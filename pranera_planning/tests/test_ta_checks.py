"""ta_checks against the frappe stand-in: the booked machine copied onto a Work Order and
enforced on Job Cards, and a Job Card not started before its input is transferred."""
import importlib
import sys
import types
import unittest

from pranera_planning.tests.test_stock_entry_checks import ValidationError, _dict, _fake_frappe


class Doc(_dict):
    def is_new(self):
        return False

    def add_comment(self, kind, text):
        self.setdefault("comments", []).append(text)


class TestTaChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "pranera_planning.ta_checks", "pranera_planning.reservation"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        fake = _fake_frappe()
        fake["frappe.utils"].escape_html = lambda s: s
        sys.modules.update(fake)
        res = types.ModuleType("pranera_planning.reservation")
        res.mr_check_settings = lambda: {"roles": {"Manufacturing Manager"}}
        sys.modules["pranera_planning.reservation"] = res
        sys.modules.pop("pranera_planning.ta_checks", None)
        cls.C = importlib.import_module("pranera_planning.ta_checks")
        cls.f = fake["frappe"]

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            sys.modules.pop(n, None) if m is None else sys.modules.__setitem__(n, m)

    def setUp(self):
        C = self.C
        C._mode = lambda: "Block"
        C.booked_for = lambda project, item: ("KM-12", "Knitting")
        C._stage_of_ws = lambda ws: "knitting"
        self.f.roles = ["Manufacturing User"]
        self.f.messages.clear()

    def wo(self, ws=None, action=None, **kw):
        d = Doc(project="SAL-1", production_item="GKF", docstatus=0, _action=action, flags=_dict(),
                operations=[_dict(idx=1, operation="KNITTING", workstation=ws)], **kw)
        return d

    def test_booked_machine_is_copied(self):
        d = self.wo()
        self.C.work_order(d)
        self.assertEqual(d.operations[0].workstation, "KM-12")

    def test_other_machine_blocked_on_submit_only(self):
        self.C.work_order(self.wo("KM-07"))                                   # draft save: fine
        with self.assertRaises(ValidationError):
            self.C.work_order(self.wo("KM-07", action="submit"))

    def test_override_with_reason(self):
        self.f.roles = ["Manufacturing Manager"]
        d = self.wo("KM-07", action="submit", ta_override_reason="KM-12 under repair")
        self.C.work_order(d)
        self.assertIn("KM-12 under repair", d.comments[0])

    def jc(self, ws="KM-12", started=True, transferred=100):
        self.f.db.get_value = lambda dt, name, fields=None, as_dict=False, **kw: _dict(
            project="SAL-1", production_item="GKF", skip_transfer=0, material_transferred_for_manufacturing=transferred)
        return Doc(work_order="WO-1", workstation=ws, flags=_dict(),
                   time_logs=[_dict(from_time="2026-11-10 08:00")] if started else [])

    def test_job_card_on_another_machine(self):
        with self.assertRaises(ValidationError):
            self.C.job_card(self.jc("KM-07"))
        self.C.job_card(self.jc("KM-12"))

    def test_job_card_started_before_input_transferred(self):
        with self.assertRaises(ValidationError):
            self.C.job_card(self.jc(transferred=0))
        self.C.job_card(self.jc(started=False, transferred=0))               # not started: fine

    def test_warn_mode(self):
        self.C._mode = lambda: "Warn"
        self.C.job_card(self.jc("KM-07"))
        self.assertEqual(len(self.f.messages), 1)


if __name__ == "__main__":
    unittest.main()
