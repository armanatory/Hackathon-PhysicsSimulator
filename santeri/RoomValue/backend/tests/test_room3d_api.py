"""API contract and restart recovery; cloud calls are mocked at the SDK boundary."""

from __future__ import annotations

import math
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import app as api
from backend.job_store import JobStore


CATALOG = {
    "room": {"size_m": [5.705, 5.965, 2.355]},
    "sources": [{"id": "src1", "position_m": [1.89407487, 4.52190448, 1.4481839]}],
    "slots": [{"id": "east_a", "position_m": [5.505, 2, 0.65], "size_m": [0.2, 2, 1]}],
}
REQUEST = {
    "sources": [{"id": "src1", "strength": 1}],
    "quiet_zones": [{"id": "reading", "center_m": [2.8, 3.4, 1.2], "size_m": [1, 1], "target_pressure_pa": 0.05}],
    "budget_eur": 500,
    "max_objects": 3,
    "allowed_slot_ids": ["east_a"],
    "object_cost_eur": 120,
}


class JobStoreTests(unittest.TestCase):
    def test_completed_survives_and_unfinished_is_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            original = JobStore(path)
            completed, running, queued = (str(uuid4()) for _ in range(3))
            original.create(completed, "room3d", REQUEST)
            original.update(completed, status="completed", result={"real_cloud_job_id": "cloud-1"})
            original.create(running, "room3d", REQUEST)
            original.update(running, status="running", progress={"evaluated": 2, "total": 6})
            original.create(queued, "room3d", REQUEST)
            (path / f"{uuid4()}.json").write_text("truncated{", encoding="utf-8")
            reloaded = JobStore(path)
            reloaded.load()
            self.assertEqual(reloaded.latest_completed("room3d")["job_id"], completed)
            self.assertEqual(reloaded.get(completed)["result"]["real_cloud_job_id"], "cloud-1")
            for job_id in (running, queued):
                self.assertEqual(reloaded.get(job_id)["status"], "interrupted")
                self.assertEqual(reloaded.get(job_id)["request"], REQUEST)
            self.assertEqual(reloaded.get(running)["progress"]["evaluated"], 2)
            self.assertEqual(JobStore._valid_id("../../outside"), False)

    def test_copy_cannot_modify_stored_result(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory))
            job_id = str(uuid4())
            store.create(job_id, "room3d", REQUEST)
            response = store.get(job_id)
            response["request"]["sources"][0]["strength"] = 10
            self.assertEqual(store.get(job_id)["request"]["sources"][0]["strength"], 1)


