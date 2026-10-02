"""sales_order: made-to-order Sales Orders get their project, against the frappe stand-in."""
import importlib
import sys
import unittest

from pranera_planning.tests.test_stock_entry_checks import _dict, _fake_frappe


class FakeOrder(_dict):
    def db_set(self, field, value, **kw):
        self[field] = value
        self.setdefault("db_sets", []).append((field, value))


class TestMadeToOrderProject(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "pranera_planning.sales_order"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        fake = _fake_frappe()
        sys.modules.update(fake)
        sys.modules.pop("pranera_planning.sales_order", None)
        cls.so = importlib.import_module("pranera_planning.sales_order")
        cls.f = fake["frappe"]

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m

    def setUp(self):
        f = self.f
        self.projects = {}
        self.created, self.comments = [], []
        test = self

        class FakeProject(_dict):
            def insert(self):
                self["name"] = self["project_name"]
                test.projects[self.name] = _dict(self)
                test.created.append(self.name)
                return self

            def add_comment(self, kind, text):
                test.comments.append((self.get("name"), text))

        def get_doc(arg, name=None):
            if isinstance(arg, dict):
                return FakeProject({**arg, "flags": _dict()})     # real documents always carry flags
            p = FakeProject(test.projects[name])
            return p

        def get_value(doctype, filters, fields=None, as_dict=False, **kw):
            if isinstance(filters, dict):                    # lookup by sales_order
                hits = [n for n, p in self.projects.items() if p.get("sales_order") == filters.get("sales_order")]
                return hits[0] if hits else None
            p = self.projects.get(filters)
            if p is None:
                return None
            if isinstance(fields, (list, tuple)):
                return _dict({k: p.get(k) for k in fields})
            return p.get(fields)

        def set_value(doctype, name, field, value=None, **kw):
            updates = field if isinstance(field, dict) else {field: value}
            self.projects[name].update(updates)

        f.get_doc = get_doc
        f.db.get_value = get_value
        f.db.set_value = set_value
        f.db.has_column = lambda dt, field: True
        f.db.exists = lambda dt, filters: self.used.get(dt, False)
        f.db.sql = lambda q, *a, **k: [(1,)] if ("Material Request" in q and self.used.get("Material Request")) else []
        self.used = {}
        self.messages = []
        f.msgprint = lambda *a, **k: self.messages.append(a[0] if a else k.get("msg"))

    def order(self, **kw):
        base = dict(name="SAL-ORD-2026-00012", made_to_order=1, project=None, amended_from=None, company="Pranera",
                    customer="BUYER", delivery_date="2026-11-15")
        base.update(kw)
        return FakeOrder(base)

    def test_orders_without_the_tick_are_untouched(self):
        d = self.order(made_to_order=0)
        self.so.on_submit(d)
        self.so.on_cancel(d)
        self.assertEqual((self.created, d.get("db_sets")), ([], None))

    def test_creates_a_made_to_order_project_and_links_both_ways(self):
        d = self.order()
        self.so.on_submit(d)
        p = self.projects["SAL-ORD-2026-00012"]
        self.assertEqual((p.project_type, p.planning_order_type, p.customer, p.sales_order, p.expected_end_date, p.status),
                         ("Production", "Made to order", "BUYER", "SAL-ORD-2026-00012", "2026-11-15", "Open"))
        self.assertEqual(d.project, "SAL-ORD-2026-00012")
        self.assertIn("project-planning?project=SAL-ORD-2026-00012&tab=plan", self.messages[0])

    def test_a_chosen_project_is_linked_not_created(self):
        self.projects["26PTIN1710"] = _dict(name="26PTIN1710", project_name="26PTIN1710", status="Open",
                                            project_type="Production", planning_order_type=None, sales_order=None, customer=None)
        d = self.order(project="26PTIN1710")
        self.so.validate(d)
        self.so.on_submit(d)
        p = self.projects["26PTIN1710"]
        self.assertEqual(self.created, [])
        self.assertEqual((p.sales_order, p.customer, p.planning_order_type), ("SAL-ORD-2026-00012", "BUYER", "Made to order"))

    def test_a_project_of_another_order_is_refused(self):
        self.projects["26PTIN1710"] = _dict(name="26PTIN1710", sales_order="SAL-ORD-2026-00099")
        with self.assertRaises(self.f.ValidationError):
            self.so.validate(self.order(project="26PTIN1710"))

    def test_an_amended_order_takes_over_and_reopens_the_project(self):
        self.projects["SAL-ORD-2026-00012"] = _dict(name="SAL-ORD-2026-00012", project_name="SAL-ORD-2026-00012", status="Cancelled",
                                                    project_type="Production", planning_order_type="Made to order",
                                                    sales_order="SAL-ORD-2026-00012", customer="BUYER")
        d = self.order(name="SAL-ORD-2026-00012-1", amended_from="SAL-ORD-2026-00012")
        self.so.on_submit(d)
        p = self.projects["SAL-ORD-2026-00012"]
        self.assertEqual(self.created, [])
        self.assertEqual((p.sales_order, p.status, d.project), ("SAL-ORD-2026-00012-1", "Open", "SAL-ORD-2026-00012"))

    def test_cancelling_closes_an_unused_project(self):
        d = self.order()
        self.so.on_submit(d)
        self.so.on_cancel(d)
        self.assertEqual(self.projects["SAL-ORD-2026-00012"].status, "Cancelled")

    def test_cancelling_an_amended_order_closes_the_original_project_too(self):
        self.projects["SAL-ORD-2026-00012"] = _dict(name="SAL-ORD-2026-00012", project_name="SAL-ORD-2026-00012", status="Open",
                                                    sales_order="SAL-ORD-2026-00012-1")
        self.so.on_cancel(self.order(name="SAL-ORD-2026-00012-1", project="SAL-ORD-2026-00012"))
        self.assertEqual(self.projects["SAL-ORD-2026-00012"].status, "Cancelled")

    def test_cancelling_keeps_a_project_in_use(self):
        d = self.order()
        self.so.on_submit(d)
        self.used = {"Project Stock Reservation": True, "Material Request": True}
        self.so.on_cancel(d)
        self.assertEqual(self.projects["SAL-ORD-2026-00012"].status, "Open")
        self.assertIn("reservations, Material Requests", self.comments[-1][1])


if __name__ == "__main__":
    unittest.main()
