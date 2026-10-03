"""Quota scheduler tests use explicit job doubles, never production pressure fields."""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

CASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CASE))
from experiments.optimizer3d import Solver, run_parallel_tasks
import allsolve


class Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class SimulationDouble:
    def __init__(self, name, events, status=None):
        self.id, self.events, self.status = name, events, status
        self.job = SimpleNamespace(id="cloud-" + name, owner=self) if status is not None else None
        self.polls, self.starts = 0, 0

    def _get_job(self):
        return self.job

    def get_status(self):
        return self.status

    def start(self):
        self.starts += 1
        self.events.append(("start", self.id))
        self.status = allsolve.Job.QUEUED
        self.job = SimpleNamespace(id="cloud-" + self.id, owner=self)


def tasks_for(count, events):
    return [{"name": str(i), "run": {"simulation_id": str(i)}, "cached": False,
             "simulation": SimulationDouble(str(i), events)} for i in range(count)]


def quota(maximum=16, running=0, reserved=0):
    return SimpleNamespace(max_concurrent_cores=maximum, total_running_cores=running,
                           total_reserved_cores=reserved)


class ParallelSchedulerTests(unittest.TestCase):
    def execute(self, tasks, events, account=None, **changes):
        clock, progress = Clock(), []

        def refresh(jobs):
            events.append(("poll", [job.owner.id for job in jobs]))
            for job in jobs:
                owner = job.owner
                if owner.status in (allsolve.Job.ERROR, allsolve.Job.ABORTED, allsolve.Job.PARTIAL_SUCCESS):
                    continue
                owner.polls += 1
                owner.status = allsolve.Job.RUNNING if owner.polls == 1 else allsolve.Job.SUCCESS
                events.append(("status", owner.id, owner.status))

        options = {"quota_provider": lambda: account or quota(), "refresh_many": refresh,
                   "sleep": clock.sleep, "clock": clock, "poll_seconds": 1}
        options.update(changes)
        result = run_parallel_tasks(tasks, progress.append, **options)
        return result, progress

    def test_launches_many_before_one_collective_poll_and_observes_running(self):
        events = []
        tasks = tasks_for(6, events)
        result, progress = self.execute(tasks, events, quota(24))
        first_poll = next(i for i, event in enumerate(events) if event[0] == "poll")
        self.assertEqual(first_poll, 6)
        self.assertEqual(events[first_poll][1], [str(i) for i in range(6)])
        self.assertEqual(result["peak_parallel_solves"], 6)
        self.assertEqual(result["peak_allocated_cores"], 24)
        self.assertEqual(result["newly_started_basis_solves"], 6)
        self.assertEqual(result["completed_simulation_ids"], [str(i) for i in range(6)])
        self.assertEqual(progress[-1]["remaining_basis_solves"], 0)
        self.assertEqual(result["observations"][0]["running_count"], 6)

    def test_delayed_quota_reporting_does_not_oversubmit_local_shadow(self):
        events = []
        tasks = tasks_for(9, events)
        result, progress = self.execute(tasks, events, quota(16, 0, 0))
        # The provider deliberately never reflects our starts. Local in-flight
        # accounting must still limit this run to four four-core jobs.
        self.assertEqual(result["peak_inflight_solves"], 4)
        self.assertLessEqual(max(event["allocated_cores"] for event in progress), 16)
        self.assertEqual(sum(task["simulation"].starts for task in tasks), 9)

    def test_512_core_quota_is_used_without_a_low_artificial_parallel_cap(self):
        events = []
        tasks = tasks_for(192, events)
        result, _ = self.execute(tasks, events, quota(512, 10, 28))
        first_poll = next(i for i, event in enumerate(events) if event[0] == "poll")
        self.assertEqual(first_poll, 118)  # floor((512-10-28)/4)
        self.assertEqual(result["peak_parallel_solves"], 118)
        self.assertEqual(result["peak_allocated_cores"], 472)
        self.assertEqual(result["newly_started_basis_solves"], 192)

    def test_existing_running_job_is_preserved_and_pending_starts_before_it_finishes(self):
        events = []
        tasks = tasks_for(3, events)
        tasks[0]["simulation"] = SimulationDouble("0", events, allsolve.Job.RUNNING)
        result, _ = self.execute(tasks, events, quota(32, 4, 0))
        self.assertEqual(tasks[0]["simulation"].starts, 0)
        first_new_start = events.index(("start", "1"))
        existing_success = events.index(("status", "0", allsolve.Job.SUCCESS))
        self.assertLess(first_new_start, existing_success)
        self.assertEqual(result["newly_started_basis_solves"], 2)

    def test_all_cached_fields_need_no_quota_poll_or_cloud_start(self):
        tasks = [{"name": "cached", "cached": True, "run": {"simulation_id": "verified-original"}, "simulation": None}]

        def forbidden(*_):
            self.fail("A verified cache-only search must not contact cloud scheduling")

        result, progress = self.execute(tasks, [], quota_provider=forbidden, refresh_many=forbidden)
        self.assertEqual(result["newly_started_basis_solves"], 0)
        self.assertEqual(result["cached_basis_fields"], 1)
        self.assertEqual(progress[-1]["completed_basis_solves"], 1)

    def test_failed_existing_simulation_is_never_restarted(self):
        events = []
        tasks = tasks_for(2, events)
        tasks[0]["simulation"] = SimulationDouble("0", events, allsolve.Job.ERROR)
        with self.assertRaisesRegex(RuntimeError, "inspect before replacing"):
            self.execute(tasks, events)
        self.assertFalse(any(event[0] == "start" for event in events))

    def test_zero_available_cores_times_out_without_starting(self):
        events = []
        with self.assertRaisesRegex(TimeoutError, "resume"):
            self.execute(tasks_for(2, events), events, quota(16, 8, 8), timeout_seconds=2)
        self.assertFalse(any(event[0] == "start" for event in events))

    def test_many_healthy_waves_have_individual_not_global_deadlines(self):
        events, clock = [], Clock()
        tasks = tasks_for(5, events)

        def refresh(jobs):
            for job in jobs:
                owner = job.owner
                owner.polls += 1
                owner.status = allsolve.Job.RUNNING if owner.polls < 3 else allsolve.Job.SUCCESS

        result, _ = self.execute(tasks, events, quota(4), clock=clock, sleep=clock.sleep,
                                refresh_many=refresh, timeout_seconds=3)
        self.assertGreater(clock(), 3)
        self.assertEqual(result["newly_started_basis_solves"], 5)
        self.assertEqual(result["peak_parallel_solves"], 1)

    def test_one_stuck_job_times_out_without_restarting_its_simulation(self):
        events, clock = [], Clock()
        tasks = tasks_for(1, events)

        def still_running(jobs):
            for job in jobs:
                job.owner.status = allsolve.Job.RUNNING

        with self.assertRaisesRegex(TimeoutError, "independent cloud job"):
            self.execute(tasks, events, quota(4), clock=clock, sleep=clock.sleep,
                         refresh_many=still_running, timeout_seconds=2)
        self.assertEqual(tasks[0]["simulation"].starts, 1)

    def test_resource_contention_backoffs_but_authentication_failure_does_not(self):
        events = []
        tasks = tasks_for(1, events)
        simulation = tasks[0]["simulation"]
        original_start = simulation.start
        calls = []

        def transient():
            calls.append(True)
            if len(calls) == 1:
                error = RuntimeError("not printed")
                error.body = '{"reason":"resource_unavailable"}'
                raise error
            original_start()

        simulation.start = transient
        result, _ = self.execute(tasks, events)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["newly_started_basis_solves"], 1)
        tasks = tasks_for(1, [])
        tasks[0]["simulation"].start = lambda: (_ for _ in ()).throw(PermissionError("unauthorized"))
        with self.assertRaises(PermissionError):
            self.execute(tasks, [])

    def test_field_cache_checksum_is_verified_before_reuse_or_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            solver = Solver.__new__(Solver)
            solver.here, solver.prepared = Path(directory), {}
            path = solver.here / "fields" / "src1__baseline" / "complex.npz"
            path.parent.mkdir(parents=True)
            # Only a checksum fixture; these bytes are never sampled as physics.
            path.write_bytes(b"test-only-cache-certificate")
            solver.state = {"runs": {"src1__baseline": {"status": "SUCCESS", "simulation_id": "historical",
                "field_cache_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}}
            task = solver.prepare_basis("src1", ())
            self.assertTrue(task["cached"])
            self.assertIsNone(task["simulation"])
            solver.prepared.clear()
            path.write_bytes(b"corrupted")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                solver.prepare_basis("src1", ())


if __name__ == "__main__":
    unittest.main()
