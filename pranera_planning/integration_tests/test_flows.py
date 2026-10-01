"""Integration tests: run on a real Frappe/ERPNext site, creating real documents.

    bench --site <TEST SITE> set-config allow_tests true
    bench --site <TEST SITE> run-tests --module pranera_planning.integration_tests.test_flows

Use a COPY of your site (see the guide), never live: ERPNext stock postings can commit, so
not everything is rolled back afterwards. Every record made here is named PPT-…

They cover what the fast stand-in tests can't: Plan Project › Create (and the Overview reading
its saved plan), reservations moving
with a transfer between stores (and back on cancel), transfers out of stores, the Purchase
Material Request free-stock check, and the made-to-order delivery check.
"""
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, today

from pranera_planning import planner

YARN, GREIGE, BATCH = "PPT-YARN", "PPT-GREIGE", "PPT-Y1"


def _first(doctype, **filters):
    return frappe.db.get_value(doctype, {"is_group": 0, **filters} if frappe.db.has_column(doctype, "is_group") else filters, "name")


def _ensure(doctype, name, **values):
    if not frappe.db.exists(doctype, name):
        frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)
    return name


class TestFlows(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.company = (frappe.defaults.get_global_default("company")
                       or frappe.db.get_value("Company", {}, "name"))
        if not cls.company:
            raise frappe.ValidationError("No Company on this site — run the tests on a copy of a configured site.")
        abbr = frappe.db.get_value("Company", cls.company, "abbr")
        parent = frappe.db.get_value("Warehouse", {"company": cls.company, "is_group": 1}, "name")
        cls.stores = _ensure("Warehouse", f"PPT Stores - {abbr}", warehouse_name="PPT Stores", company=cls.company, parent_warehouse=parent)
        cls.stores2 = _ensure("Warehouse", f"PPT Stores 2 - {abbr}", warehouse_name="PPT Stores 2", company=cls.company, parent_warehouse=parent)
        cls.wip = _ensure("Warehouse", f"WIP PPT - {abbr}", warehouse_name="WIP PPT", company=cls.company, parent_warehouse=parent)
        frappe.db.set_single_value("Stock Settings", "use_serial_batch_fields", 1)

        _ensure("Item Group", "PPT Goods", item_group_name="PPT Goods", parent_item_group="All Item Groups")
        uom = "Kg" if frappe.db.exists("UOM", "Kg") else "Nos"
        for code in (YARN, GREIGE):
            _ensure("Item", code, item_code=code, item_name=code, item_group="PPT Goods", stock_uom=uom, is_stock_item=1,
                    has_batch_no=1, create_new_batch=1 if code == GREIGE else 0, batch_number_series="PPT-G-.####",
                    valuation_rate=10, is_purchase_item=1)
        _ensure("Batch", BATCH, batch_id=BATCH, item=YARN)
        for t in ("Purchase", "Production"):
            _ensure("Project Type", t, project_type=t)
        _ensure("Supplier", "PPT Supplier", supplier_name="PPT Supplier", supplier_group=_first("Supplier Group"))
        _ensure("Customer", "PPT Customer", customer_name="PPT Customer", customer_group=_first("Customer Group"),
                territory=_first("Territory"))

        def project(name, ptype):
            existing = frappe.db.get_value("Project", {"project_name": name}, "name")
            return existing or frappe.get_doc({"doctype": "Project", "project_name": name, "project_type": ptype,
                                               "status": "Open", "company": cls.company}).insert().name
        cls.pur, cls.prod, cls.prod2 = project("PPT-PUR", "Purchase"), project("PPT-PROD", "Production"), project("PPT-PROD2", "Production")

        if not frappe.db.exists("Purchase Receipt Item", {"batch_no": BATCH, "docstatus": 1}):
            pr = frappe.get_doc({"doctype": "Purchase Receipt", "supplier": "PPT Supplier", "company": cls.company,
                                 "posting_date": today(), "set_warehouse": cls.stores,
                                 "items": [{"item_code": YARN, "qty": 1000, "rate": 10, "warehouse": cls.stores,
                                            "batch_no": BATCH, "use_serial_batch_fields": 1, "project": cls.pur}]})
            pr.insert()
            pr.submit()
        if not frappe.db.exists("BOM", {"item": GREIGE, "is_default": 1, "docstatus": 1}):
            bom = frappe.get_doc({"doctype": "BOM", "item": GREIGE, "quantity": 100, "company": cls.company,
                                  "is_active": 1, "is_default": 1, "rm_cost_as_per": "Valuation Rate",
                                  "items": [{"item_code": YARN, "qty": 100, "rate": 10}]})
            bom.insert()
            bom.submit()
        s = frappe.get_single("Re-order Settings")
        s.default_warehouse = cls.stores
        s.save()

    @classmethod
    def tearDownClass(cls):
        frappe.db.rollback()
        super().tearDownClass()

    # ── helpers ──────────────────────────────────────────────────────────────
    def reservations(self, **filters):
        return frappe.get_all("Project Stock Reservation", filters={"batch_no": BATCH, **filters},
                              fields=["name", "warehouse", "reserved_qty", "status", "production_project", "moved_from"],
                              order_by="creation asc")

    def transfer(self, qty, target, project=None, submit=True):
        se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Transfer", "purpose": "Material Transfer",
                             "company": self.company, "project": project,
                             "items": [{"item_code": YARN, "qty": qty, "s_warehouse": self.stores, "t_warehouse": target,
                                        "batch_no": BATCH, "use_serial_batch_fields": 1}]})
        se.insert()
        if submit:
            se.submit()
        return se

    # ── the flows, in order ──────────────────────────────────────────────────
    def test_1_plan_made_to_order_creates_reservation_and_request(self):
        out = planner.create({"order_type": "Made to order", "project": self.prod, "needed_by": add_days(today(), 20),
                              "lines": [{"item": GREIGE, "qty": 300}]})
        self.assertEqual(len(out), 1)
        res = self.reservations(production_project=self.prod, status="Active")
        self.assertEqual([(r.warehouse, flt(r.reserved_qty)) for r in res], [(self.stores, 300)])       # yarn borrowed from PPT-PUR
        mr = frappe.get_doc("Material Request", out[0]["requests"][0]["name"])
        self.assertEqual((mr.docstatus, mr.material_request_type), (0, "Manufacture"))
        self.assertEqual([(i.item_code, flt(i.qty), i.project) for i in mr.items], [(GREIGE, 300, self.prod)])
        self.assertEqual(frappe.db.get_value("Project", self.prod, "planning_order_type"), "Made to order")

    def test_2_replanning_counts_the_drafts(self):
        prop = planner.propose({"order_type": "Made to order", "project": self.prod, "lines": [{"item": GREIGE, "qty": 300}]})[0]
        greige = next(r for r in prop["levels"] if r["item"] == GREIGE)
        self.assertEqual((greige["coming"], greige["request"]), (300, 0))
        self.assertEqual(prop["reservations"], [])

    def test_3_buying_what_is_free_is_refused(self):
        mr = frappe.get_doc({"doctype": "Material Request", "material_request_type": "Purchase", "company": self.company,
                             "transaction_date": today(), "schedule_date": add_days(today(), 10),
                             "items": [{"item_code": YARN, "qty": 900, "schedule_date": add_days(today(), 10),
                                        "warehouse": self.stores, "project": self.prod2}]})
        mr.insert()
        with self.assertRaises(frappe.ValidationError):            # 700 free: Administrator must give a reason
            mr.submit()

    def test_4_transfer_between_stores_moves_the_reservation_and_cancel_puts_it_back(self):
        se = self.transfer(900, self.stores2)                      # 700 free moves first, then 200 reserved
        active = {r.warehouse: flt(r.reserved_qty) for r in self.reservations(production_project=self.prod, status="Active")}
        self.assertEqual(active, {self.stores: 100, self.stores2: 200})
        se.cancel()
        active = {r.warehouse: flt(r.reserved_qty) for r in self.reservations(production_project=self.prod, status="Active")}
        self.assertEqual(active, {self.stores: 300})

    def test_5_transfer_out_of_stores_is_checked(self):
        with self.assertRaises(frappe.ValidationError):            # 800 > 700 free, for another project
            self.transfer(800, self.wip, project=self.prod2, submit=False)
        with self.assertRaises(frappe.ValidationError):            # no project on a transfer of reserved stock
            self.transfer(800, self.wip, project=None, submit=False)
        se = self.transfer(100, self.wip, project=self.prod2, submit=False)   # within the free stock
        se.delete()

    def test_6_delivery_holds_reserved_stock_for_its_project(self):
        def dn(qty):
            return frappe.get_doc({"doctype": "Delivery Note", "customer": "PPT Customer", "company": self.company,
                                   "posting_date": today(),
                                   "items": [{"item_code": YARN, "qty": qty, "rate": 20, "warehouse": self.stores,
                                              "batch_no": BATCH, "use_serial_batch_fields": 1}]})
        with self.assertRaises(frappe.ValidationError):            # 800 > 700 free, no Sales Order for PPT-PROD
            dn(800).insert()
        d = dn(700).insert()
        d.delete()

    def test_7_plan_made_to_stock_creates_the_family_project(self):
        out = planner.create({"order_type": "Made to stock", "needed_by": add_days(today(), 20),
                              "lines": [{"item": YARN, "qty": 2000, "mode": "top_up"}]})
        p = frappe.get_doc("Project", out[0]["project"])
        self.assertEqual((p.project_type, p.planning_order_type), ("Purchase", "Made to stock"))
        self.assertIn("PPT GOODS", p.project_name.upper())
        mr = frappe.get_doc("Material Request", out[0]["requests"][0]["name"])
        self.assertEqual((mr.material_request_type, [flt(i.qty) for i in mr.items]), ("Purchase", [2000]))

    def test_8_overview_reads_the_saved_plans(self):
        from pranera_planning.api.project_planning import get_overview
        from pranera_planning.api.plan import plan_defaults
        o = get_overview(self.prod)                                # test 1 planned 300 greige for it
        self.assertEqual(o["project"]["order_type"], "Made to order")
        self.assertEqual([(r["item"], flt(r["ordered"])) for r in o["rows"]], [(GREIGE, 300)])
        self.assertGreaterEqual(o["totals"]["drafts"], 1)
        self.assertEqual([(l["item"], flt(l["qty"])) for l in plan_defaults(self.prod)["lines"]], [(GREIGE, 300)])
        stock = frappe.get_all("Project", filters={"planning_order_type": "Made to stock", "project_name": ["like", "%PPT GOODS%"]},
                               pluck="name")
        self.assertTrue(stock)                                     # test 7's family project
        o = get_overview(stock[0])
        self.assertEqual([(r["item"], flt(r["target"]), r["mode"]) for r in o["rows"]], [(YARN, 2000, "top_up")])
