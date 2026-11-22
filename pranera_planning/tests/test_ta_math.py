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


    def test_ordered_beyond_what_the_plan_counted_is_still_tracked(self):
        # free stock covers the level, so the plan counts nothing coming — but 2,000 is on order
        lv = [{"item": "YARN", "request": 0, "coming": 0, "coming_all": 2000, "made": False, "depth": 0, "lead_days": 10}]
        self.assertEqual(T.schedule(lv, "2026-11-24")[0]["qty"], 2000.0)


class TestSplitByRoute(unittest.TestCase):
    def test_a_level_partly_with_a_job_worker_is_two_activities(self):
        lv = [{"item": "GKF", "request": 30, "coming": 70, "coming_job_work": 0, "made": True, "depth": 0,
               "stage": "Knitting", "route": "Job work", "stage_days": 20,
               "stage_days_by_route": {"In-house": 7, "Job work": 20}}]
        acts = {a["route"]: a for a in T.schedule(lv, "2026-12-31") if a["kind"] == T.STAGE}
        self.assertEqual((acts["In-house"]["qty"], acts["Job work"]["qty"]), (70.0, 30.0))
        self.assertEqual((acts["In-house"]["duration_days"], acts["Job work"]["duration_days"]), (7, 20))

    def test_job_work_back_to_in_house(self):
        lv = [{"item": "SKF", "request": 40, "coming": 60, "coming_job_work": 60, "made": True, "depth": 0,
               "stage": "Finishing", "route": "In-house", "stage_days": 3}]
        acts = {a["route"]: a["qty"] for a in T.schedule(lv, "2026-12-31") if a["kind"] == T.STAGE}
        self.assertEqual(acts, {"In-house": 40.0, "Job work": 60.0})

    def test_a_booking_stays_with_its_in_house_part(self):
        lv = [{"item": "GKF", "request": 0, "coming": 100, "coming_job_work": 0, "made": True, "depth": 0,
               "stage": "Knitting", "route": "In-house", "stage_days": 7}]
        old = T.schedule(lv, "2026-12-31")
        old[0].update(workstation="FK01", planned_start="2026-12-01", planned_end="2026-12-05")
        lv[0].update(coming_job_work=30)                                    # 30 moved to job work
        out = {(a["route"], a["kind"]): a for a in T.merge(old, T.schedule(lv, "2026-12-31"))}
        self.assertEqual(out[("In-house", T.STAGE)]["workstation"], "FK01")
        self.assertEqual(out[("In-house", T.STAGE)]["qty"], 70.0)
        self.assertFalse(out[("Job work", T.STAGE)].get("workstation"))


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
