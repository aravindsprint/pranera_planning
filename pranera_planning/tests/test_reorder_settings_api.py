"""api.reorder_settings against the frappe stand-in: what a save keeps, drops and refuses."""
import importlib
import sys
import unittest

from pranera_planning.tests.test_stock_entry_checks import _dict, _fake_frappe


class FakeSettings(_dict):
    def set(self, key, value):
        self[key] = value

    def append(self, table, values):
        self.setdefault(table, []).append(_dict(values))

    def save(self):
        self["saved"] = True


class TestReorderSettingsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "pranera_planning.api.reorder_settings"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        fake = _fake_frappe()
        fake["frappe.utils"].cint = lambda v: int(float(v or 0))
        sys.modules.update(fake)
        sys.modules.pop("pranera_planning.api.reorder_settings", None)
        cls.api = importlib.import_module("pranera_planning.api.reorder_settings")
        cls.f = fake["frappe"]

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m

    def setUp(self):
        self.doc = FakeSettings(
            history_days=90, stock_project_pattern="{YY}STK-{FAMILY}-{PERIOD}", group_rules=[], seasons=[],
            stage_leads=[_dict(stage="Knitting", route="In-house", override_days=0, inhouse_days=20.4, inhouse_orders=171,
                               jobwork_days=6.0, jobwork_orders=18)])
        self.f.get_single = lambda dt: self.doc
        self.f.has_permission = lambda *a, **k: True

    def test_save_keeps_learned_figures_and_drops_empty_rows(self):
        out = self.api.save_settings({
            "history_days": "60", "stock_project_pattern": "{YY}STK-{FAMILY}-{PERIOD}-{SEQ}",
            "stage_leads": [{"stage": "Knitting", "route": "In-house", "override_days": 5, "inhouse_days": 999},
                            {"stage": "", "override_days": 3}],
            "group_rules": [{"item_group": "YARN", "round_to": 25}, {"item_group": "", "round_to": 5}],
            "seasons": [{"season": "SUMMER", "start_month": "2"}, {"season": "", "start_month": "8"}],
        })
        self.assertTrue(self.doc.saved)
        self.assertEqual(out["history_days"], 60)
        self.assertEqual(len(out["stage_leads"]), 1)
        k = out["stage_leads"][0]
        self.assertEqual((k["override_days"], k["inhouse_days"], k["inhouse_orders"]), (5, 20.4, 171))   # learned kept, not 999
        self.assertEqual([r["item_group"] for r in out["group_rules"]], ["YARN"])
        self.assertEqual([r["season"] for r in out["seasons"]], ["SUMMER"])

    def test_a_pattern_without_family_is_refused(self):
        with self.assertRaises(self.f.ValidationError):
            self.api.save_settings({"stock_project_pattern": "{YY}STK-{PERIOD}-{SEQ}"})
        self.assertNotIn("saved", self.doc)


if __name__ == "__main__":
    unittest.main()
