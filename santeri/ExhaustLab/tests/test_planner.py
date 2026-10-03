"""Physical coupling, inverse constraint behavior and immutable-source gates."""
import copy
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from ExhaustLab import planner


ANALYTIC = {"trusted": False, "status": "not_run", "cases": [], "errors": []}


class PlannerPhysicsTests(unittest.TestCase):
    def test_massflow_temperature_and_absolute_pressure_coupling(self):
        cold = planner.gas_properties(0.01, 26.85, 100)
        hot = planner.gas_properties(0.01, 326.85, 100)
        high_pressure = planner.gas_properties(0.01, 26.85, 200)
        self.assertAlmostEqual(hot["density_kg_m3"], cold["density_kg_m3"] / 2)
        self.assertAlmostEqual(hot["volume_flow_m3_s"], cold["volume_flow_m3_s"] * 2)
        self.assertAlmostEqual(high_pressure["volume_flow_m3_s"], cold["volume_flow_m3_s"] / 2)
        self.assertGreater(hot["viscosity_pa_s"], cold["viscosity_pa_s"])

    def test_darcy_scaling_and_units(self):
        # mu=2e-5Pa s, L=.2m, Q=.01m3/s, A=.01m2,k=2e-8m2 ->200Pa.
        pressure = planner.darcy_pressure_drop(2e-5, 0.2, 0.01, 0.01, 2e-8)
        self.assertAlmostEqual(pressure, 200)
        self.assertAlmostEqual(planner.darcy_pressure_drop(2e-5, 0.2, 0.02, 0.01, 2e-8), 2 * pressure)
        self.assertAlmostEqual(planner.darcy_pressure_drop(2e-5, 0.2, 0.01, 0.02, 2e-8), pressure / 2)

    def test_exact_thermal_crossing_and_mean(self):
        # T(t)=100-100exp(-t/10); it crosses50 at10ln2.
        duration = 20
        result = planner.thermal_step(0, 100, 0, 10, 0, 100, duration, 50)
        self.assertAlmostEqual(result["end_c"], 100 * (1 - math.exp(-2)))
        self.assertAlmostEqual(result["mean_c"], 100 - 50 * (1 - math.exp(-2)))
        self.assertAlmostEqual(result["hot_time_s"], duration - 10 * math.log(2))

    def test_cooling_threshold_crossing(self):
        result = planner.thermal_step(100, 0, 0, 10, 0, 100, 20, 50)
        self.assertAlmostEqual(result["hot_time_s"], 10 * math.log(2))
        self.assertLess(result["end_c"], 50)

    def test_insulation_reduces_conductance_and_heat_loss(self):
        bare = planner.lateral_conductance(0.16, 0.2, 0, 15, 0.045)
        covered = planner.lateral_conductance(0.16, 0.2, 0.02, 15, 0.045)
        self.assertLess(covered, bare)
        payload = planner.get_defaults()
        payload["search"].update(diameters_mm=[160], lengths_mm=[200], pipe_lengths_mm=[300], insulation_mm=[0, 20])
        candidates = planner.plan_design(payload, ANALYTIC)["candidates"]
        bare, covered = candidates
        self.assertLess(covered["cycle_heat_loss_kwh"], bare["cycle_heat_loss_kwh"])
        self.assertGreater(covered["peak_filter_temp_c"], bare["peak_filter_temp_c"])


