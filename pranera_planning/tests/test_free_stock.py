"""Free stock before buying: the real free_stock() and the Material Request hook, run
against the frappe stand-in with canned data."""
import importlib
import sys
import unittest

from pranera_planning.tests.test_stock_entry_checks import WORLD, Doc, _dict, _fake_frappe


class TestFreeStock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "pranera_planning.reservation"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        fakes = _fake_frappe()
        sys.modules.update(fakes)
        sys.modules.pop("pranera_planning.reservation", None)
        cls.R = importlib.import_module("pranera_planning.reservation")
        cls.frappe = fakes["frappe"]

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m
        WORLD.clear()

    def setUp(self):
        R, f = self.R, self.frappe
        f.messages.clear()
        f.logged.clear()
        # YRFPP090/GREIGE: batch 5678 (25PUR001) 975 free in Stores; batch 9999 (25PROD001, the
        # asker) 300 in Stores of which 100 reserved for someone; DRYER is a service.
        WORLD["Item"] = lambda flt: (
            [_dict(name="YRFPP090/GREIGE", stock_uom="Kgs")]
            if "YRFPP090/GREIGE" in (flt or {}).get("name", [None, []])[1] else [])
        WORLD["Batch"] = lambda flt: [_dict(name="5678", item="YRFPP090/GREIGE"), _dict(name="9999", item="YRFPP090/GREIGE")]
        WORLD["Project Stock Reservation"] = lambda flt: ["9999"]
        R.get_stock_locations = lambda batches: {
            "5678": {"Stores - PSS": {"available": 975.0, "rolls": {}}},
            "9999": {"Stores - PSS": {"available": 300.0, "rolls": {}}},
        }
        f.db.sql = lambda q, *a, **k: [("5678", "25PUR001"), ("9999", "25PROD001")] if "Purchase Receipt Item" in q else []
        R.get_produced_owners = lambda batches: {}
        R.get_reservation_state = lambda batches, **kw: {"9999": {
            "available": 300.0, "locations": {"Stores - PSS": {"available": 300.0, "rolls": {}}},
            "reservations": [{"name": "PSR-X", "status": "Active", "production_project": "26PTIN1645",
                              "warehouse": "Stores - PSS", "roll_no": "", "reserved_qty": 100.0,
                              "issued_qty": 0.0, "remaining_qty": 100.0}]}}

    def test_free_stock_summary(self):
        st = self.R.free_stock(["YRFPP090/GREIGE", "DRYER"], for_project="25PROD001")
        self.assertEqual(set(st), {"YRFPP090/GREIGE"})               # the service is ignored
        y = st["YRFPP090/GREIGE"]
        self.assertEqual((y["own"], y["elsewhere"], y["uom"]), (200.0, 975.0, "Kgs"))   # 300 - 100 reserved
        self.assertEqual(y["projects"][0]["project"], "25PUR001")

    def test_stock_produced_for_another_project_does_not_count_for_a_purchase(self):
        R, f = self.R, self.frappe
        f.db.sql = lambda q, *a, **k: [("9999", "25PROD001")] if "Purchase Receipt Item" in q else []   # 5678 not purchased
        R.get_produced_owners = lambda batches: {"5678": "26PTIN1645"}                                # ... but produced for 26PTIN1645
        shown = R.free_stock(["YRFPP090/GREIGE"], for_project="25PROD001")["YRFPP090/GREIGE"]
        counted = R.free_stock(["YRFPP090/GREIGE"], for_project="25PROD001", include_produced_elsewhere=False)["YRFPP090/GREIGE"]
        self.assertEqual(shown["elsewhere"], 975.0)          # the page still shows it (it can be reserved across)
        self.assertEqual(counted["elsewhere"], 0.0)          # but a purchase isn't expected to use it
        self.assertEqual(counted["own"], 200.0)

    def request(self, qty=2000):
        comments = []
        d = Doc(material_request_type="Purchase", project=None, reservation_override_reason=None, items=[
            Doc(item_code="YRFPP090/GREIGE", stock_qty=qty, qty=qty, project="25PROD001"),
            Doc(item_code="DRYER", stock_qty=500, qty=500, project="25PROD001"),
        ])
        d.add_comment = lambda kind, text: comments.append(text)
        d.comments = comments
        return d

    def settings(self, mode="block", roles=("Purchase Manager",), minimums=()):
        self.R.mr_check_settings = lambda: {"mode": mode, "roles": set(roles), "minimums": list(minimums)}
        WORLD["Item"] = self._items
        WORLD["Item Group"] = lambda flt: [_dict(name="YARN", lft=10, rgt=20)]

    def _items(self, flt):
        names = (flt or {}).get("name", [None, []])[1]
        if "YRFPP090/GREIGE" not in names:
            return []
        return [_dict(name="YRFPP090/GREIGE", item_group="YARN", stock_uom="Kgs")]

    def run_check(self, d, method):
        self.frappe.messages.clear()
        self.frappe.logged.clear()
        try:
            self.R.check_material_request(d, method)
            return "allowed"
        except self.frappe.ValidationError as e:
            self.last_error = str(e)
            return "blocked"

    # 2,000 requested; free for 25PROD001: 200 of its own + 975 under 25PUR001 = 1,175 -> at most 825

    def test_save_shows_what_is_free_and_the_most_you_can_request(self):
        self.settings()
        self.assertEqual(self.run_check(self.request(), "validate"), "allowed")
        self.assertEqual(self.frappe.logged, [])
        title, msg = self.frappe.messages[0]
        self.assertIn("instead of buying", title)
        self.assertIn('href="/planning-app/project-stock-reservation?project=25PUR001"', msg)
        self.assertIn("at most <b>825 Kgs</b>", msg)
        self.assertIn("already free under this project", msg)
        self.assertNotIn("DRYER", msg)

    def test_submit_is_refused_for_a_normal_user(self):
        self.settings()
        self.frappe.roles = ["Stock User"]
        self.assertEqual(self.run_check(self.request(), "before_submit"), "blocked")
        self.assertIn("Only these roles can buy anyway", self.last_error)
        self.assertIn("Purchase Manager", self.last_error)

    def test_override_role_with_a_reason_goes_through_and_is_recorded(self):
        self.settings(roles=("Buyer Head",))                     # roles come from the settings, not code
        self.frappe.roles = ["Buyer Head"]
        d = self.request()
        d.reservation_override_reason = "Free lot is a different shade"
        self.assertEqual(self.run_check(d, "before_submit"), "allowed")
        self.assertIn("Free lot is a different shade", d.comments[0])
        self.assertIn("tester@example.com", d.comments[0])

    def test_a_stock_plans_request_is_not_blocked_but_noted(self):
        self.settings()
        self.frappe.roles = ["Stock User"]
        d = self.request()
        d.from_stock_plan = 1
        self.assertEqual(self.run_check(d, "validate"), "allowed")
        self.assertEqual(self.frappe.messages, [])                    # no orange notice on save
        self.assertEqual(self.run_check(d, "before_submit"), "allowed")
        self.assertIn("From a stock plan", d.comments[0])
        self.assertIn("1,175", d.comments[0])

    def test_override_role_without_a_reason_is_asked_for_one(self):
        self.settings(roles=("Buyer Head",))
        self.frappe.roles = ["Buyer Head"]
        self.assertEqual(self.run_check(self.request(), "before_submit"), "blocked")
        self.assertIn("Override reason", self.last_error)

    def test_a_role_not_in_the_settings_cannot_override(self):
        self.settings(roles=("Buyer Head",))
        self.frappe.roles = ["Purchase Manager"]
        d = self.request()
        d.reservation_override_reason = "please"
        self.assertEqual(self.run_check(d, "before_submit"), "blocked")

    def test_nothing_requested_beyond_free_stock_goes_through(self):
        self.settings()
        self.assertEqual(self.run_check(self.request(qty=0), "before_submit"), "allowed")

    def test_warn_mode_lets_submit_through(self):
        self.settings(mode="warn")
        self.assertEqual(self.run_check(self.request(), "before_submit"), "allowed")
        self.assertEqual(len(self.frappe.messages), 1)

    def test_off_mode_says_nothing(self):
        self.settings(mode="off")
        self.assertEqual(self.run_check(self.request(), "before_submit"), "allowed")
        self.assertEqual(self.frappe.messages, [])

    def test_leftovers_below_the_group_minimum_are_ignored(self):
        self.settings(minimums=[(1, 100, 2000)])                 # ignore free stock under 2,000 kg
        self.assertEqual(self.run_check(self.request(), "before_submit"), "allowed")
        self.assertEqual(self.frappe.messages, [])

    def test_other_request_types_are_left_alone(self):
        self.settings()
        d = self.request()
        d.material_request_type = "Manufacture"
        self.assertEqual(self.run_check(d, "before_submit"), "allowed")
        self.assertEqual(self.frappe.messages, [])

    def test_a_failure_never_blocks_but_is_shown(self):
        self.settings()
        saved = self.R.get_stock_locations

        def boom(*a, **k):
            raise RuntimeError("db down")
        self.R.get_stock_locations = boom
        try:
            self.assertEqual(self.run_check(self.request(), "before_submit"), "allowed")
            self.assertEqual(len(self.frappe.logged), 1)
            self.assertIn("skipped", self.frappe.messages[0][0])
        finally:
            self.R.get_stock_locations = saved


if __name__ == "__main__":
    unittest.main()
