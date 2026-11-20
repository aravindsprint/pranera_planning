"""mr_moves: taking quantity off a project's Manufacture requests to move it to job work."""
import sys
import unittest

from pranera_planning.tests.test_stock_entry_checks import _dict, _fake_frappe


class FakeMR(_dict):
    def set(self, k, v):
        self[k] = v


class TestMoves(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved = {n: sys.modules.get(n) for n in ("frappe", "frappe.utils", "pranera_planning.mr_moves")}
        sys.modules.update(_fake_frappe())
        sys.modules.pop("pranera_planning.mr_moves", None)
        import pranera_planning.mr_moves as M
        cls.M = M

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            sys.modules.pop(n, None) if m is None else sys.modules.__setitem__(n, m)

    LINES = [{"mr": "MR-26", "docstatus": 0, "row": "a", "open": 1000, "mr_ordered": 0},
             {"mr": "MR-20", "docstatus": 1, "row": "b", "open": 1500, "mr_ordered": 0},
             {"mr": "MR-10", "docstatus": 1, "row": "c", "open": 800, "mr_ordered": 300}]   # has a Work Order

    def test_drafts_first_then_submitted_never_one_with_work_orders(self):
        cuts, left = self.M.plan_reductions(self.LINES, 1500)
        self.assertEqual((cuts, left), ([("MR-26", "a", 1000), ("MR-20", "b", 500)], 0.0))
        cuts, left = self.M.plan_reductions(self.LINES, 3000)
        self.assertEqual(left, 500)                                           # MR-10's 800 can't move

    def test_cut_reduces_and_drops_empty_lines(self):
        doc = FakeMR(items=[_dict(name="a", stock_qty=1500, qty=1500, conversion_factor=1),
                            _dict(name="b", stock_qty=1500, qty=1500, conversion_factor=1)])
        self.M._cut(doc, {"a": 500, "b": 1500})
        self.assertEqual([(l.name, l.qty) for l in doc["items"]], [("a", 1000)])


if __name__ == "__main__":
    unittest.main()
