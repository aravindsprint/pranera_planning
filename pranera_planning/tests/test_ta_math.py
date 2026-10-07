"""ta_math: a plan's levels scheduled backwards from delivery, rebuilds that keep what
happened, and how each activity stands."""
import unittest

from pranera_planning import ta_math as T

LEVELS = [  # finished ← dyed ← greige ← yarn, as the planner returns them (depth 0 = top)
    {"item": "SKF", "request": 1900, "made": True, "depth": 0, "stage": "Finishing", "route": "In-house", "stage_days": 3},
    {"item": "DKF", "request": 1950, "made": True, "depth": 1, "stage": "Dyeing", "route": "Job work", "stage_days": 10},
    {"item": "GKF", "request": 2000, "made": True, "depth": 2, "stage": "Knitting", "route": "In-house", "stage_days": 7},
    {"item": "YARN", "request": 2075, "made": False, "depth": 3, "lead_days": 45, "supplier": "HANGZHOU"},
    {"item": "OWN", "request": 0, "made": True, "depth": 1, "stage": "Dyeing", "stage_days": 10},   # covered by stock
]


class TestSchedule(unittest.TestCase):
    def setUp(self):
        self.acts = T.schedule(LEVELS, "2026-12-31")

    def test_backwards_from_delivery(self):
        by = {a["item_code"]: a for a in self.acts}
        self.assertEqual((by["SKF"]["planned_start"], by["SKF"]["planned_end"]), ("2026-12-28", "2026-12-31"))
        self.assertEqual((by["DKF"]["planned_start"], by["DKF"]["planned_end"]), ("2026-12-18", "2026-12-28"))
        self.assertEqual((by["GKF"]["planned_start"], by["GKF"]["planned_end"]), ("2026-12-11", "2026-12-18"))
        self.assertEqual((by["YARN"]["planned_start"], by["YARN"]["planned_end"]), ("2026-10-27", "2026-12-11"))

    def test_order_and_kinds(self):
        self.assertEqual([a["activity"] for a in self.acts], ["Buy", "Knitting", "Dyeing", "Finishing", "Ready to deliver"])
        self.assertEqual(self.acts[0]["route"], "Bought")
        self.assertEqual(self.acts[-1]["kind"], T.MILESTONE)

    def test_stock_already_there_needs_no_activity(self):
        self.assertNotIn("OWN", [a["item_code"] for a in self.acts])


class TestComing(unittest.TestCase):
    def test_what_is_already_coming_is_still_an_activity(self):
        lv = [{"item": "YARN", "request": 0, "coming": 2000, "made": False, "depth": 0, "lead_days": 45}]
        acts = T.schedule(lv, "2026-11-24")
        self.assertEqual((acts[0]["activity"], acts[0]["qty"], acts[0]["planned_start"]), ("Buy", 2000.0, "2026-10-10"))


class TestMerge(unittest.TestCase):
    def test_a_started_activity_no_longer_needed_stays_as_history(self):
        old = T.schedule([{"item": "YARN", "request": 2000, "made": False, "depth": 0, "lead_days": 45}], "2026-11-24")
        old[0]["actual_start"] = "2026-10-10"
        out = T.merge(old, T.schedule([], "2026-11-24"))
        self.assertIn("YARN", [a["item_code"] for a in out])

    def test_started_activities_keep_their_dates_and_baselines_stay(self):
        old = T.schedule(LEVELS, "2026-12-31")
        for a in old:
            a["baseline_end"] = a["planned_end"]
            if a["item_code"] == "YARN":
                a["actual_start"] = "2026-10-27"
        old.append({"activity": "Lab dip approved", "kind": T.MILESTONE, "source": "manual", "planned_end": "2026-11-15"})
        new = T.schedule(LEVELS, "2027-01-10")                       # delivery moved 10 days
        out = {(a["activity"], a.get("item_code")): a for a in T.merge(old, new)}
        self.assertEqual(out[("Buy", "YARN")]["planned_end"], "2026-12-11")          # started: kept
        self.assertEqual(out[("Finishing", "SKF")]["planned_end"], "2027-01-10")     # not started: moved
        self.assertEqual(out[("Finishing", "SKF")]["baseline_end"], "2026-12-31")    # first plan kept as baseline
        self.assertIn(("Lab dip approved", None), out)                              # manual milestone kept


class TestStatus(unittest.TestCase):
    ACT = {"kind": T.STAGE, "qty": 2000, "planned_start": "2026-12-11", "planned_end": "2026-12-18",
           "baseline_end": "2026-12-15"}

    def test_not_started_late(self):
        s = T.status_of(self.ACT, {}, "2026-12-13")
        self.assertEqual((s["status"], s["late_start"], s["delay_days"], s["slip_days"]), (T.NOT_STARTED, True, 0, 3))

    def test_in_progress_past_its_end(self):
        s = T.status_of(self.ACT, {"start": "2026-12-12", "done_qty": 900}, "2026-12-20")
        self.assertEqual((s["status"], s["delay_days"], s["actual_end"]), (T.IN_PROGRESS, 2, None))

    def test_done_within_tolerance(self):
        s = T.status_of(self.ACT, {"start": "2026-12-12", "end": "2026-12-17", "done_qty": 1965}, "2026-12-20")
        self.assertEqual((s["status"], s["delay_days"]), (T.DONE, -1))

    def test_milestone_is_closed_by_hand(self):
        m = {"kind": T.MILESTONE, "planned_end": "2026-11-15", "actual_end": "2026-11-17"}
        self.assertEqual((T.status_of(m, {}, "2026-11-20")["status"], T.status_of(m, {}, "2026-11-20")["delay_days"]),
                         (T.DONE, 2))

    def test_summary(self):
        rows = [{**self.ACT, **T.status_of(self.ACT, {}, "2026-12-13")},
                {**self.ACT, **T.status_of(self.ACT, {"start": "2026-12-12", "end": "2026-12-17", "done_qty": 2000}, "2026-12-13")}]
        s = T.summary(rows, "2026-12-13")
        self.assertEqual((s["done"], s["late"], s["on_track"]), (1, 1, False))


if __name__ == "__main__":
    unittest.main()
