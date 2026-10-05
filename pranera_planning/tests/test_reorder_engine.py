"""reorder.calculate end to end, against the frappe stand-in, fed the design canvas's stock,
demand and settings: it must write exactly the canvas's re-order numbers."""
import importlib
import sys
import unittest

from pranera_planning.tests.test_stock_entry_checks import WORLD, _dict, _fake_frappe

ITEMS = {
    "SKF11355/WHITE/68OW": ("FABRIC FINISHED", "2TF ECO 220"),
    "DKF11355/WHITE/68OW": ("FABRIC DYED", "2TF ECO 220"),
    "GKF11355/GREIGE/28OW": ("FABRIC GREIGE", "2TF ECO 220"),
    "YRFPP090/GREIGE": ("YARN", ""),
    "YRSPE011/GREIGE": ("YARN", "-"),
}
GROUPS = {"FABRIC FINISHED": (2, 3), "FABRIC DYED": (4, 5), "FABRIC GREIGE": (6, 7), "YARN": (10, 11)}


class TestReorderEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "pranera_planning.reservation", "pranera_planning.reorder"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        fake = _fake_frappe()
        fake["frappe.utils"].add_days = lambda d, n: d
        fake["frappe.utils"].add_months = lambda d, n: d
        fake["frappe.utils"].today = lambda: "2026-09-30"
        fake["frappe.utils"].getdate = lambda d: d
        sys.modules.update(fake)
        for n in names[2:]:
            sys.modules.pop(n, None)
        cls.E = importlib.import_module("pranera_planning.reorder")

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m
        WORLD.clear()

    def run_engine(self, include_bought=False):
        E = self.E
        WORLD["Item"] = lambda flt: [
            _dict(name=c, item_name=c, item_group=g, stock_uom="Kgs", commercial_name=cn,
                  lead_time_days={"YRFPP090/GREIGE": 10, "YRSPE011/GREIGE": 21}.get(c, 0))
            for c, (g, cn) in ITEMS.items() if c in flt["name"][1]]
        WORLD["Item Group"] = lambda flt: [_dict(name=g, lft=b[0], rgt=b[1]) for g, b in GROUPS.items() if g in flt["name"][1]]
        E.in_stores = lambda items: {"SKF11355/WHITE/68OW": 1200, "DKF11355/WHITE/68OW": 98, "GKF11355/GREIGE/28OW": 500,
                                     "YRFPP090/GREIGE": 975, "YRSPE011/GREIGE": 60}
        E.reserved = lambda items: {"SKF11355/WHITE/68OW": 300, "GKF11355/GREIGE/28OW": 400}
        E.wip = lambda items: {"SKF11355/WHITE/68OW": 250, "DKF11355/WHITE/68OW": 95}
        E.on_order = lambda items: {"YRSPE011/GREIGE": 100}
        E.bom_chain = lambda items: ({"SKF11355/WHITE/68OW": "DKF11355/WHITE/68OW", "DKF11355/WHITE/68OW": "GKF11355/GREIGE/28OW",
                                      "GKF11355/GREIGE/28OW": "YRFPP090/GREIGE"},
                                     {"SKF11355/WHITE/68OW", "DKF11355/WHITE/68OW", "GKF11355/GREIGE/28OW"})
        saved = {}
        E._save = lambda code, values: saved.__setitem__(code, values)
        E.open_po_lines = lambda items: list(getattr(self, "po_lines", []))

        def rule(safety, cover):
            return _dict(safety_days=safety, cover_days=cover, round_to=25, demand_basis="Sales + Consumption", bought_lead_days=0)
        cfg = {"history_days": 90, "near_margin": 10, "safety_days": 5, "cover_days": 30, "round_to": 1, "include_bought": include_bought,
               "stage_days": {"knitting": 5, "dyeing": 7, "finishing": 3},
               "rules": [(2, 3, rule(7, 30)), (4, 7, rule(3, 15)), (10, 11, rule(5, 20))]}
        sales = {"SKF11355/WHITE/68OW": 2700, "GKF11355/GREIGE/28OW": 270}
        used = {"DKF11355/WHITE/68OW": 2790, "GKF11355/GREIGE/28OW": 2700, "YRFPP090/GREIGE": 4050, "YRSPE011/GREIGE": 450}
        count = E.calculate(list(ITEMS), cfg, sales=sales, used=used)
        return count, saved

    def test_writes_the_canvas_numbers(self):
        count, saved = self.run_engine()
        self.assertEqual(count, 5)
        skf = saved["SKF11355/WHITE/68OW"]
        self.assertEqual((skf["lead_days"], skf["avg_daily"], skf["reorder_level"], skf["reorder_qty"], skf["max_level"]),
                         (15, 30, 660, 900, 1560))
        self.assertEqual((skf["free"], skf["position"], skf["status"], skf["suggest_qty"]), (900, 1150, "OK", 0))
        self.assertEqual((skf["family"], skf["obtained"], skf["stage"]), ("2TF ECO 220", "Made", "Finishing"))

        dkf = saved["DKF11355/WHITE/68OW"]       # dyeing 7 + knitting 5 below it, as for finished fabric
        self.assertEqual((dkf["lead_days"], dkf["reorder_level"], dkf["max_level"], dkf["position"], dkf["status"], dkf["suggest_qty"]),
                         (12, 465, 930, 193, "Order now", 750))

        gkf = saved["GKF11355/GREIGE/28OW"]
        self.assertEqual((gkf["lead_days"], gkf["avg_daily"], gkf["reorder_level"], gkf["max_level"], gkf["position"], gkf["suggest_qty"]),
                         (5, 33, 264, 759, 100, 675))

        ypp = saved["YRFPP090/GREIGE"]
        self.assertEqual((ypp["obtained"], ypp["lead_days"], ypp["reorder_level"], ypp["status"]), ("Bought", 10, 675, "OK"))
        self.assertEqual(ypp["family"], "YARN")                       # no Commercial Name: the group is the family
        self.assertEqual(saved["YRSPE011/GREIGE"]["family"], "YARN")  # "-" counts as none

    def test_purchase_orders_due_after_the_lead_time_arrive_later(self):
        # YRSPE011 (21 lead days from its Item) has 100 on order: due in 45 days, it doesn't count.
        self.po_lines = [("YRSPE011/GREIGE", 100, "2026-11-14", "PO-0123")]
        try:
            _count, saved = self.run_engine()
        finally:
            self.po_lines = []
        y = saved["YRSPE011/GREIGE"]
        self.assertEqual((y["on_order"], y["arriving_later"]), (0, 100))
        self.assertEqual(y["position"], 60)
        self.assertIn("PO-0123", y["arriving_later_note"])
        self.assertEqual(y["lead_source"], "Item's Lead Time Days")

    def test_bought_lead_days_only_when_asked(self):
        _c, saved = self.run_engine(include_bought=True)
        self.assertEqual(saved["SKF11355/WHITE/68OW"]["lead_days"], 25)
        self.assertEqual(saved["GKF11355/GREIGE/28OW"]["lead_days"], 15)


if __name__ == "__main__":
    unittest.main()
