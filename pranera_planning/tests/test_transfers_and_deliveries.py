"""Material Transfers out of stores, and deliveries of reserved / made-to-order stock,
against the frappe stand-in (same world as test_stock_entry_checks: batch 25PUR001/REL/1234,
2,000 kg in Stores - PSS, all reserved for 25PROD001)."""
import importlib
import sys
import unittest

from pranera_planning.tests.test_stock_entry_checks import (
    RESERVATION, WORLD, Doc, ValidationError, _dict, _fake_frappe, _state, row,
)

BATCH = "25PUR001/REL/1234"


class TestTransfersAndDeliveries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "pranera_planning.reservation"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        fakes = _fake_frappe()
        sys.modules.update(fakes)
        sys.modules.pop("pranera_planning.reservation", None)
        cls.R = importlib.import_module("pranera_planning.reservation")
        cls.frappe = fakes["frappe"]
        R = cls.R
        R.is_pool_warehouse = lambda wh: not (wh or "").startswith("Work In Progress")
        R.get_produced_owners = lambda batches: {}
        R.get_reservation_state = _state
        R.get_stock_locations = lambda batches: {BATCH: {"Stores - PSS": {"available": 2000.0, "rolls": {}}},
                                                 "B-MTO": {"Stores - PSS": {"available": 400.0, "rolls": {}}}}
        R.delivery_mode = lambda: "block"
        WORLD["Project Stock Reservation"] = lambda flt: (
            [RESERVATION.batch_no] if flt and BATCH in str(flt.get("batch_no")) else [])
        WORLD["Sales Order"] = lambda flt: [_dict(name="SO-1", project="25PROD001"), _dict(name="SO-7", project="26PTIN1710"),
                                            _dict(name="SO-9", project=None)]
        WORLD["Project"] = lambda flt: [_dict(name="26PTIN1710", sales_order="SO-7")]

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m
        WORLD.clear()

    def outcome(self, fn, doc):
        self.frappe.logged.clear()
        self.frappe.messages.clear()
        try:
            fn(doc)
            result = "allowed"
        except ValidationError as e:
            self.last = str(e)
            result = "blocked"
        self.assertEqual(self.frappe.logged, [], "the check crashed — it would let everything through")
        return result

    # ── Material Transfer ─────────────────────────────────────────────────────
    def transfer(self, target, project, qty=100):
        r = row("r1", BATCH, qty)
        r.t_warehouse = target
        self.R.line_projects = lambda d: {x.name: project for x in d.items}
        return Doc(name="MAT-STE-T", stock_entry_type="Material Transfer", purpose="Material Transfer", items=[r],
                   work_order=None, project=project)

    def test_transfer_out_of_stores_for_another_project_is_blocked(self):
        self.assertEqual(self.outcome(self.R.validate_stock_entry, self.transfer("Work In Progress - PSS", "25PROD002")), "blocked")

    def test_transfer_out_of_stores_for_the_reserving_project_is_allowed(self):
        self.assertEqual(self.outcome(self.R.validate_stock_entry, self.transfer("Work In Progress - PSS", "25PROD001")), "allowed")

    def test_transfer_out_of_stores_without_a_project_asks_for_one(self):
        self.assertEqual(self.outcome(self.R.validate_stock_entry, self.transfer("Work In Progress - PSS", None)), "blocked")
        self.assertIn("set the Project", self.last)

    def test_transfer_between_stores_is_not_an_issue(self):
        self.assertEqual(self.outcome(self.R.validate_stock_entry, self.transfer("Stores 2 - PSS", "25PROD002")), "allowed")

    # ── deliveries ───────────────────────────────────────────────────────────
    def invoice(self, batch, qty, so, **kw):
        return Doc(doctype="Sales Invoice", is_return=kw.get("is_return", 0), update_stock=kw.get("update_stock", 1),
                   items=[Doc(warehouse="Stores - PSS", batch_no=batch, stock_qty=qty, qty=qty, sales_order=so)])

    def test_stock_reserved_for_a_project_ships_against_its_orders_only(self):
        self.assertEqual(self.outcome(self.R.check_delivery, self.invoice(BATCH, 500, "SO-1")), "allowed")
        self.assertEqual(self.outcome(self.R.check_delivery, self.invoice(BATCH, 500, "SO-9")), "blocked")
        self.assertIn("reserved for another order", self.last)
        self.assertEqual(self.outcome(self.R.check_delivery, self.invoice(BATCH, 500, None)), "blocked")

    def test_made_to_order_stock_ships_only_against_its_sales_order(self):
        self.R.get_owners = lambda batches: {"B-MTO": "26PTIN1710"}
        try:
            self.assertEqual(self.outcome(self.R.check_delivery, self.invoice("B-MTO", 100, "SO-9")), "blocked")
            self.assertIn("ships only against SO-7", self.last)
            self.assertEqual(self.outcome(self.R.check_delivery, self.invoice("B-MTO", 100, "SO-7")), "allowed")
        finally:
            self.R.get_owners = self._owners

    def test_returns_and_invoices_without_stock_are_left_alone(self):
        self.assertEqual(self.outcome(self.R.check_delivery, self.invoice(BATCH, 500, "SO-9", is_return=1)), "allowed")
        self.assertEqual(self.outcome(self.R.check_delivery, self.invoice(BATCH, 500, "SO-9", update_stock=0)), "allowed")

    def test_warn_mode_lets_it_through_with_a_message(self):
        self.R.delivery_mode = lambda: "warn"
        try:
            self.assertEqual(self.outcome(self.R.check_delivery, self.invoice(BATCH, 500, "SO-9")), "allowed")
            self.assertEqual(len(self.frappe.messages), 1)
        finally:
            self.R.delivery_mode = lambda: "block"

    @classmethod
    def _owners(cls, batches):
        return {}



if __name__ == "__main__":
    unittest.main()