class PlannerConstraintTests(unittest.TestCase):
    def setUp(self):
        self.payload = planner.get_defaults()

    def test_default_finite_grid_and_loaded_state(self):
        result = planner.plan_design(self.payload, ANALYTIC)
        self.assertEqual(result["summary"]["evaluated"], 81)
        self.assertEqual(result["status"], "feasible")
        self.assertEqual(result["mode"], "analytic_screening")
        candidate = result["recommended"]
        self.assertTrue(candidate["feasible"])
        self.assertGreater(candidate["worst_loaded_backpressure_kpa"], candidate["worst_clean_backpressure_kpa"])
        self.assertGreaterEqual(candidate["filter_volume_l"], self.payload["material"]["minimum_filter_volume_l"])
        self.assertEqual(candidate["specified_capture_pct"], self.payload["material"]["spec_capture_pct"])

    def test_no_fabricated_winner_when_capture_spec_cannot_meet_target(self):
        self.payload["constraints"]["target_capture_pct"] = 99
        result = planner.plan_design(self.payload, ANALYTIC)
        self.assertEqual(result["status"], "infeasible")
        self.assertIsNone(result["recommended"])
        self.assertFalse(result["pareto"])
        self.assertEqual(result["constraint_failures"][0], {"constraint": "capture_specification", "count": 81})

    def test_backpressure_constraint_forces_larger_geometry(self):
        self.payload["search"].update(pipe_lengths_mm=[100], insulation_mm=[0])
        initial = planner.plan_design(self.payload, ANALYTIC)
        self.payload["constraints"]["max_backpressure_kpa"] = 3
        limited = planner.plan_design(self.payload, ANALYTIC)
        self.assertGreater(limited["recommended"]["diameter_mm"], initial["recommended"]["diameter_mm"])
        self.assertLessEqual(limited["recommended"]["worst_loaded_backpressure_kpa"], 3)

    def test_small_envelope_reports_infeasibility(self):
        self.payload["constraints"]["max_outer_diameter_mm"] = 100
        result = planner.plan_design(self.payload, ANALYTIC)
        self.assertIsNone(result["recommended"])
        self.assertTrue(all(any(v["constraint"] == "outer_diameter" for v in c["violations"]) for c in result["candidates"]))

    def test_objective_is_best_member_of_feasible_grid(self):
        for objective, field in [("lowest_cost", "cost_eur"), ("smallest_volume", "package_volume_l"), ("lowest_backpressure", "worst_loaded_backpressure_kpa")]:
            self.payload["search"]["objective"] = objective
            result = planner.plan_design(self.payload, ANALYTIC)
            best = min(c[field] for c in result["candidates"] if c["feasible"])
            self.assertAlmostEqual(result["recommended"][field], best)

    def test_input_bounds_and_unknown_fields_rejected(self):
        for payload in ({"duty_cycle": []}, {"environment": {"pressure_kpa": 0}}, {"material": {"spec_capture_pct": float("nan")}}, {"mystery": 1}, []):
            with self.assertRaises(ValueError):
                planner.plan_design(payload, ANALYTIC)

    def test_missing_cloud_geometry_excluded_in_verified_mode(self):
        dataset = {"trusted": True, "status": "verified", "errors": [], "cases": [
            {"trusted": True, "case": "d120l200", "diameter_m": 0.12, "length_m": 0.2,
             "pressure_factor": 1.001, "project_id": "project123"}]}
        result = planner.plan_design(self.payload, dataset)
        self.assertEqual(result["mode"], "allsolve_verified_screening")
        self.assertEqual(result["recommended"]["diameter_mm"], 120)
        self.assertEqual(result["recommended"]["filter_length_mm"], 200)
        self.assertEqual(result["recommended"]["source"]["case"], "d120l200")
        self.assertEqual(len(result["summary"]["missing_cloud_geometries"]), 8)


