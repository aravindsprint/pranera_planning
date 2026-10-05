"""The re-order engine must reproduce the numbers on the design canvas exactly."""
import unittest
from datetime import date

from pranera_planning.reorder_math import (
    cumulative_lead, stage_days_used, deepest, main_input, median, normalise_family, period_of, reorder_numbers, round_up,
    stock_project_name, next_seq,
)


class TestReorderNumbers(unittest.TestCase):
    def check(self, r, **expected):
        for k, v in expected.items():
            self.assertAlmostEqual(r[k], v, places=6, msg=k) if isinstance(v, float) else self.assertEqual(r[k], v, k)

    def test_finished_fabric_ok(self):           # SKF11355/WHITE/68OW on the canvas
        r = reorder_numbers(2700, 90, 15, 7, 30, in_stores=1200, reserved=300, wip=250, on_order=0, round_to=25)
        self.check(r, avg_daily=30.0, safety_qty=210.0, reorder_level=660.0, reorder_qty=900.0, max_level=1560.0,
                   free=900.0, position=1150.0, status="OK", suggest_qty=0.0)

    def test_dyed_fabric_order_now(self):        # DKF, lead dyeing 7 + knitting 5: 930 − 193 = 737 → 750
        r = reorder_numbers(2790, 90, 12, 3, 15, in_stores=98, reserved=0, wip=95, on_order=0, round_to=25)
        self.check(r, reorder_level=465.0, max_level=930.0, position=193.0, status="Order now", suggest_qty=750.0)

    def test_greige_order_now(self):             # GKF: 759 − 100 = 659 → 675
        r = reorder_numbers(270 + 2700, 90, 5, 3, 15, in_stores=500, reserved=400, wip=0, on_order=0, round_to=25)
        self.check(r, reorder_level=264.0, max_level=759.0, position=100.0, status="Order now", suggest_qty=675.0)

    def test_yarn_ok(self):
        r = reorder_numbers(4050, 90, 10, 5, 20, in_stores=975, reserved=0, wip=0, on_order=0, round_to=25)
        self.check(r, reorder_level=675.0, max_level=1575.0, status="OK")

    def test_yarn_near(self):                    # 160 is within 10% above 155
        r = reorder_numbers(450, 90, 21, 10, 30, in_stores=60, reserved=0, wip=0, on_order=100, round_to=25)
        self.check(r, reorder_level=155.0, position=160.0, status="Near", suggest_qty=0.0)

    def test_over_max_and_no_demand(self):
        self.assertEqual(reorder_numbers(900, 90, 10, 5, 20, 1000, 0, 0, 0)["status"], "Over max")
        self.assertEqual(reorder_numbers(0, 90, 10, 5, 20, 1000, 0, 0, 0)["status"], "No demand")

    def test_rounding_ignores_float_noise(self):
        self.assertEqual(round_up(1960.1), 1961)
        self.assertEqual(round_up(789.9, 25), 800)
        self.assertEqual(round_up(600.0000000001, 25), 600)


class TestLeadDays(unittest.TestCase):
    def test_finished_fabric_adds_every_stage_and_stops_at_yarn(self):
        stage = {"SKF": 3, "DKF": 7, "GKF": 5}
        main = {"SKF": "DKF", "DKF": "GKF", "GKF": "YRFPP090"}
        self.assertEqual(cumulative_lead("SKF", stage, main, {"YRFPP090": 10}), 15)     # the canvas: 5 + 7 + 3
        self.assertEqual(cumulative_lead("DKF", stage, main, {"YRFPP090": 10}), 12)
        self.assertEqual(cumulative_lead("YRFPP090", stage, main, {"YRFPP090": 10}), 10)  # yarn itself: supplier days

    def test_bought_lead_days_can_be_included(self):
        stage = {"SKF": 3, "DKF": 7, "GKF": 5}
        main = {"SKF": "DKF", "DKF": "GKF", "GKF": "YRFPP090"}
        self.assertEqual(cumulative_lead("SKF", stage, main, {"YRFPP090": 10}, include_bought=True), 25)

    def test_days_used_drives_the_levels(self):
        rows = [{"stage": "Knitting", "route": "In-house", "inhouse_days": 20.4, "override_days": 5},
                {"stage": "Dyeing", "route": "Job work", "jobwork_days": 25.7, "override_days": None},
                {"stage": "Finishing", "route": "Job work", "jobwork_days": 2.9, "override_days": 3}]
        self.assertEqual(stage_days_used(rows), {"knitting": 5, "finishing": 3})          # dyeing: not set, flagged
        self.assertEqual(stage_days_used(rows, use_learned=True), {"knitting": 5, "dyeing": 26, "finishing": 3})

    def test_a_loop_in_the_boms_does_not_hang(self):
        self.assertEqual(cumulative_lead("A", {"A": 2, "B": 3}, {"A": "B", "B": "A"}, {}), 5)

    def test_median_resists_forgotten_orders(self):
        self.assertEqual(median([6, 7, 7, 8, 62]), 7)
        self.assertEqual(median([4, 6]), 5)
        self.assertIsNone(median([]))


