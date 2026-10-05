"""lead_time.resolve and the Purchase Order lead time check, against the frappe stand-in.

The story: 30S COTTON is bought from China (ZHEJIANG, 45 days) or India (SRI MILLS, 15);
MELANGE is bought from SRI MILLS but takes 45 days (its Supplier Items row)."""
import importlib
import sys
import types
import unittest

from pranera_planning.tests.test_stock_entry_checks import WORLD, ValidationError, _dict, _fake_frappe

INFO = {"30S COTTON": _dict(item_group="YARN", lead_time_days=20),
        "MELANGE": _dict(item_group="YARN", lead_time_days=0),
        "NEW YARN": _dict(item_group="YARN", lead_time_days=0)}


def group_days(group):
    return 12 if group == "YARN" else 0


class _World:
    @staticmethod
    def setup(fake, latest_po=None):
        WORLD["Item Default"] = lambda flt: [_dict(parent="30S COTTON", default_supplier="SRI MILLS", company="PSS"),
                                             _dict(parent="MELANGE", default_supplier="SRI MILLS", company="PSS")]
        WORLD["Supplier"] = lambda flt: [_dict(name=n, usual_lead_days=d) for n, d in
                                         (("ZHEJIANG", 45), ("SRI MILLS", 15)) if n in flt["name"][1]]
        WORLD["Item Supplier"] = lambda flt: [_dict(parent="MELANGE", supplier="SRI MILLS", lead_days=45)]
        fake["frappe"].db.sql = lambda q, v=None, **k: [(i, s) for i, s in (latest_po or {}).items() if i in v["items"]] \
            if "ORDER BY po.transaction_date DESC" in q else []


class TestResolve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "pranera_planning.lead_time"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        cls.fake = _fake_frappe()
        cls.fake["frappe.utils"].add_months = lambda d, n: d
        cls.fake["frappe.utils"].today = lambda: "2026-10-05"
        sys.modules.update(cls.fake)
        sys.modules.pop("pranera_planning.lead_time", None)
        cls.T = importlib.import_module("pranera_planning.lead_time")

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            sys.modules.pop(n, None) if m is None else sys.modules.__setitem__(n, m)
        WORLD.clear()

    def resolve(self, order=None, supplier=None, fallback="Latest Purchase Order", latest_po=None):
        _World.setup(self.fake, latest_po)
        cfg = {**self.T.default_config(), "fallback": fallback}
        if order is not None:
            cfg["order"] = order
        return self.T.resolve(list(INFO), INFO, group_days, cfg, supplier=supplier)

    def test_default_supplier_and_item_row(self):
        r = self.resolve()
        self.assertEqual((r["30S COTTON"]["days"], r["30S COTTON"]["source"], r["30S COTTON"]["supplier"]),
                         (15.0, "supplier", "SRI MILLS"))
        self.assertEqual((r["MELANGE"]["days"], r["MELANGE"]["source"]), (45.0, "supplier_item"))

    def test_purchase_order_supplier_overrides_the_default(self):
        r = self.resolve(supplier="ZHEJIANG")
        self.assertEqual((r["30S COTTON"]["days"], r["30S COTTON"]["supplier_from"]), (45.0, "this Purchase Order"))
        self.assertEqual(r["MELANGE"]["days"], 45.0)           # no row for ZHEJIANG → ZHEJIANG's usual 45

    def test_no_default_supplier_uses_the_latest_purchase_order(self):
        r = self.resolve(latest_po={"NEW YARN": "ZHEJIANG"})
        self.assertEqual((r["NEW YARN"]["days"], r["NEW YARN"]["supplier"], r["NEW YARN"]["supplier_from"]),
                         (45.0, "ZHEJIANG", "latest Purchase Order"))

    def test_no_supplier_setting_falls_to_item_then_group(self):
        r = self.resolve(fallback="No supplier", latest_po={"NEW YARN": "ZHEJIANG"})
        self.assertEqual((r["NEW YARN"]["days"], r["NEW YARN"]["source"], r["NEW YARN"]["supplier"]), (12.0, "group", None))

    def test_ranking_from_the_settings(self):
        r = self.resolve(order=["item", "group"])
        self.assertEqual((r["30S COTTON"]["days"], r["30S COTTON"]["source"]), (20.0, "item"))
        self.assertEqual((r["MELANGE"]["days"], r["MELANGE"]["source"]), (12.0, "group"))


class FakePO(_dict):
    def add_comment(self, kind, text):
        self.setdefault("comments", []).append(text)


class TestPurchaseOrderCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "pranera_planning.purchase_order", "pranera_planning.reorder",
                 "pranera_planning.reservation", "pranera_planning.lead_time"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        cls.fake = _fake_frappe()
        cls.fake["frappe.utils"].formatdate = lambda d: str(d)
        sys.modules.update(cls.fake)
        cls.cfg = {"rules": [], "lead": {"order": ["supplier_item", "supplier", "item", "group"], "fallback": "Latest Purchase Order",
                                         "months": 6, "check": "Block", "grace": 0.0}}
        reorder = types.ModuleType("pranera_planning.reorder")
        reorder.load_settings = lambda: cls.cfg
        reservation = types.ModuleType("pranera_planning.reservation")
        reservation.mr_check_settings = lambda: {"roles": {"Purchase Manager"}}
        lead_time = types.ModuleType("pranera_planning.lead_time")
        lead_time.group_days_for = lambda groups, rules: (lambda g: 0)
        leads = {"ZHEJIANG": {"30S COTTON": (45, "supplier"), "DYE": (20, "item")}}
        lead_time.resolve = lambda codes, info, gd, cfg, supplier=None: {
            c: {"days": leads.get(supplier, {}).get(c, (0, None))[0], "source": leads.get(supplier, {}).get(c, (0, None))[1]}
            for c in codes}
        sys.modules.update({"pranera_planning.reorder": reorder, "pranera_planning.reservation": reservation,
                            "pranera_planning.lead_time": lead_time})
        sys.modules.pop("pranera_planning.purchase_order", None)
        cls.P = importlib.import_module("pranera_planning.purchase_order")
        WORLD["Item"] = lambda flt: [_dict(name=c, item_group="YARN", lead_time_days=0) for c in flt["name"][1]]

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            sys.modules.pop(n, None) if m is None else sys.modules.__setitem__(n, m)
        WORLD.clear()

    def setUp(self):
        self.fake["frappe"].messages.clear()
        self.fake["frappe"].logged.clear()
        self.fake["frappe"].roles = ["Purchase User"]
        self.cfg["lead"]["check"] = "Block"

    def po(self, required_by="2026-11-05", item="30S COTTON", **kw):
        return FakePO({"supplier": "ZHEJIANG", "transaction_date": "2026-10-06", "is_subcontracted": 0,
                       "items": [_dict(idx=1, name="r1", item_code=item, schedule_date=required_by)], **kw})

    def test_draft_save_only_warns(self):
        self.P.check_lead_time(self.po(), "validate")
        self.assertEqual(len(self.fake["frappe"].messages), 1)
        self.assertIn("2026-11-20", self.fake["frappe"].messages[0][1])

    def test_submit_is_blocked(self):
        with self.assertRaises(ValidationError) as e:
            self.P.check_lead_time(self.po(), "before_submit")
        self.assertIn("earliest is <b>2026-11-20</b>", str(e.exception))

    def test_in_time_passes(self):
        self.P.check_lead_time(self.po("2026-11-20"), "before_submit")
        self.assertEqual(self.fake["frappe"].messages, [])

    def test_override_role_without_reason_is_told_how(self):
        self.fake["frappe"].roles = ["Purchase Manager"]
        with self.assertRaises(ValidationError) as e:
            self.P.check_lead_time(self.po(), "before_submit")
        self.assertIn("Lead time override reason", str(e.exception))

    def test_override_with_reason_passes_and_is_recorded(self):
        self.fake["frappe"].roles = ["Purchase Manager"]
        doc = self.po(lead_time_override_reason="Air freight confirmed by supplier")
        self.P.check_lead_time(doc, "before_submit")
        self.assertIn("Air freight", doc.comments[0])

    def test_reason_without_the_role_still_blocks(self):
        with self.assertRaises(ValidationError):
            self.P.check_lead_time(self.po(lead_time_override_reason="please"), "before_submit")

    def test_item_lead_days_only_warn_on_submit(self):
        self.P.check_lead_time(self.po("2026-10-10", item="DYE"), "before_submit")
        self.assertEqual(len(self.fake["frappe"].messages), 1)

    def test_warn_mode_never_blocks(self):
        self.cfg["lead"]["check"] = "Warn"
        self.P.check_lead_time(self.po(), "before_submit")
        self.assertEqual(len(self.fake["frappe"].messages), 1)

    def test_off_and_subcontracted_are_skipped(self):
        self.cfg["lead"]["check"] = "Off"
        self.P.check_lead_time(self.po(), "before_submit")
        self.cfg["lead"]["check"] = "Block"
        self.P.check_lead_time(self.po(is_subcontracted=1), "before_submit")
        self.assertEqual(self.fake["frappe"].messages, [])

    def test_update_items_checks_only_changed_dates(self):
        doc = self.po()
        doc.get_doc_before_save = lambda: _dict(items=[_dict(name="r1", schedule_date="2026-11-05")])
        self.P.check_lead_time(doc, "before_update_after_submit")          # unchanged: no check
        doc["items"][0]["schedule_date"] = "2026-11-01"
        with self.assertRaises(ValidationError):
            self.P.check_lead_time(doc, "before_update_after_submit")

    def test_a_failing_check_never_stops_the_order(self):
        self.fake["frappe"].get_all, saved = (lambda *a, **k: 1 / 0), self.fake["frappe"].get_all
        try:
            self.P.check_lead_time(self.po(), "before_submit")
        finally:
            self.fake["frappe"].get_all = saved
        self.assertEqual(self.fake["frappe"].logged[0][0], "Lead time check on Purchase Order failed")


if __name__ == "__main__":
    unittest.main()