class PlannerSourceGateTests(unittest.TestCase):
    def make_manifest(self, folder):
        state = {"case": "test", "diameter_m": 0.12, "length_m": 0.2,
                 "project_id": "test-project", "simulation_job_id": "test-job", "simulation_status": "JobStatusType.SUCCESS"}
        validation = {"passed": True, "pressure_factor": 1, "gates": {"pressure": True}}
        sources = [folder / name for name in ("state.json", "samples.json", "validation.json")]
        for source, value in zip(sources, (state, {"fixture_samples": 1}, validation)):
            source.write_text(json.dumps(value), encoding="utf-8")
        hashes = {str(source.relative_to(planner.ROOT)): hashlib.sha256(source.read_bytes()).hexdigest() for source in sources}
        mesh_file = folder / "mesh.json"
        mesh_file.write_text(json.dumps({"passed": True, "source_hashes": hashes}), encoding="utf-8")
        batch_file = folder / "batch.json"
        batch_file.write_text(json.dumps({"max_active_jobs": 1, "peak_active_jobs": 1, "requested_cases": ["test"]}), encoding="utf-8")
        def evidence(path):
            return {"evidence_path": str(path.relative_to(planner.ROOT)), "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        data = {"ready": True, "expected_geometry_count": 1,
                "mesh_verification": {"passed": True, **evidence(mesh_file)},
                "concurrency": {"max_active_jobs": 1, "peak_active_jobs": 1, "requested_geometry_count": 1, "verified_geometry_count": 1, **evidence(batch_file)},
                "cases": [{**state, "pressure_factor": 1, "validation": validation, "source_hashes": hashes}]}
        manifest = folder / "manifest.json"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        return manifest, data, sources, mesh_file, batch_file

    def test_malformed_manifests_are_unverified_instead_of_crashing(self):
        with tempfile.TemporaryDirectory(dir=planner.ROOT / "runs") as directory:
            manifest = Path(directory) / "manifest.json"
            for value in ([], {"cases": {}}, {"cases": ["broken"]}, {"cases": [{"validation": "broken", "source_hashes": ["broken"]}]}):
                manifest.write_text(json.dumps(value), encoding="utf-8")
                dataset = planner.load_cloud_dataset(manifest)
                self.assertFalse(dataset["trusted"])
                self.assertTrue(dataset["errors"])

    def test_replaced_export_invalidates_cloud_dataset(self):
        with tempfile.TemporaryDirectory(dir=planner.ROOT / "runs") as directory:
            folder = Path(directory)
            manifest, data, sources, mesh, batch = self.make_manifest(folder)
            trusted = planner.load_cloud_dataset(manifest)
            self.assertTrue(trusted["trusted"])
            sources[1].write_text("replacement", encoding="utf-8")
            untrusted = planner.load_cloud_dataset(manifest)
            self.assertFalse(untrusted["trusted"])
            self.assertTrue(any("hash mismatch" in error for error in untrusted["errors"]))
            result = planner.plan_design(cloud_dataset=untrusted)
            self.assertEqual(result["mode"], "analytic_screening")
            self.assertNotEqual(result["recommended"]["source"]["mode"], "allsolve_pressure_verified")

    def test_ready_count_and_case_headers_cannot_override_archived_evidence(self):
        with tempfile.TemporaryDirectory(dir=planner.ROOT / "runs") as directory:
            manifest, base, sources, mesh, batch = self.make_manifest(Path(directory))
            for mutate, fragment in [
                (lambda d: d.update(ready=False), "not declared ready"),
                (lambda d: d.update(expected_geometry_count=2), "geometry count"),
                (lambda d: d["cases"][0].update(pressure_factor=1.01), "archived validation"),
                (lambda d: d["cases"][0].update(diameter_m=0.13), "archived state"),
                (lambda d: d["concurrency"].update(peak_active_jobs=3), "archived evidence"),
            ]:
                data = copy.deepcopy(base)
                mutate(data)
                manifest.write_text(json.dumps(data), encoding="utf-8")
                dataset = planner.load_cloud_dataset(manifest)
                self.assertFalse(dataset["trusted"])
                self.assertTrue(any(fragment in error for error in dataset["errors"]), dataset["errors"])

    def test_replaced_mesh_and_batch_evidence_invalidate_study(self):
        for evidence_kind in ("mesh", "batch"):
            with tempfile.TemporaryDirectory(dir=planner.ROOT / "runs") as directory:
                manifest, base, sources, mesh, batch = self.make_manifest(Path(directory))
                evidence = mesh if evidence_kind == "mesh" else batch
                evidence.write_text("replacement", encoding="utf-8")
                dataset = planner.load_cloud_dataset(manifest)
                self.assertFalse(dataset["trusted"])
                self.assertTrue(any("source hash mismatch" in error for error in dataset["errors"]))

    def test_failed_validation_never_authorizes_cloud_factor(self):
        with tempfile.TemporaryDirectory(dir=planner.ROOT / "runs") as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps({"cases": [{"case": "failed", "diameter_m": 0.12, "length_m": 0.2,
                "pressure_factor": 1, "project_id": "p", "flow_job_id": "j", "validation": {"passed": False}, "source_hashes": {}}]}), encoding="utf-8")
            self.assertFalse(planner.load_cloud_dataset(manifest)["trusted"])


if __name__ == "__main__":
    unittest.main()
