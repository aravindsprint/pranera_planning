"""planner.propose end to end against the frappe stand-in: scenario 4 (Production, made to
order) and scenario 3 (Production, made to stock) from the design canvas."""
import importlib
import sys
import types
import unittest

from pranera_planning.tests.test_stock_entry_checks import _dict, _fake_frappe

SKF, DKF, GKF, YPP, YSP = "SKF11355/WHITE/68OW", "DKF11355/WHITE/68OW", "GKF11355/GREIGE/28OW", "YRFPP090/GREIGE", "YRSPE011/GREIGE"
BOMS = {SKF: "BOM-SKF", DKF: "BOM-DKF", GKF: "BOM-GKF-009"}
ROWS = {SKF: [(DKF, 1.03)], DKF: [(GKF, 1.05)], GKF: [(YPP, 0.90), (YSP, 0.10)]}


def lot(batch, qty, project, produced=False, roll=""):
    return {"batch_no": batch, "warehouse": "Stores - PSS", "roll_no": roll, "qty": qty, "project": project, "produced": produced}


class TestPropose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "pranera_planning.reservation", "pranera_planning.reorder", "pranera_planning.planner"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        fake = _fake_frappe()
        u = fake["frappe.utils"]
        u.add_days, u.add_months, u.today = (lambda d, n: d), (lambda d, n: d), (lambda: "2026-10-01")
        from datetime import date
        u.getdate = lambda d=None: date.fromisoformat(str(d)[:10]) if d else date(2026, 10, 1)
        fake["frappe"].defaults = types.SimpleNamespace(get_user_default=lambda k: "Pranera")
        sys.modules.update(fake)
        for n in names[2:]:
            sys.modules.pop(n, None)
        cls.P = importlib.import_module("pranera_planning.planner")
        cls.f = fake["frappe"]
        cls.real_bom_tree = staticmethod(cls.P.bom_tree)

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m

    def setUp(self):
        P, f = self.P, self.f
        stage_rows = [_dict(stage="Finishing", route="Job work", job_work_services="STENTER, DRYER"),
                      _dict(stage="Dyeing", route="In-house", job_work_services=""),
                      _dict(stage="Knitting", route="In-house", job_work_services="KNITTING")]
        P.load_settings = lambda: {"doc": _dict(stage_leads=stage_rows, stock_project_period="Quarter", seasons=[],
                                                stock_project_pattern="{YY}STK-{FAMILY}-{PERIOD}"),
                                   "rules": [], "round_to": 25}
        P.item_info = lambda codes: {c: _dict(name=c, item_name=c, item_group="G", stock_uom="Kgs",
                                              commercial_name="" if c.startswith("YR") else "2TF ECO 220") for c in codes}
        def bom_tree(codes, depth=10, chosen=None):
            rows = dict(ROWS)
            boms = {c: BOMS[c] for c in BOMS}
            if (chosen or {}).get(GKF) == "BOM-GKF-LOSS":          # an alternative greige BOM: 100% YRFPP090
                rows[GKF] = [(YPP, 1.0)]
                boms[GKF] = "BOM-GKF-LOSS"
            return boms, rows
        P.bom_tree = bom_tree
        P.last_service = lambda items: {SKF: "DRYER"}                      # this fabric last went to the dryer
        f.get_all = lambda doctype, filters=None, fields=None, as_list=False, **kw: (
            [("26PTIN1710", "Made to order"), ("25PUR001", ""), ("26STK-OLD", "Made to stock")] if doctype == "Project" else [])

    def run_mto(self):
        P = self.P
        P.free_lots = lambda codes: {
            DKF: [lot("DKF-B1", 98, "26PTIN1710", produced=True)],
            GKF: [lot("GKF-B1", 25, "26PTIN1710", True, f"R{i}") for i in range(1, 17)] + [lot("GKF-X", 500, "26PTIN1645", True, "R9")],
            YPP: [lot("25PUR001/REL/5678", 975, "25PUR001")],
            YSP: [lot("YSP-B", 60, "25PUR001")]}
        P.held_for = lambda project, codes: {}
        P.coming = lambda project, codes: ({YSP: 100}, {YSP: ["Purchase Orders: 1"]})
        self.f.db.get_value = lambda dt, name, fields=None, **kw: _dict(name="26PTIN1710", project_name="26PTIN1710",
                                                                         project_type="Production", status="Open", customer=None)
        return P.propose({"order_type": "Made to order", "project": "26PTIN1710", "sales_order": "SO-1", "needed_by": "2026-11-15",
                          "lines": [{"item": SKF, "qty": 2000}, {"item": GKF, "qty": 300}]})[0]

    def test_what_counts_as_own_stock(self):
        own, kinds = self.P.counts_as_own, {"25PUR001": "Made to stock", "PTIN1710": "Made to order"}
        mts, mto = "Made to stock", "Made to order"
        self.assertTrue(own(None, "26STK-YARN-Q4-01", mts, kinds))           # old stock, no project
        self.assertTrue(own("", "26STK-YARN-Q4-01", mts, kinds))
        self.assertTrue(own("25PUR001", "26STK-YARN-Q4-01", mts, kinds))     # another stock project
        self.assertTrue(own("26STK-YARN-Q4-01", "26STK-YARN-Q4-01", mts, kinds))
        self.assertFalse(own("PTIN1710", "26STK-YARN-Q4-01", mts, kinds))    # another order's stock
        self.assertFalse(own(None, "PTIN1710", mto, kinds))                  # an order counts only its own
        self.assertTrue(own("PTIN1710", "PTIN1710", mto, kinds))

    def test_mto_numbers(self):
        p = self.run_mto()
        lv = {r["item"]: r for r in p["levels"]}
        self.assertEqual([lv[c]["request"] for c in (SKF, DKF, GKF, YPP, YSP)], [2000, 1962, 1961, 800, 50])
        self.assertAlmostEqual(lv[GKF]["need"], 2360.1)

    def test_mto_reserves_own_stock_roll_by_roll_and_borrows_purchased_only(self):
        p = self.run_mto()
        own = [r for r in p["reservations"] if r["kind"] == "own"]
        self.assertEqual(sum(r["qty"] for r in own if r["item_code"] == GKF), 400)
        self.assertEqual(len([r for r in own if r["item_code"] == GKF]), 16)                 # 16 rolls of 25
        self.assertEqual(sum(r["qty"] for r in own if r["item_code"] == DKF), 98)
        borrowed = {r["item_code"]: (r["project"], r["qty"]) for r in p["reservations"] if r["kind"] == "borrow"}
        self.assertEqual(borrowed, {YPP: ("25PUR001", 975), YSP: ("25PUR001", 60)})
        self.assertNotIn("GKF-X", [r["batch_no"] for r in p["reservations"]])              # produced for 26PTIN1645: theirs

    def test_mto_requests(self):
        p = self.run_mto()
        req = p["requests"]
        self.assertEqual([(r["item_code"], r["qty"]) for r in req["Job work"]], [("DRYER", 2000)])     # one service: this item's last
        self.assertEqual(req["Job work"][0]["bom_no"], "BOM-SKF")
        self.assertEqual(sorted((r["item_code"], r["qty"]) for r in req["Manufacture"]), [(DKF, 1962), (GKF, 1961)])
        self.assertEqual(sorted((r["item_code"], r["qty"]) for r in req["Purchase"]), [(YPP, 800), (YSP, 50)])
        self.assertEqual(p["warnings"], [])

    def test_process_loss_raises_the_input_per_unit(self):
        f, saved_all, saved_sql = self.f, self.f.get_all, self.f.db.sql
        f.get_all = lambda doctype, filters=None, fields=None, **kw: (
            [_dict(name="BOM-DKF", item=DKF, quantity=100, process_loss_percentage=3)]
            if doctype == "BOM" and (filters or {}).get("item") else [])
        f.db.sql = lambda q, v=None, **kw: [("BOM-DKF", GKF, 100.0, 1)]
        try:
            boms, rows = self.real_bom_tree([DKF], depth=1)
        finally:
            f.get_all, f.db.sql = saved_all, saved_sql
        self.assertEqual(boms, {DKF: "BOM-DKF"})
        self.assertAlmostEqual(rows[DKF][0][1], 100 / 97, places=6)          # 1,000 good needs 1,030.9 in

    def test_a_chosen_bom_changes_the_plan(self):
        P = self.P
        P.free_lots = lambda codes: {}
        P.held_for = lambda project, codes: {}
        P.coming = lambda project, codes: ({}, {})
        self.f.db.get_value = lambda dt, name, fields=None, **kw: _dict(name="26PTIN1710", project_name="26PTIN1710",
                                                                         project_type="Production", status="Open", customer=None)
        p = P.propose({"order_type": "Made to order", "project": "26PTIN1710", "lines": [{"item": GKF, "qty": 100}],
                       "boms": {GKF: "BOM-GKF-LOSS"}})[0]
        lv = {r["item"]: r for r in p["levels"]}
        self.assertEqual(lv[GKF]["bom"], "BOM-GKF-LOSS")
        self.assertEqual(lv[YPP]["need"], 100)
        self.assertNotIn(YSP, lv)

    def test_mts_goes_to_the_family_project_and_uses_any_stock_projects_stock(self):
        P = self.P
        P.free_lots = lambda codes: {SKF: [lot("SKF-OLD", 900, "26STK-OLD", produced=True)],
                                     YPP: [lot("25PUR001/REL/5678", 975, "25PUR001")]}
        P.held_for = lambda project, codes: {}
        P.coming = lambda project, codes: ({}, {})
        self.f.db.get_value = lambda *a, **k: None                       # the Q4 project doesn't exist yet
        props = P.propose({"order_type": "Made to stock", "needed_by": "2026-10-20",
                           "lines": [{"item": SKF, "qty": 5000, "mode": "top_up"}]})
        self.assertEqual(len(props), 1)
        p = props[0]
        self.assertEqual((p["project"]["project_name"], p["project"]["project_type"], p["project"]["exists"]),
                         ("26STK-2TF ECO 220-Q4", "Production", False))
        lv = {r["item"]: r for r in p["levels"]}
        self.assertEqual((lv[SKF]["own"], lv[SKF]["request"]), (900, 4100))           # last period's stock counts as own
        self.assertEqual([r for r in p["reservations"] if r["kind"] == "own"], [])  # made to stock: own stock stays free


    def _mts(self, pattern, existing_names, payload_extra=None):
        P = self.P
        settings = P.load_settings()
        settings["doc"]["stock_project_pattern"] = pattern
        P.load_settings = lambda: settings
        P.free_lots = lambda codes: {}
        P.held_for = lambda project, codes: {}
        P.coming = lambda project, codes: ({}, {})
        kinds = self.f.get_all

        def get_all(doctype, filters=None, fields=None, as_list=False, pluck=None, **kw):
            if doctype == "Project" and pluck == "project_name":
                return list(existing_names)
            return kinds(doctype, filters=filters, fields=fields, as_list=as_list, **kw)
        self.f.get_all = get_all
        self.f.db.get_value = lambda dt, name, fields=None, **kw: (
            _dict(name=name, project_name=name, project_type="Production") if isinstance(name, str) else None)
        return P.propose({"order_type": "Made to stock", "needed_by": "2026-10-20",
                          "lines": [{"item": SKF, "qty": 5000, "mode": "top_up"}, {"item": DKF, "qty": 100, "mode": "top_up"}],
                          **(payload_extra or {})})

    def test_second_plan_in_the_quarter_gets_the_next_number(self):
        props = self._mts("{YY}STK-{FAMILY}-{PERIOD}-{SEQ}", ["26STK-2TF ECO 220-Q4-01"])
        self.assertEqual(len(props), 1)                                   # both lines are 2TF ECO 220: one project
        self.assertEqual((props[0]["project"]["project_name"], props[0]["project"]["exists"]), ("26STK-2TF ECO 220-Q4-02", False))

    def test_replanning_a_stock_project_keeps_it(self):
        props = self._mts("{YY}STK-{FAMILY}-{PERIOD}-{SEQ}", ["26STK-2TF ECO 220-Q4-01"], {"project": "26STK-2TF ECO 220-Q4-01"})
        self.assertEqual((props[0]["project"]["project"], props[0]["project"]["exists"]), ("26STK-2TF ECO 220-Q4-01", True))


if __name__ == "__main__":
    unittest.main()
