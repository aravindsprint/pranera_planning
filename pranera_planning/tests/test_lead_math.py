"""lead_math: the ranked lead-day sources, splitting open Purchase Orders into in time and
arriving later, and which Purchase Order lines are too early for their supplier."""
import unittest

from pranera_planning import lead_math as L


class TestSourceOrder(unittest.TestCase):
    def test_no_rows_means_default_order_all_on(self):
        self.assertEqual(L.source_order([]), L.DEFAULT_ORDER)

    def test_rank_and_switches_follow_the_rows(self):
        rows = [{"source": "Item's Lead Time Days", "enabled": 1}, {"source": "Supplier Items row", "enabled": 0},
                {"source": "Supplier's usual lead days", "enabled": 1}, {"source": "Item-group rule", "enabled": 1}]
        self.assertEqual(L.source_order(rows), [L.ITEM, L.SUPPLIER, L.GROUP])

    def test_unknown_and_repeated_sources_are_ignored(self):
        rows = [{"source": "Nonsense", "enabled": 1}, {"source": "supplier", "enabled": 1}, {"source": "supplier", "enabled": 1}]
        self.assertEqual(L.source_order(rows), [L.SUPPLIER])


class TestPickLead(unittest.TestCase):
    VALUES = {L.SUPPLIER_ITEM: 45, L.SUPPLIER: 15, L.ITEM: 20, L.GROUP: 10}

    def test_first_source_with_a_number_wins(self):
        self.assertEqual(L.pick_lead(L.DEFAULT_ORDER, self.VALUES), (45.0, L.SUPPLIER_ITEM))

    def test_melange_row_missing_falls_to_the_supplier(self):
        self.assertEqual(L.pick_lead(L.DEFAULT_ORDER, {**self.VALUES, L.SUPPLIER_ITEM: None}), (15.0, L.SUPPLIER))

    def test_switched_off_source_is_skipped(self):
        self.assertEqual(L.pick_lead([L.ITEM, L.GROUP], self.VALUES), (20.0, L.ITEM))

    def test_zero_counts_as_not_set(self):
        self.assertEqual(L.pick_lead(L.DEFAULT_ORDER, {L.SUPPLIER: 0, L.GROUP: 10}), (10.0, L.GROUP))

    def test_nothing_set(self):
        self.assertEqual(L.pick_lead(L.DEFAULT_ORDER, {}), (0.0, None))


class TestDescribe(unittest.TestCase):
    def test_supplier_source_names_the_supplier(self):
        self.assertEqual(L.describe(45, L.SUPPLIER, "ZHEJIANG", "default"), "Supplier's usual lead days for ZHEJIANG")

    def test_fallback_supplier_is_explained(self):
        self.assertIn("no default supplier: latest Purchase Order", L.describe(45, L.SUPPLIER, "ZHEJIANG", "latest Purchase Order"))

    def test_no_source(self):
        self.assertTrue(L.describe(0, None).startswith("No lead days"))


class TestSplitOnOrder(unittest.TestCase):
    LINES = [("YARN30", 1500, "2026-11-14", "PO-0123"),     # China container: 40 days out
             ("YARN30", 400, "2026-10-12", "PO-0130"),      # India: next week
             ("YARN30", 200, "2026-09-01", "PO-0099"),      # overdue: still expected
             ("MELANGE", 300, "2026-11-30", "PO-0140")]

    def test_lines_due_after_a_new_order_would_arrive_are_later(self):
        later, lines = L.split_on_order(self.LINES, "2026-10-05", {"YARN30": 15, "MELANGE": 0})
        self.assertEqual(later, {"YARN30": 1500.0})
        self.assertEqual(lines["YARN30"], [("PO-0123", 1500.0, "2026-11-14")])

    def test_due_exactly_at_lead_is_in_time(self):
        later, _l = L.split_on_order([("YARN30", 10, "2026-10-20", "PO-1")], "2026-10-05", {"YARN30": 15})
        self.assertEqual(later, {})

    def test_note(self):
        self.assertEqual(L.later_note([("PO-0123", 1500.0, "2026-11-14")], "Kgs"), "1,500 Kgs on PO-0123 due 2026-11-14")


class TestLateLines(unittest.TestCase):
    def lead(self, code):
        return {"YARN30": (45, L.SUPPLIER), "MELANGE": (45, L.SUPPLIER_ITEM), "DYE": (20, L.ITEM)}.get(code, (0, None))

    def rows(self, date):
        return [{"idx": 1, "item_code": "YARN30", "schedule_date": date}]

    def test_too_early_for_the_supplier_blocks(self):
        out = L.late_lines(self.rows("2026-11-05"), "2026-10-06", 0, self.lead)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["earliest"], out[0]["blocks"]), ("2026-11-20", True))

    def test_on_the_earliest_date_passes(self):
        self.assertEqual(L.late_lines(self.rows("2026-11-20"), "2026-10-06", 0, self.lead), [])

    def test_grace_days(self):
        self.assertEqual(L.late_lines(self.rows("2026-11-18"), "2026-10-06", 3, self.lead), [])
        self.assertEqual(len(L.late_lines(self.rows("2026-11-16"), "2026-10-06", 3, self.lead)), 1)

    def test_item_lead_days_only_warn(self):
        out = L.late_lines([{"idx": 2, "item_code": "DYE", "schedule_date": "2026-10-10"}], "2026-10-06", 0, self.lead)
        self.assertFalse(out[0]["blocks"])

    def test_no_lead_days_no_check(self):
        self.assertEqual(L.late_lines([{"idx": 3, "item_code": "OTHER", "schedule_date": "2026-10-06"}], "2026-10-06", 0, self.lead), [])


if __name__ == "__main__":
    unittest.main()