class Room3DApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.directory.name))
        self.executor = Mock()
        self.patches = [
            patch.object(api, "_store", self.store),
            patch.object(api, "_executor", self.executor),
            patch.object(api, "_ready3d", return_value=True),
            patch.object(api, "_get_catalog", return_value=deepcopy(CATALOG)),
            patch.object(api, "_optimizer_available", return_value=True),
        ]
        for item in self.patches:
            item.start()
        self.client_context = TestClient(api.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()
        api._active_job = None

    def test_catalog_and_latest_empty(self):
        response = self.client.get("/api/room3d/catalog")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["room"]["size_m"], CATALOG["room"]["size_m"])
        self.assertIs(response.json()["allsolve_ready"], True)
        self.assertEqual(self.client.get("/api/room3d/latest").status_code, 404)

    def test_rejects_outside_room_unknown_source_and_duplicate_ids(self):
        variants = []
        outside = deepcopy(REQUEST)
        outside["quiet_zones"][0]["center_m"][0] = 5.5
        variants.append(outside)
        tall = deepcopy(REQUEST)
        tall["quiet_zones"][0]["center_m"][2] = 2.355
        variants.append(tall)
        unknown = deepcopy(REQUEST)
        unknown["sources"][0]["id"] = "unmeasured"
        variants.append(unknown)
        duplicate = deepcopy(REQUEST)
        duplicate["allowed_slot_ids"] *= 2
        variants.append(duplicate)
        inside_source = deepcopy(REQUEST)
        inside_source["quiet_zones"][0]["center_m"] = CATALOG["sources"][0]["position_m"]
        variants.append(inside_source)
        inside_treatment = deepcopy(REQUEST)
        inside_treatment["quiet_zones"][0].update(center_m=[5.56, 3, 1.2], size_m=[0.1, 0.1])
        variants.append(inside_treatment)
        for request in variants:
            with self.subTest(request=request):
                self.assertEqual(self.client.post("/api/room3d/optimize", json=request).status_code, 422)
        self.executor.submit.assert_not_called()

    def test_rejects_invalid_budget_targets_sizes_strength_and_count(self):
        for field, value in (("budget_eur", -1), ("budget_eur", 100_001), ("object_cost_eur", -1), ("max_objects", 7), ("max_objects", 1.5)):
            request = deepcopy(REQUEST)
            request[field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(self.client.post("/api/room3d/optimize", json=request).status_code, 422)
        for field, value in (("target_pressure_pa", 0), ("target_pressure_pa", 101), ("size_m", [0, 1])):
            request = deepcopy(REQUEST)
            request["quiet_zones"][0][field] = value
            self.assertEqual(self.client.post("/api/room3d/optimize", json=request).status_code, 422)
        request = deepcopy(REQUEST)
        request["sources"][0]["strength"] = 0
        self.assertEqual(self.client.post("/api/room3d/optimize", json=request).status_code, 422)
        for bad_number in (math.inf, -math.inf, math.nan):
            request = deepcopy(REQUEST)
            request["quiet_zones"][0]["center_m"][0] = bad_number
            with self.assertRaises(ValidationError):
                api.OptimizeRequest3D.model_validate(request)

    def test_zero_budget_and_count_run_baseline_but_block_parallel_work(self):
        request = deepcopy(REQUEST)
        request.update(budget_eur=0, max_objects=0)
        accepted = self.client.post("/api/room3d/optimize", json=request)
        self.assertEqual(accepted.status_code, 202)
        job_id = accepted.json()["job_id"]
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").json()["request"]["max_objects"], 0)
        self.assertEqual(self.client.post("/api/room3d/optimize", json=REQUEST).status_code, 409)
        self.executor.submit.assert_called_once()

    def test_original_2d_endpoint_shares_the_busy_guard(self):
        self.assertEqual(self.client.post("/api/room3d/optimize", json=REQUEST).status_code, 202)
        comparison = {
            "room": {"width_m": 10, "length_m": 10}, "frequency_hz": 250,
            "source": {"x_m": 1, "y_m": 1}, "budget_eur": 500,
            "listeners": [{"id": "near", "x_m": 2, "y_m": 2}, {"id": "far", "x_m": 8, "y_m": 8}],
            "treatments": [{"id": "east", "x_m": 9, "y_m": 5, "cost_eur": 120}],
        }
        with patch.object(api, "_ready", return_value=True), patch.object(api, "_validate_verified_preset"):
            self.assertEqual(self.client.post("/api/compare", json=comparison).status_code, 409)
        self.executor.submit.assert_called_once()

    def test_no_allowed_placements_accepts_baseline_search(self):
        request = deepcopy(REQUEST)
        request["allowed_slot_ids"] = []
        response = self.client.post("/api/room3d/optimize", json=request)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.store.get(response.json()["job_id"])["request"]["allowed_slot_ids"], [])
        self.executor.submit.assert_called_once()

    def test_cloud_failure_does_not_make_up_result_and_can_resume(self):
        response = self.client.post("/api/room3d/optimize", json=REQUEST)
        job_id = response.json()["job_id"]
        with patch.object(api, "_run_optimization", side_effect=RuntimeError("SECRET credential or SDK response")):
            api._run_job3d(job_id, api.OptimizeRequest3D.model_validate(REQUEST))
        failed = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(failed["status"], "failed")
        self.assertNotIn("result", failed)
        self.assertNotIn("SECRET", failed["error"])
        self.assertEqual(self.client.get("/api/room3d/latest").status_code, 404)
        resumed = self.client.post(f"/api/jobs/{job_id}/resume")
        self.assertEqual(resumed.status_code, 202)
        self.assertEqual(resumed.json()["job_id"], job_id)
        self.assertEqual(self.store.get(job_id)["attempt"], 2)

    def test_engine_result_and_progress_are_persisted_without_transform(self):
        job_id = self.client.post("/api/room3d/optimize", json=REQUEST).json()["job_id"]
        result = {"dimension": 3, "frequency_hz": 125, "project_id": "project-1",
                  "project_url": "https://allsolve.quanscient.com/#/projects/project-1/model",
                  "evaluations": [{"status": "SUCCESS", "simulation_ids": ["cloud-baseline", "cloud-treatment"]}]}

        def run(request, progress):
            self.assertEqual(request, api.OptimizeRequest3D.model_validate(REQUEST).model_dump(mode="json"))
            progress({"stage": "searching", "message": "Evaluated first layout", "evaluated": 1,
                      "total": 2, "best_count": 1, "project_url": result["project_url"]})
            progress({"stage": "downloading", "message": "Reading next field", "latest_simulation_id": "cloud-treatment"})
            saved = self.store.get(job_id)["progress"]
            self.assertEqual(saved["stage"], "downloading")
            self.assertEqual(saved["message"], "Reading next field")
            self.assertEqual(saved["evaluated"], 1)
            self.assertEqual(saved["total"], 2)
            self.assertEqual(saved["best_count"], 1)
            self.assertEqual(saved["project_url"], result["project_url"])
            progress({"stage": "complete", "message": "Minimum object count found", "evaluated": 2})
            return result

        with patch.object(api, "_run_optimization", side_effect=run):
            api._run_job3d(job_id, api.OptimizeRequest3D.model_validate(REQUEST))
        completed = self.client.get("/api/room3d/latest").json()
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"], result)
        self.assertEqual(completed["progress"]["stage"], "completed")
        self.assertEqual(completed["progress"]["evaluated"], 2)
        self.assertEqual(completed["progress"]["total"], 2)
        self.assertEqual(completed["progress"]["best_count"], 1)
        recovered = JobStore(Path(self.directory.name))
        recovered.load()
        self.assertEqual(recovered.latest_completed("room3d")["result"], result)
        self.assertEqual(self.client.post(f"/api/jobs/{job_id}/resume").status_code, 409)

    def test_missing_cloud_provenance_is_failed_not_completed(self):
        job_id = self.client.post("/api/room3d/optimize", json=REQUEST).json()["job_id"]
        with patch.object(api, "_run_optimization", return_value={"dimension": 3, "frequency_hz": 125, "evaluations": []}):
            api._run_job3d(job_id, api.OptimizeRequest3D.model_validate(REQUEST))
        failed = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(failed["status"], "failed")
        self.assertNotIn("result", failed)

    def test_every_evaluation_requires_success_and_cloud_ids(self):
        base = {"dimension": 3, "frequency_hz": 125, "project_id": "project-1",
                "project_url": "https://allsolve.quanscient.com/#/projects/project-1/model",
                "evaluations": [{"status": "SUCCESS", "simulation_ids": ["cloud-baseline"]}]}
        for invalid in ({"status": "ERROR", "simulation_ids": ["cloud-treatment"]},
                        {"status": "SUCCESS", "simulation_ids": []}):
            result = deepcopy(base)
            result["evaluations"].append(invalid)
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                api._validate_result3d(result)

    def test_quietness_modes_and_legacy_absolute_requests(self):
        legacy = api.OptimizeRequest3D.model_validate(REQUEST)
        self.assertEqual(legacy.quietness_metric, "absolute_rms_pressure_pa")
        both = deepcopy(REQUEST)
        both["quiet_zones"][0]["target_reduction_db"] = 6
        relative = api.OptimizeRequest3D.model_validate(both)
        self.assertEqual(relative.quietness_metric, "relative_pressure_reduction_db")
        both["quietness_metric"] = "absolute_rms_pressure_pa"
        absolute = api.OptimizeRequest3D.model_validate(both)
        self.assertEqual(absolute.quietness_metric, "absolute_rms_pressure_pa")
        self.assertEqual(absolute.quiet_zones[0].target_reduction_db, 6)
        explicit_relative = deepcopy(REQUEST)
        explicit_relative["quietness_metric"] = "relative_pressure_reduction_db"
        with self.assertRaises(ValidationError):
            api.OptimizeRequest3D.model_validate(explicit_relative)
        reduction_only = deepcopy(REQUEST)
        reduction_only["quiet_zones"][0].pop("target_pressure_pa")
        reduction_only["quiet_zones"][0]["target_reduction_db"] = 0
        self.assertEqual(api.OptimizeRequest3D.model_validate(reduction_only).quietness_metric, "relative_pressure_reduction_db")
        reduction_only["quietness_metric"] = "absolute_rms_pressure_pa"
        with self.assertRaises(ValidationError):
            api.OptimizeRequest3D.model_validate(reduction_only)
        for invalid_target in (-1, 31):
            reduction_only["quietness_metric"] = "relative_pressure_reduction_db"
            reduction_only["quiet_zones"][0]["target_reduction_db"] = invalid_target
            with self.assertRaises(ValidationError):
                api.OptimizeRequest3D.model_validate(reduction_only)
        invalid_mode = deepcopy(both)
        invalid_mode["quietness_metric"] = "db_a"
        with self.assertRaises(ValidationError):
            api.OptimizeRequest3D.model_validate(invalid_mode)

    def test_preview_whitelist(self):
        self.assertEqual(self.client.get("/api/room3d/preview/unknown").status_code, 404)
        response = self.client.get("/api/room3d/preview/room")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")


if __name__ == "__main__":
    unittest.main()
