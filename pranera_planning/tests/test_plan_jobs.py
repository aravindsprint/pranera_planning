"""api.plan start / job_status: the plan's background job, against the frappe stand-in."""
import enum
import importlib
import sys
import types
import unittest

from pranera_planning.tests.test_stock_entry_checks import _fake_frappe


class JobStatus(str, enum.Enum):                 # as rq defines it
    QUEUED = "queued"
    STARTED = "started"
    FINISHED = "finished"
    FAILED = "failed"


class FakeJob:
    def __init__(self, status, user="planner@x", returned=None):
        self.status, self.kwargs, self.returned = status, {"user": user}, returned

    def get_status(self):
        return self.status

    def return_value(self):
        return self.returned


class TestPlanJobs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ["frappe", "frappe.utils", "frappe.utils.background_jobs", "pranera_planning.api.plan",
                 "pranera_planning.planner", "pranera_planning.reservation", "pranera_planning.reorder"]
        cls._saved = {n: sys.modules.get(n) for n in names}
        fake = _fake_frappe()
        u = fake["frappe.utils"]
        u.add_days, u.add_months, u.today, u.getdate = (lambda d, n: d), (lambda d, n: d), (lambda: "2026-10-01"), (lambda d=None: d)
        u.now_datetime = lambda: "2026-10-01 10:00:00"
        fake["frappe"].defaults = types.SimpleNamespace(get_user_default=lambda k: "Pranera")
        cls.bj = types.ModuleType("frappe.utils.background_jobs")
        fake["frappe.utils.background_jobs"] = cls.bj
        sys.modules.update(fake)
        for n in names[3:]:
            sys.modules.pop(n, None)
        cls.api = importlib.import_module("pranera_planning.api.plan")
        cls.f = fake["frappe"]

    @classmethod
    def tearDownClass(cls):
        for n, m in cls._saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m

    def setUp(self):
        self.jobs = {}
        self.bj.get_job = lambda job_id: self.jobs.get(job_id)
        self.f.session = types.SimpleNamespace(user="planner@x")

    def status(self, job="abc"):
        return self.api.job_status(job)

    def test_queued_and_running(self):
        self.jobs["pranera-plan-abc"] = FakeJob(JobStatus.QUEUED)
        self.assertEqual(self.status(), {"status": "queued"})
        self.jobs["pranera-plan-abc"] = FakeJob(JobStatus.STARTED)
        self.assertEqual(self.status(), {"status": "running"})

    def test_finished_returns_the_result_or_the_error(self):
        self.jobs["pranera-plan-abc"] = FakeJob(JobStatus.FINISHED, returned={"ok": True, "result": [1]})
        self.assertEqual(self.status(), {"status": "done", "result": [1]})
        self.jobs["pranera-plan-abc"] = FakeJob(JobStatus.FINISHED, returned={"ok": False, "error": "No warehouse"})
        self.assertEqual(self.status(), {"status": "failed", "error": "No warehouse"})

    def test_a_crashed_job_is_failed(self):
        self.jobs["pranera-plan-abc"] = FakeJob(JobStatus.FAILED)
        self.assertEqual(self.status()["status"], "failed")

    def test_an_unknown_job_and_someone_elses_job_are_refused(self):
        with self.assertRaises(Exception):
            self.status("nope")
        self.jobs["pranera-plan-abc"] = FakeJob(JobStatus.QUEUED, user="other@x")
        with self.assertRaises(Exception):
            self.status()


if __name__ == "__main__":
    unittest.main()
