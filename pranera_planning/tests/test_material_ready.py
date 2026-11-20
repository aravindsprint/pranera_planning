"""material_ready.assess: is the input there for a stage?"""
import sys
import unittest

from pranera_planning.tests.test_stock_entry_checks import _fake_frappe


class TestAssess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved = {n: sys.modules.get(n) for n in ("frappe", "frappe.utils", "pranera_planning.material_ready")}
        fake = _fake_frappe()
        from datetime import date, datetime
        fake["frappe.utils"].getdate = lambda d: d if isinstance(d, date) else datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
        sys.modules.update(fake)
        sys.modules.pop("pranera_planning.material_ready", None)
        import pranera_planning.material_ready as M
        cls.M = M

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            sys.modules.pop(n, None) if m is None else sys.modules.__setitem__(n, m)

    def line(self, need, tr=0, st=0, exp=None):
        return {"need": need, "transferred": tr, "in_stores": st, "expected": exp}

    def test_ready(self):
        r = self.M.assess([self.line(1000, tr=400, st=600)], "2026-11-10")
        self.assertEqual((r["status"], r["pct"], r["late"]), ("Ready", 100, False))

    def test_partial_expected_in_time(self):
        r = self.M.assess([self.line(1000, st=600, exp="2026-11-05")], "2026-11-10")
        self.assertEqual((r["status"], r["pct"], r["expected"], r["late"]), ("Partial", 60, "2026-11-05", False))

    def test_not_ready_and_late(self):
        r = self.M.assess([self.line(1000, exp="2026-11-21")], "2026-11-10")
        self.assertEqual((r["status"], r["late"]), ("Not ready", True))

    def test_nothing_planned_for_the_rest_is_late(self):
        self.assertTrue(self.M.assess([self.line(1000, st=100)], "2026-11-10")["late"])


if __name__ == "__main__":
    unittest.main()
