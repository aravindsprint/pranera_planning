"""api.project_planning.get_overview and api.plan.plan_defaults against the frappe stand-in."""
import importlib
import json
import sys
import types
import unittest

from pranera_planning.tests.test_stock_entry_checks import _dict, _fake_frappe

SKF, GKF = "SKF11355/WHITE/68OW", "GKF11355/GREIGE/28OW"


class TestProjectPlanning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "pranera_planning.reservation", "pranera_planning.reorder",
                 "pranera_planning.planner", "pranera_planning.api.project_planning", "pranera_planning.api.plan",
                 "pranera_planning.api.reservation"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        fake = _fake_frappe()
        u = fake["frappe.utils"]
        u.add_days, u.add_months, u.today = (lambda d, n: d), (lambda d, n: d), (lambda: "2026-10-01")
        u.getdate = lambda d=None: d
        fake["frappe"].defaults = types.SimpleNamespace(get_user_default=lambda k: "Pranera")
        sys.modules.update(fake)
        for n in names[2:]:
            sys.modules.pop(n, None)
        cls.planner = importlib.import_module("pranera_planning.planner")
        cls.api = importlib.import_module("pranera_planning.api.project_planning")
        cls.plan_api = importlib.import_module("pranera_planning.api.plan")
        cls.res_api = importlib.import_module("pranera_planning.api.reservation")
        cls.f = fake["frappe"]

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m

    def setUp(self):
        P, f, api = self.planner, self.f, self.api
        P._has = lambda dt, field: True
        P.item_info = lambda codes: {c: _dict(name=c, item_name=c, item_group="G", stock_uom="Kgs") for c in codes}
        self.res_api.get_purchase_project_stock = lambda project: {"stages": [
            {"stage": "Knitting", "orders": 1, "batches": 1, "input_qty": 420, "in_process_qty": 0, "produced_qty": 400,
             "loss_qty": 20, "in_stores_qty": 400}]}
        api._open_items = lambda project: set()
        api._remaining = lambda rows: {r.name: r.rem for r in rows}
        f.db.sql = lambda *a, **k: []
        f.db.sql_list = lambda *a, **k: []

    def project(self, **kw):
        base = dict(name="26PTIN1710", project_name="26PTIN1710", project_type="Production", status="Open", customer=None,
                    sales_order=None, planning_order_type="Made to order", stock_family=None, stock_period=None, saved_plan=None)
        base.update(kw)
        self.api.project_info = lambda project: _dict(base)

    def test_made_to_order_ready_in_production_not_planned(self):
        self.project(sales_order="SO-1")
        self.api.sales_order_lines = lambda so: [
            {"item": SKF, "item_name": SKF, "ordered": 2000, "delivered": 0, "uom": "Kgs", "label": "line 1"},
            {"item": GKF, "item_name": GKF, "ordered": 300, "delivered": 0, "uom": "Kgs", "label": "line 2"}]
        P = self.planner
        P.free_lots = lambda items: {GKF: [{"project": "26PTIN1710", "qty": 250}, {"project": "26PTIN1645", "qty": 500}]}
        P.held_for = lambda project, items: {GKF: 150}
        P.coming = lambda project, items: ({SKF: 1500}, {})
        self.f.get_all = lambda doctype, **kw: [] if doctype != "Project Stock Reservation" else [_dict(name="R1", batch_no="B", rem=1533)]
        self.f.db.get_value = lambda *a, **k: _dict(customer="BUYER", delivery_date="2026-11-15")
        o = self.api.get_overview("26PTIN1710")
        rows = {r["item"]: r for r in o["rows"]}
        self.assertEqual((rows[SKF]["ready"], rows[SKF]["in_production"], rows[SKF]["not_planned"]), (0, 1500, 500))
        self.assertEqual((rows[GKF]["ready"], rows[GKF]["in_production"], rows[GKF]["not_planned"]), (300, 0, 0))   # 250 own + 150 held, capped at 300
        self.assertEqual(o["totals"]["held"], 1533)
        self.assertEqual(o["totals"]["not_planned"], 500)
        self.assertEqual((o["project"]["customer"], o["project"]["delivery_date"]), ("BUYER", "2026-11-15"))
        self.assertEqual(o["stages"][0]["planned_qty"], 0)

    def test_made_to_stock_programme(self):
        self.project(name="26STK-X", planning_order_type="Made to stock", stock_family="2TF ECO 220", stock_period="Q4",
                     saved_plan=json.dumps({"lines": [{"item": SKF, "qty": 5000, "mode": "top_up"}], "needed_by": "2026-12-20"}))
        P = self.planner
        P.free_lots = lambda items: {SKF: [{"project": "26STK-X", "qty": 900}]}
        P.held_for = lambda project, items: {}
        P.coming = lambda project, items: ({SKF: 4100}, {})
        given = [_dict(name="G1", item_code=SKF, batch_no="B", production_project="26PTIN1722", rem=300)]
        self.f.get_all = lambda doctype, filters=None, **kw: (given if (filters or {}).get("purchase_project") else []) \
            if doctype == "Project Stock Reservation" else []
        o = self.api.get_overview("26STK-X")
        r = o["rows"][0]
        self.assertEqual((r["target"], r["held"], r["reserved_by_orders"], r["free_now"], r["in_production"], r["free_after_plan"]),
                         (5000, 1200, 300, 900, 4100, 5000))
        self.assertEqual(o["project"]["delivery_date"], "2026-12-20")

    def test_plan_tab_starts_from_the_sales_order(self):
        self.project(sales_order="SO-1")
        self.plan_api.sales_order_lines = lambda so: {"sales_order": so, "customer": "BUYER", "delivery_date": "2026-11-15",
                                                      "submitted": True, "project": None,
                                                      "lines": [{"item": SKF, "qty": 2000, "label": "Sales Order line 1"}]}
        d = self.plan_api.plan_defaults("26PTIN1710")
        self.assertEqual((d["order_type"], d["sales_order"], d["needed_by"]), ("Made to order", "SO-1", "2026-11-15"))
        self.assertEqual(d["lines"], [{"item": SKF, "qty": 2000, "label": "Sales Order line 1", "mode": "need"}])

    def test_plan_tab_starts_from_saved_targets_for_made_to_stock(self):
        self.project(planning_order_type="Made to stock",
                     saved_plan=json.dumps({"lines": [{"item": SKF, "qty": 5000, "mode": "top_up"}], "needed_by": "2026-12-20"}))
        d = self.plan_api.plan_defaults("26STK-X")
        self.assertEqual(d["order_type"], "Made to stock")
        self.assertEqual([(l["item"], l["qty"], l["mode"]) for l in d["lines"]], [(SKF, 5000, "top_up")])

    def test_a_project_without_an_order_type_is_planned_as_made_to_order(self):
        self.project(planning_order_type=None)
        self.assertEqual(self.plan_api.plan_defaults("25PROD002")["order_type"], "Made to order")


if __name__ == "__main__":
    unittest.main()
