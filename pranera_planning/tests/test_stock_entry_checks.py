"""Runs the REAL Stock Entry checks (validate_stock_entry) end to end against a minimal
stand-in for frappe with canned data — so a crash inside the checks (which would let an
entry through) is caught here, not on the shop floor.

The stand-in is installed only for these tests and the real modules are restored after, so
this also runs inside a bench where frappe is installed.
"""
import importlib
import sys
import types
import unittest

WORLD = {}


class ValidationError(Exception):
    pass


class _dict(dict):
    __getattr__ = dict.get

    def __setattr__(self, k, v):
        self[k] = v


class Doc:
    """Like a frappe document: attributes plus .get()."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def get(self, k, d=None):
        return self.__dict__.get(k, d)

    def __getattr__(self, k):
        return None


def _fake_frappe():
    f = types.ModuleType("frappe")
    f.ValidationError = ValidationError
    f._dict = _dict
    f._ = lambda s: s
    f.conf = _dict()
    f.logged, f.messages = [], []

    def throw(msg, title=None):
        raise ValidationError(f"{title}: {msg}")

    f.throw = throw
    f.msgprint = lambda msg, title=None, indicator=None, alert=False: f.messages.append((title, msg))
    f.log_error = lambda title=None, message=None: f.logged.append((title, sys.exc_info()[1]))
    f.as_json = str
    f.whitelist = lambda *a, **k: (a[0] if a and callable(a[0]) else (lambda fn: fn))
    f.has_permission = lambda *a, **k: True
    f.get_all = lambda doctype, filters=None, fields=None, pluck=None, **kw: WORLD.get(doctype, lambda flt: [])(filters)
    f.db = types.SimpleNamespace(get_value=lambda *a, **k: None, sql=lambda *a, **k: [], exists=lambda *a, **k: True,
                                 has_column=lambda *a: True, escape=repr)
    f.cache = lambda: types.SimpleNamespace(get_value=lambda k: {}, set_value=lambda *a, **k: None,
                                            delete_value=lambda k: None)
    u = types.ModuleType("frappe.utils")
    u.flt = lambda v, *a: float(v or 0)
    u.now_datetime = lambda: "now"
    f.utils = u
    return {"frappe": f, "frappe.utils": u}


RESERVATION = _dict(name="PSR-00009", production_project="25PROD001", item_code="YRFPP090/GREIGE",
                    batch_no="25PUR001/REL/1234", warehouse="Stores - PSS", roll_no="")


def _state(batches, **kw):
    return {"25PUR001/REL/1234": {
        "available": 2000.0,
        "locations": {"Stores - PSS": {"available": 2000.0, "rolls": {}}},
        "reservations": [{"name": "PSR-00009", "status": "Active", "production_project": "25PROD001",
                          "warehouse": "Stores - PSS", "roll_no": "", "reserved_qty": 2000.0,
                          "issued_qty": 0.0, "remaining_qty": 2000.0}],
    }}


def row(name, batch, qty, wh="Stores - PSS", item="YRFPP090/GREIGE"):
    return Doc(name=name, item_code=item, batch_no=batch, s_warehouse=wh, is_finished_item=0,
               transfer_qty=qty, qty=qty, custom_roll_no="")


def entry(rows):
    return Doc(name="MAT-STE-TEST", stock_entry_type="Material Transfer for Manufacture", items=rows,
               work_order="MFG-WO-TEST", project=None)


class TestStockEntryChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "pranera_planning.reservation"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        fakes = _fake_frappe()
        sys.modules.update(fakes)
        sys.modules.pop("pranera_planning.reservation", None)
        cls.R = importlib.import_module("pranera_planning.reservation")
        cls.frappe = fakes["frappe"]
        cls.R.is_pool_warehouse = lambda wh: not (wh or "").startswith("Work In Progress")
        cls.R.get_produced_owners = lambda batches: {}
        cls.R.get_reservation_state = _state
        WORLD["Project Stock Reservation"] = lambda flt: [RESERVATION.batch_no] if flt and flt.get("batch_no") else [RESERVATION]

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m
        WORLD.clear()

    def check(self, rows, project="25PROD001"):
        """'blocked' or 'allowed'; fails the test if the check itself crashed."""
        self.R.line_projects = lambda d: {r.name: project for r in d.items}
        self.frappe.logged.clear()
        try:
            self.R.validate_stock_entry(entry(rows))
            outcome = "allowed"
        except ValidationError:
            outcome = "blocked"
        self.assertEqual(self.frappe.logged, [], "the check crashed — entries would slip through")
        return outcome

    def test_other_batch_while_reservation_waits_is_blocked(self):
        self.assertEqual(self.check([row("r1", "25PTIN001/REL/1234", 500)]), "blocked")

    def test_free_batch_while_reservation_waits_is_blocked(self):
        self.assertEqual(self.check([row("r1", "25PUR001/REL/5678", 500)]), "blocked")

    def test_reserved_batch_from_another_warehouse_is_blocked(self):
        self.assertEqual(self.check([row("r1", "25PUR001/REL/1234", 500, wh="Stores 2 - PSS")]), "blocked")

    def test_reserved_batch_from_reserved_warehouse_is_allowed(self):
        self.assertEqual(self.check([row("r1", "25PUR001/REL/1234", 500)]), "allowed")

    def test_all_reserved_plus_extra_is_allowed(self):
        self.assertEqual(self.check([row("r1", "25PUR001/REL/1234", 2000), row("r2", "25PUR001/REL/5678", 300)]), "allowed")

    def test_another_project_taking_reserved_stock_is_blocked(self):
        self.assertEqual(self.check([row("r1", "25PUR001/REL/1234", 500)], project="25PROD002"), "blocked")


    # ── Roll Wise Pick List: the rolls it names count, even when the row names none ──
    def _pick_world(self, picked_rolls):
        """Greige batch G1 produced for 25PROD001: rolls R1 (25) and R4 (25) in Stores - PSS,
        R4 reserved for 25PROD002. The entry's pick list names `picked_rolls`."""
        R, f = self.R, self.frappe
        saved = (R.get_reservation_state, R.get_produced_owners, f.db.sql, f.db.exists)
        R.get_produced_owners = lambda batches: {"G1": "25PROD001"}
        R.get_reservation_state = lambda batches, **kw: {"G1": {
            "available": 50.0,
            "locations": {"Stores - PSS": {"available": 50.0, "rolls": {"R1": 25.0, "R4": 25.0}}},
            "reservations": [{"name": "PSR-R4", "status": "Active", "production_project": "25PROD002",
                              "warehouse": "Stores - PSS", "roll_no": "R4", "reserved_qty": 25.0,
                              "issued_qty": 0.0, "remaining_qty": 25.0}]}}
        f.db.exists = lambda *a, **k: True
        f.db.sql = lambda q, *a, **k: [("G1", r, 25.0, 25.0) for r in picked_rolls] if "Roll Wise Pick Item" in q else []
        WORLD["Project Stock Reservation"] = lambda flt: (
            ["G1"] if flt and flt.get("batch_no") else
            [_dict(name="PSR-R4", production_project="25PROD002", item_code="GKF", batch_no="G1",
                   warehouse="Stores - PSS", roll_no="R4")])
        return saved

    def _restore(self, saved):
        self.R.get_reservation_state, self.R.get_produced_owners, self.frappe.db.sql, self.frappe.db.exists = saved
        WORLD["Project Stock Reservation"] = lambda flt: [RESERVATION.batch_no] if flt and flt.get("batch_no") else [RESERVATION]

    def _send(self, qty):
        r = row("r1", "G1", qty, item="GKF")
        d = entry([r])
        d.stock_entry_type = "Send to Subcontractor"
        d.custom_roll_wise_pick_list = "PICK/0001"
        return d

    def _run(self, d, project):
        self.R.line_projects = lambda dd: {x.name: project for x in dd.items}
        self.frappe.logged.clear()
        try:
            self.R.validate_stock_entry(d)
            outcome = "allowed"
        except ValidationError:
            outcome = "blocked"
        self.assertEqual(self.frappe.logged, [], "the check crashed")
        return outcome

    def test_pick_list_naming_a_roll_not_reserved_for_you_is_blocked(self):
        saved = self._pick_world(["R1"])
        try:
            self.assertEqual(self._run(self._send(25), "25PROD002"), "blocked")
        finally:
            self._restore(saved)

    def test_pick_list_naming_your_reserved_roll_is_allowed(self):
        saved = self._pick_world(["R4"])
        try:
            self.assertEqual(self._run(self._send(25), "25PROD002"), "allowed")
        finally:
            self._restore(saved)

    def test_past_issue_is_split_into_its_picked_rolls(self):
        saved_moves = self.R.get_pick_list_moves
        self.R.get_pick_list_moves = lambda batches: {"G1": [
            {"roll_no": "R1", "weight": 25.0, "voucher": "STE-1", "s_warehouse": "Stores - PSS", "t_warehouse": "SUB - X"},
            {"roll_no": "R2", "weight": 25.0, "voucher": "STE-1", "s_warehouse": "Stores - PSS", "t_warehouse": "SUB - X"}]}
        try:
            lines = [_dict(batch_no="G1", voucher="STE-1", roll_no="", qty=60.0, warehouse="Stores - PSS")]
            split = self.R._split_by_pick_lists(lines, ["G1"])
            self.assertEqual([(l.roll_no, l.qty) for l in split], [("R1", 25.0), ("R2", 25.0), ("", 10.0)])
        finally:
            self.R.get_pick_list_moves = saved_moves


if __name__ == "__main__":
    unittest.main()
