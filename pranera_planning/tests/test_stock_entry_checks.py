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


if __name__ == "__main__":
    unittest.main()
