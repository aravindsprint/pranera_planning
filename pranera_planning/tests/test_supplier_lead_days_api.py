"""api.supplier_lead_days against the frappe stand-in: a save sets what changed, clears rows
taken off the page, and adds a Supplier Items row when the item has none for that supplier."""
import importlib
import sys
import unittest

from pranera_planning.tests.test_stock_entry_checks import WORLD, _dict, _fake_frappe


class FakeItem(_dict):
    def append(self, table, values):
        self.setdefault(table, []).append(values)

    def save(self):
        self["saved"] = True


class TestSupplierLeadDaysApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "pranera_planning.api.supplier_lead_days"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        cls.fake = _fake_frappe()
        cls.fake["frappe.utils"].cint = lambda v: int(float(v or 0))
        sys.modules.update(cls.fake)
        sys.modules.pop("pranera_planning.api.supplier_lead_days", None)
        cls.api = importlib.import_module("pranera_planning.api.supplier_lead_days")

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            sys.modules.pop(n, None) if m is None else sys.modules.__setitem__(n, m)
        WORLD.clear()

    def test_save_sets_clears_and_adds(self):
        f = self.fake["frappe"]
        WORLD["Supplier"] = lambda flt: [_dict(name="ZHEJIANG", usual_lead_days=40), _dict(name="OLD MILL", usual_lead_days=20)]
        WORLD["Item Supplier"] = lambda flt: []
        written, items = [], {}
        f.db.set_value = lambda dt, name, field, value: written.append((dt, name, field, value))
        f.db.get_value = lambda dt, flt, field: "row-1" if flt.get("supplier") == "SRI MILLS" and flt.get("parent") == "MELANGE" else None
        f.get_doc = lambda dt, name: items.setdefault(name, FakeItem(name=name))
        self.api.save_lead_days({
            "supplier_leads": [{"supplier": "ZHEJIANG", "usual_lead_days": 45}, {"supplier": "SRI MILLS", "usual_lead_days": 15}],
            "item_supplier_leads": [{"item_code": "MELANGE", "supplier": "SRI MILLS", "lead_days": 45},
                                    {"item_code": "SLUB", "supplier": "SRI MILLS", "lead_days": 30}],
        })
        self.assertIn(("Supplier", "ZHEJIANG", "usual_lead_days", 45), written)
        self.assertIn(("Supplier", "SRI MILLS", "usual_lead_days", 15), written)
        self.assertIn(("Supplier", "OLD MILL", "usual_lead_days", 0), written)        # taken off the page
        self.assertIn(("Item Supplier", "row-1", "lead_days", 45), written)           # existing row
        self.assertEqual(items["SLUB"]["supplier_items"], [{"supplier": "SRI MILLS", "lead_days": 30}])
        self.assertTrue(items["SLUB"]["saved"])


if __name__ == "__main__":
    unittest.main()
