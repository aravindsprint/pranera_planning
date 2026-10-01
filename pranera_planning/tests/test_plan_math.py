"""The plan calculation must reproduce the four scenarios on the design canvas exactly."""
import unittest

from pranera_planning.plan_math import allocate_lots, build_plan, scenario_rules

SKF, DKF, GKF, YPP, YSP = "SKF11355/WHITE/68OW", "DKF11355/WHITE/68OW", "GKF11355/GREIGE/28OW", "YRFPP090/GREIGE", "YRSPE011/GREIGE"
CHAIN = {SKF: [(DKF, 1.03)], DKF: [(GKF, 1.05)], GKF: [(YPP, 0.90), (YSP, 0.10)]}


def items(**stock):
    out = {}
    for code in (SKF, DKF, GKF, YPP, YSP):
        made = code in CHAIN
        out[code] = {"made": made, "bom": CHAIN.get(code, []), "round_to": 1 if made else 25, "own": 0, "coming": 0, "borrowable": 0}
    for code, values in stock.items():
        out[code].update(values)
    return out


def by_item(plan):
    return {r["item"]: r for r in plan["levels"]}


class TestScenarios(unittest.TestCase):
    def check(self, row, **expected):
        for k, v in expected.items():
            self.assertAlmostEqual(row[k], v, places=6, msg=f"{row['item']} {k}")

    def test_1_purchase_made_to_stock(self):
        p = by_item(build_plan(
            [{"item": YPP, "qty": 1575, "mode": "top_up"}, {"item": YSP, "qty": 305, "mode": "top_up"}],
            items(**{YPP: {"own": 975, "borrowable": 500}, YSP: {"own": 60, "coming": 100}}),
            scenario_rules("Purchase", "Made to stock")))
        self.check(p[YPP], need=1575, own=975, reserve=0, request=600)        # a purchase pool never borrows
        self.check(p[YSP], need=305, own=60, coming=100, short=145, request=150)
        self.assertNotIn(GKF, p)

    def test_2_purchase_made_to_order(self):
        p = by_item(build_plan([{"item": YPP, "qty": 1000}], items(**{YPP: {"borrowable": 975}}),
                               scenario_rules("Purchase", "Made to order")))
        self.check(p[YPP], need=1000, reserve=975, short=25, request=25)

    def test_purchase_project_never_explodes_a_bom(self):
        p = by_item(build_plan([{"item": SKF, "qty": 100}], items(), scenario_rules("Purchase", "Made to order")))
        self.assertEqual(list(p), [SKF])
        self.assertFalse(p[SKF]["made"])

    def test_3_production_made_to_stock(self):
        p = by_item(build_plan(
            [{"item": SKF, "qty": 5000, "mode": "top_up"}],
            items(**{SKF: {"own": 900, "coming": 250}, DKF: {"own": 98, "coming": 95},
                     YPP: {"borrowable": 975}, YSP: {"borrowable": 60}}),
            scenario_rules("Production", "Made to stock")))
        self.check(p[SKF], need=5000, own=900, coming=250, short=3850, request=3850)
        self.check(p[DKF], need=3965.5, own=98, coming=95, short=3772.5, request=3773)
        self.check(p[GKF], need=3961.65, short=3961.65, request=3962)
        self.check(p[YPP], need=3565.8, reserve=975, short=2590.8, request=2600)
        self.check(p[YSP], need=396.2, reserve=60, short=336.2, request=350)

    def test_4_production_made_to_order(self):
        p = by_item(build_plan(
            [{"item": SKF, "qty": 2000}, {"item": GKF, "qty": 300}],
            items(**{DKF: {"own": 98}, GKF: {"own": 400}, YPP: {"borrowable": 975}, YSP: {"coming": 100, "borrowable": 60}}),
            scenario_rules("Production", "Made to order")))
        self.check(p[SKF], request=2000)
        self.check(p[DKF], need=2060, own=98, request=1962)
        self.check(p[GKF], need=2360.1, own=400, short=1960.1, request=1961)    # 1,962 × 1.05 + 300 sold, added up first
        self.check(p[YPP], need=1764.9, reserve=975, request=800)
        self.check(p[YSP], need=196.1, coming=100, reserve=60, short=36.1, request=50)
        order = [r["item"] for r in build_plan([{"item": SKF, "qty": 2000}, {"item": GKF, "qty": 300}], items(),
                                               scenario_rules("Production", "Made to order"))["levels"]]
        self.assertLess(order.index(DKF), order.index(GKF))                     # greige waits for both of its parents


class TestModes(unittest.TestCase):
    def test_make_mode_does_not_take_own_stock_at_its_level(self):
        p = by_item(build_plan([{"item": GKF, "qty": 675, "mode": "make"}], items(**{GKF: {"own": 100}, YPP: {"own": 300}}),
                               scenario_rules("Production", "Made to stock")))
        self.assertEqual(p[GKF]["request"], 675)                                 # the report's suggestion already counted stock
        self.assertEqual(p[YPP]["own"], 300)                                     # the levels below still use it
        self.assertAlmostEqual(p[YPP]["need"], 607.5)

    def test_nothing_needed_nothing_requested(self):
        p = by_item(build_plan([{"item": SKF, "qty": 100, "mode": "top_up"}], items(**{SKF: {"own": 150}}),
                               scenario_rules("Production", "Made to stock")))
        self.assertEqual(p[SKF]["request"], 0)
        self.assertNotIn(DKF, p)

    def test_a_loop_in_the_boms_does_not_hang(self):
        loop = {"A": {"made": True, "bom": [("B", 1)], "round_to": 1}, "B": {"made": True, "bom": [("A", 1)], "round_to": 1}}
        plan = build_plan([{"item": "A", "qty": 10}], loop, scenario_rules("Production", "Made to order"))
        self.assertEqual(sorted(r["item"] for r in plan["levels"]), ["A", "B"])



class TestAllocation(unittest.TestCase):
    def test_whole_lots_then_part_of_the_last(self):
        lots = [{"batch_no": "B1", "roll_no": "R1", "qty": 25}, {"batch_no": "B1", "roll_no": "R2", "qty": 25},
                {"batch_no": "B1", "roll_no": "R3", "qty": 25}]
        picked, missing = allocate_lots(lots, 60)
        self.assertEqual([(p["roll_no"], p["qty"]) for p in picked], [("R1", 25), ("R2", 25), ("R3", 10)])
        self.assertEqual(missing, 0)

    def test_not_enough(self):
        picked, missing = allocate_lots([{"batch_no": "B", "qty": 975}], 1000)
        self.assertEqual((picked[0]["qty"], missing), (975, 25))


if __name__ == "__main__":
    unittest.main()