class TestStockProjects(unittest.TestCase):
    def test_family_from_commercial_name(self):
        self.assertEqual(normalise_family("GREEN GOLD KORGMOTT HT 260\t\t"), "GREEN GOLD KORGMOTT HT 260")
        self.assertEqual(normalise_family("  2tf  eco 220 "), "2TF ECO 220")
        self.assertEqual(normalise_family("-"), "")
        self.assertEqual(normalise_family(None), "")

    def test_periods(self):
        self.assertEqual(period_of(date(2026, 11, 3), "Quarter"), (2026, "Q4"))
        self.assertEqual(period_of(date(2026, 1, 31), "Quarter"), (2026, "Q1"))
        self.assertEqual(period_of("2026-10-15", "Month"), (2026, "OCT"))

    def test_seasons_cross_the_new_year(self):
        seasons = [("Summer", 2), ("Winter", 8)]
        self.assertEqual(period_of(date(2026, 5, 1), "Season", seasons), (2026, "SUMMER"))
        self.assertEqual(period_of(date(2026, 9, 1), "Season", seasons), (2026, "WINTER"))
        self.assertEqual(period_of(date(2027, 1, 10), "Season", seasons), (2026, "WINTER"))

    def test_project_name(self):
        self.assertEqual(stock_project_name("{YY}STK-{FAMILY}-{PERIOD}", 2026, "2TF ECO 220", "Q4"), "26STK-2TF ECO 220-Q4")
        self.assertEqual(stock_project_name(None, 2026, "YARN", "Q4", 1), "26STK-YARN-Q4-01")   # default has {SEQ}


class TestGroupRulesAndBoms(unittest.TestCase):
    def test_the_nearest_group_rule_wins(self):
        rules = [(1, 100, "ALL"), (10, 40, "FABRIC"), (12, 20, "FABRIC/KNITS")]
        self.assertEqual(deepest((13, 14), rules), "FABRIC/KNITS")
        self.assertEqual(deepest((30, 31), rules), "FABRIC")
        self.assertEqual(deepest((60, 61), rules), "ALL")
        self.assertIsNone(deepest((200, 201), rules))

    def test_main_input_is_the_fabric_not_the_trim(self):
        rows = [("GKF11355", 105, "Kgs", 1), ("DYE-RED", 300, "Gms", 0), ("SALT", 110, "Kgs", 0)]
        self.assertEqual(main_input(rows, "Kgs"), "GKF11355")
        self.assertEqual(main_input([("YRFPP090", 90, "Kgs", 1), ("YRSPE011", 10, "Kgs", 1)], "Kgs"), "YRFPP090")
        self.assertEqual(main_input([("X", 1, "Nos", 0), ("Y", 3, "Nos", 0)], "Kgs"), "Y")
        self.assertIsNone(main_input([], "Kgs"))



class TestStockProjectSequence(unittest.TestCase):
    P = "{YY}STK-{FAMILY}-{PERIOD}-{SEQ}"

    def test_first_plan_of_a_family_and_period_is_01(self):
        seq = next_seq(self.P, 2026, "2TF ECO 220", "Q4", [])
        self.assertEqual(stock_project_name(self.P, 2026, "2TF ECO 220", "Q4", seq), "26STK-2TF ECO 220-Q4-01")

    def test_second_plan_in_the_same_period_is_02(self):
        seq = next_seq(self.P, 2026, "2TF ECO 220", "Q4", ["26STK-2TF ECO 220-Q4-01"])
        self.assertEqual(stock_project_name(self.P, 2026, "2TF ECO 220", "Q4", seq), "26STK-2TF ECO 220-Q4-02")

    def test_other_families_periods_and_gaps(self):
        existing = ["26STK-2TF ECO 220-Q4-01", "26STK-2TF ECO 220-Q4-03", "26STK-2TF ECO 220-Q3-07",
                    "26STK-2TF ECO 2200-Q4-09", "26STK-YARN-Q4-05", "26STK-2TF ECO 220-Q4"]
        self.assertEqual(next_seq(self.P, 2026, "2TF ECO 220", "Q4", existing), 4)    # gaps aren't reused
        self.assertEqual(next_seq(self.P, 2026, "YARN", "Q4", existing), 6)
        self.assertEqual(next_seq(self.P, 2027, "2TF ECO 220", "Q1", existing), 1)

    def test_a_pattern_without_seq_keeps_one_project_per_period(self):
        self.assertIsNone(next_seq("{YY}STK-{FAMILY}-{PERIOD}", 2026, "YARN", "Q4", []))
        self.assertEqual(stock_project_name("{YY}STK-{FAMILY}-{PERIOD}", 2026, "YARN", "Q4"), "26STK-YARN-Q4")


if __name__ == "__main__":
    unittest.main()


from pranera_planning.reorder_math import duplicate_stages, route_days, stage_route_days  # noqa: E402


class TestDaysPerRoute(unittest.TestCase):
    """Each stage has In-house days (override_days) and Job work days (jobwork_override_days)."""
    ROWS = [
        {"stage": "Knitting", "route": "In-house", "override_days": 5, "jobwork_override_days": 10},
        {"stage": "Dyeing", "route": "Job work", "override_days": 7, "jobwork_override_days": 12},
        {"stage": "Finishing", "route": "Job work", "override_days": 3, "jobwork_override_days": None},
        {"stage": "Compacting", "route": "In-house", "jobwork_days": 4.2},
    ]

    def test_report_uses_the_usual_routes_days(self):
        self.assertEqual(stage_days_used(self.ROWS), {"knitting": 5, "dyeing": 12, "finishing": 3})

    def test_learned_only_fills_a_route_without_days(self):
        self.assertEqual(stage_days_used(self.ROWS, use_learned=True)["compacting"], 5)

    def test_plan_gets_both_routes(self):
        days = stage_route_days(self.ROWS)
        self.assertEqual(days["knitting"], {"In-house": 5, "Job work": 10})
        self.assertEqual(days["finishing"], {"In-house": 3, "Job work": None})

    def test_route_days_rounds_up(self):
        self.assertEqual(route_days({"jobwork_override_days": 9.2}, "Job work"), 10)

    def test_duplicate_stage_names(self):
        rows = self.ROWS + [{"stage": " knitting "}]
        self.assertEqual(duplicate_stages(rows), ["Knitting"])
        self.assertEqual(duplicate_stages(self.ROWS), [])
