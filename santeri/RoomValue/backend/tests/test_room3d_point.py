"""Editable 3D source/listener coordinates and minimum-noise API contract."""

from __future__ import annotations

import math
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import app as api
from backend.job_store import JobStore
from backend.tests.test_room3d_api import CATALOG, REQUEST


POINT_CATALOG = deepcopy(CATALOG)
POINT_CATALOG["sources"].extend([
    {"id": "src2", "position_m": [3.5, 4.6, 1.4]},
    {"id": "src3", "position_m": [3.5, 1.6, 1.4]},
])
POINT_REQUEST = {
    "sources": [{"id": "src1", "position_m": [1.9, 4.5, 1.4], "level_db": 80}],
    "listener_m": [2.8, 3.4, 1.2],
    "max_panels": 3,
    "allowed_slot_ids": ["east_a"],
}
POINT_RESULT = {
    "objective": "minimize_listener_noise", "dimension": 3, "frequency_hz": 125,
    "noise_metric": "normalized_spl_db", "project_id": "point-project",
    "project_url": "https://allsolve.quanscient.com/#/projects/point-project/model",
    "baseline": {"pressure_rms_pa": .02, "noise_db": 60, "simulation_ids": ["baseline-job"]},
    "optimal_layout": {"slot_ids": ["east_a"], "object_count": 1, "pressure_rms_pa": .01,
                       "noise_db": 53.9794, "reduction_db": 6.0206,
                       "simulation_ids": ["panel-job"], "status": "SUCCESS"},
    "evaluations": [
        {"slot_ids": [], "object_count": 0, "pressure_rms_pa": .02, "noise_db": 60,
         "reduction_db": 0, "simulation_ids": ["baseline-job"], "status": "SUCCESS"},
        {"slot_ids": ["east_a"], "object_count": 1, "pressure_rms_pa": .01, "noise_db": 53.9794,
         "reduction_db": 6.0206, "simulation_ids": ["panel-job"], "status": "SUCCESS"},
    ],
}


class PointMinimizeApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.directory.name))
        self.executor = Mock()
        self.patches = [
            patch.object(api, "_store", self.store),
            patch.object(api, "_executor", self.executor),
            patch.object(api, "_ready3d", return_value=True),
            patch.object(api, "_get_catalog", return_value=deepcopy(POINT_CATALOG)),
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

    def test_editable_xyz_request_without_budget_uses_point_worker_and_busy_guard(self):
        request = deepcopy(POINT_REQUEST)
        request["sources"][0]["position_m"] = [2, 2.5, 1.2]
        accepted = self.client.post("/api/room3d/minimize", json=request)
        self.assertEqual(accepted.status_code, 202)
        job_id = accepted.json()["job_id"]
        saved = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(saved["kind"], "room3d_point")
        self.assertEqual(saved["request"]["sources"][0]["position_m"], [2, 2.5, 1.2])
        self.assertNotIn("budget_eur", saved["request"])
        self.assertIs(self.executor.submit.call_args.args[0], api._run_point_job)
        self.assertEqual(self.client.post("/api/room3d/optimize", json=REQUEST).status_code, 409)
        self.assertEqual(self.client.post("/api/room3d/minimize", json=request).status_code, 409)

    def test_rejects_invalid_coordinates_and_collisions(self):
        variants = []
        for position in ([.08, 4.5, 1.4], [6, 4.5, 1.4], [1.9, 4.5, 2.3]):
            request = deepcopy(POINT_REQUEST)
            request["sources"][0]["position_m"] = position
            variants.append(request)
        wall_listener = deepcopy(POINT_REQUEST)
        wall_listener["listener_m"] = [0, 3.4, 1.2]
        variants.append(wall_listener)
        inside_source = deepcopy(POINT_REQUEST)
        inside_source["listener_m"] = [1.9, 4.5, 1.4]
        variants.append(inside_source)
        touching_sources = deepcopy(POINT_REQUEST)
        touching_sources["sources"].append({"id": "src2", "position_m": [2.05, 4.5, 1.4], "level_db": 75})
        variants.append(touching_sources)
        inside_panel = deepcopy(POINT_REQUEST)
        inside_panel["listener_m"] = [5.6, 3, 1.2]
        variants.append(inside_panel)
        touching_panel = deepcopy(POINT_REQUEST)
        touching_panel["sources"][0]["position_m"] = [5.45, 3, 1.2]
        variants.append(touching_panel)
        unknown_source = deepcopy(POINT_REQUEST)
        unknown_source["sources"][0]["id"] = "unknown"
        variants.append(unknown_source)
        for request in variants:
            with self.subTest(request=request):
                self.assertEqual(self.client.post("/api/room3d/minimize", json=request).status_code, 422)
        self.executor.submit.assert_not_called()

    def test_no_allowed_panels_permits_point_and_source_in_excluded_panel_volume(self):
        request = deepcopy(POINT_REQUEST)
        request.update(allowed_slot_ids=[], max_panels=0, listener_m=[5.6, 3, 1.2])
        request["sources"][0]["position_m"] = [5.45, 3, 1.2]
        self.assertEqual(self.client.post("/api/room3d/minimize", json=request).status_code, 202)

    def test_db_limits_count_and_nonfinite_numbers(self):
        for level in (0, 120):
            request = deepcopy(POINT_REQUEST)
            request["sources"][0]["level_db"] = level
            self.assertEqual(api.PointPlan3D.model_validate(request).sources[0].level_db, level)
        for level in (-1, 121, math.inf, math.nan):
            request = deepcopy(POINT_REQUEST)
            request["sources"][0]["level_db"] = level
            with self.assertRaises(ValidationError):
                api.PointPlan3D.model_validate(request)
        for count in (-1, 7, 1.5, True):
            request = deepcopy(POINT_REQUEST)
            request["max_panels"] = count
            self.assertEqual(self.client.post("/api/room3d/minimize", json=request).status_code, 422)
        for field in ("listener_m", "position_m"):
            request = deepcopy(POINT_REQUEST)
            if field == "listener_m":
                request[field][0] = math.inf
            else:
                request["sources"][0][field][0] = math.nan
            with self.assertRaises(ValidationError):
                api.PointPlan3D.model_validate(request)
        for obsolete_field in ("budget_eur", "object_cost_eur", "quiet_zones"):
            request = deepcopy(POINT_REQUEST)
            request[obsolete_field] = 100
            self.assertEqual(self.client.post("/api/room3d/minimize", json=request).status_code, 422)

    def test_completed_point_result_is_persisted_and_latest_is_separate(self):
        self.assertEqual(self.client.get("/api/room3d/minimize/latest").status_code, 404)
        job_id = self.client.post("/api/room3d/minimize", json=POINT_REQUEST).json()["job_id"]

        def run(request, progress):
            self.assertEqual(request, POINT_REQUEST)
            progress({"stage": "complete", "evaluated": 2, "total": 2})
            return deepcopy(POINT_RESULT)

        with patch.object(api, "_run_point_optimization", side_effect=run):
            api._run_point_job(job_id, api.PointPlan3D.model_validate(POINT_REQUEST))
        completed = self.client.get("/api/room3d/minimize/latest").json()
        self.assertEqual(completed["kind"], "room3d_point")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"], POINT_RESULT)
        self.assertEqual(completed["progress"]["evaluated"], 2)
        self.assertEqual(self.client.get("/api/room3d/latest").status_code, 404)
        recovered = JobStore(Path(self.directory.name))
        recovered.load()
        self.assertEqual(recovered.latest_completed("room3d_point")["result"], POINT_RESULT)

    def test_interrupted_point_job_uses_generic_resume_with_same_request(self):
        job_id = self.client.post("/api/room3d/minimize", json=POINT_REQUEST).json()["job_id"]
        self.store.update(job_id, status="interrupted")
        api._active_job = None
        resumed = self.client.post(f"/api/jobs/{job_id}/resume")
        self.assertEqual(resumed.status_code, 202)
        self.assertEqual(resumed.json()["job_id"], job_id)
        self.assertIs(self.executor.submit.call_args.args[0], api._run_point_job)
        self.assertEqual(self.store.get(job_id)["request"], POINT_REQUEST)

    def test_point_provenance_rejects_missing_baseline_ids_and_nonfinite_metrics(self):
        variants = []
        missing_baseline = deepcopy(POINT_RESULT)
        missing_baseline["baseline"]["simulation_ids"] = []
        variants.append(missing_baseline)
        nonfinite = deepcopy(POINT_RESULT)
        nonfinite["evaluations"][0]["noise_db"] = math.nan
        variants.append(nonfinite)
        missing_optimum = deepcopy(POINT_RESULT)
        missing_optimum["optimal_layout"]["status"] = "ERROR"
        variants.append(missing_optimum)
        for result in variants:
            with self.assertRaises(ValueError):
                api._validate_point_result(result)


if __name__ == "__main__":
    unittest.main()
