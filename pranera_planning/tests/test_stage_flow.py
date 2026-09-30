"""The Produced section's stage table: input / in process / produced / loss per stage,
kept apart by unit. Runs api.reservation._stages against a frappe stand-in."""
import importlib
import sys
import unittest

from pranera_planning.tests.test_stock_entry_checks import _fake_frappe


def produced(stage, rank, uom, qty, stores=0.0, used_own=0.0, wip=0.0):
    return {"stage": stage, "stage_rank": rank, "uom": uom, "received_qty": qty, "available_qty": stores,
            "elsewhere": {"In WIP": wip} if wip else {}, "used_own_qty": used_own, "used_other": []}


def flow(inp=0.0, in_process=0.0, orders=("WO-1",), other=None):
    return {"input": inp, "in_process": in_process, "orders": set(orders),
            "other_input": dict(other or {}), "other_in_process": {}}


class TestStageFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "pranera_planning.reservation", "pranera_planning.api.reservation"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        sys.modules.update(_fake_frappe())
        for n in names[2:]:
            sys.modules.pop(n, None)
        cls.api = importlib.import_module("pranera_planning.api.reservation")

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m

    def stages(self, rows, fl):
        return {s["stage"]: s for s in self.api._stages(rows, fl)}

    def test_loss_excludes_what_is_still_in_process(self):
        # your local case: 2000 yarn in, 500 greige out so far, 1500 still in WIP
        s = self.stages([produced("Knitting", 0, "Kgs", 500)], {(0, "Knitting", "Kgs"): flow(2000, 1500)})
        k = s["Knitting"]
        self.assertEqual((k["input_qty"], k["in_process_qty"], k["produced_qty"], k["loss_qty"]), (2000, 1500, 500, 0))

    def test_real_loss(self):
        s = self.stages([produced("Knitting", 0, "Kgs", 40947.7)], {(0, "Knitting", "Kgs"): flow(41115.6, 0)})
        self.assertAlmostEqual(s["Knitting"]["loss_qty"], 167.9, places=1)

    def test_same_operation_in_two_units_is_kept_apart(self):
        rows = [produced("Knitting", 0, "Kgs", 40947.7), produced("Knitting", 0, "Pcs", 1200)]
        fl = {(0, "Knitting", "Kgs"): flow(41115.6), (0, "Knitting", "Pcs"): flow(other={"Kgs": 300})}
        s = self.stages(rows, fl)
        self.assertEqual(set(s), {"Knitting (Kgs)", "Knitting (Pcs)"})
        pcs = s["Knitting (Pcs)"]
        self.assertIsNone(pcs["loss_qty"])                       # kilos in, pieces out: no loss figure
        self.assertEqual(pcs["other_input"], [{"uom": "Kgs", "qty": 300, "in_process": 0.0}])

    def test_stage_with_orders_but_nothing_produced_yet(self):
        s = self.stages([], {(1, "Dyeing", "Kgs"): flow(400, 400)})
        d = s["Dyeing"]
        self.assertEqual((d["produced_qty"], d["in_process_qty"], d["loss_qty"], d["batches"]), (0, 400, 0, 0))

    def test_steps_ordered_and_side_by_side_flagged(self):
        rows = [produced("Dyeing", 1, "Kgs", 10), produced("Knitting", 0, "Kgs", 10), produced("Collar Knitting", 0, "Pcs", 5)]
        out = self.api._stages(rows, {})
        self.assertEqual([x["stage"] for x in out], ["Collar Knitting", "Knitting", "Dyeing"])
        self.assertTrue(out[0]["shared_step"])
        self.assertFalse(out[2]["shared_step"])


if __name__ == "__main__":
    unittest.main()
