"""api.reorder.get_reorder_report against the frappe stand-in."""
import importlib
import sys
import types
import unittest

from pranera_planning.tests.test_stock_entry_checks import _dict, _fake_frappe

ROWS = [
    _dict(name="SKF", status="OK", suggest_qty=0, obtained="Made", lead_days=15),
    _dict(name="DKF", status="Order now", suggest_qty=750, obtained="Made", lead_days=12),
    _dict(name="GKF", status="Order now", suggest_qty=675, obtained="Made", lead_days=0),
    _dict(name="YSP", status="Near", suggest_qty=0, obtained="Bought", lead_days=21),
]


class TestReorderApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "pranera_planning.api.reorder"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        fake = _fake_frappe()
        f = fake["frappe"]

        def get_all(doctype, filters=None, or_filters=None, fields=None, group_by=None, limit_page_length=None, **kw):
            rows = [r for r in ROWS if not (filters or {}).get("status") or r.status == filters["status"]]
            if group_by == "status":
                out = {}
                for r in rows:
                    out[r.status] = out.get(r.status, 0) + 1
                return [_dict(status=k, n=v) for k, v in out.items()]
            return [_dict(r) for r in rows]
        f.get_all = get_all
        f.get_single = lambda dt: _dict(history_days=90, near_margin=10, last_run="2026-09-30 02:00:00", last_run_items=4,
                                        use_learned_lead_days=0,
                                        stage_leads=[_dict(stage="Knitting", override_days=0, inhouse_days=20.4),
                                                     _dict(stage="Dyeing", override_days=7)])
        sys.modules.update(fake)
        sys.modules.pop("pranera_planning.api.reorder", None)
        cls.api = importlib.import_module("pranera_planning.api.reorder")

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m

    def test_order_now_first_biggest_suggestion_first(self):
        r = self.api.get_reorder_report()
        self.assertEqual([x["item_code"] for x in r["rows"]], ["DKF", "GKF", "YSP", "SKF"])

    def test_counts_ignore_the_status_filter(self):
        r = self.api.get_reorder_report(status="Order now")
        self.assertEqual([x["item_code"] for x in r["rows"]], ["DKF", "GKF"])
        self.assertEqual(r["counts"], {"Order now": 2, "Near": 1, "OK": 1, "Over max": 0, "No demand": 0})
        self.assertEqual(r["total"], 4)

    def test_made_items_without_lead_days_are_flagged(self):
        r = {x["item_code"]: x for x in self.api.get_reorder_report()["rows"]}
        self.assertTrue(r["GKF"]["lead_missing"])
        self.assertFalse(r["YSP"]["lead_missing"])      # bought: lead days come from the supplier

    def test_stages_without_days_are_reported(self):
        self.assertEqual(self.api.get_reorder_report()["settings"]["stages_without_days"], ["Knitting"])


if __name__ == "__main__":
    unittest.main()
