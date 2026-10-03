"""In-memory export-contract fixtures only; never create fake harvested runs."""

import copy
import unittest

import numpy as np

from ExhaustLab.analyze_study import extract_case, field_diagnostics, require_field_validation


def validation_fixture():
    shape = (2, 3, 2)
    axes = (np.array([0, 0.06]), np.array([0, 0.003, 0.006]), np.array([0, 0.02]))
    xx, yy, zz = np.meshgrid(*axes, indexing="ij")
    points = np.stack((xx, yy, zz), axis=-1)
    velocity = np.zeros(shape + (3,))
    velocity[..., 0] = 0.01
    electric = np.zeros_like(velocity)
    electric[..., 1] = -200 / 0.006
    state = {
        "case": "in_memory_analytic_validation_fixture",
        "project_id": "test_only", "project_url": "https://example.invalid/test-only",
        "mesh_id": "test_only", "mesh_job_id": "test_only",
        "flow_simulation_id": "test_only", "flow_job_id": "test_only",
        "electric_simulation_id": "test_only", "electric_job_id": "test_only",
        "mesh_status": "JobStatusType.SUCCESS", "flow_status": "JobStatusType.SUCCESS",
        "electric_status": "JobStatusType.SUCCESS", "geometry_built": True,
        "grid_shape": list(shape), "length_m": 0.06, "gap_m": 0.006, "span_m": 0.02,
        "mu_pa_s": 1.81e-5, "rho_kg_m3": 1.2, "flow_m3_s": 0.01 * 0.006 * 0.02,
        "voltage_v": 200, "reference": {"pressure_drop_pa": 0.06},
    }
    common = {"sample_xyz_m": points.ravel().tolist(), "gas_volume_m3": [0.06 * 0.006 * 0.02]}
    flow = {**common, "sample_vector": velocity.ravel().tolist(), "sample_scalar": (0.06 - xx).ravel().tolist()}
    electric_data = {**common, "sample_vector": electric.ravel().tolist(), "sample_scalar": (200 * yy / 0.006).ravel().tolist()}
    return state, flow, electric_data


class ExportContractTests(unittest.TestCase):
    def test_failed_stale_or_partially_failed_benchmarks_block_processing(self):
        state, _, _ = validation_fixture()
        hashes = {name: "in_memory_test_hash" for name in ("state.json", "flow_samples.json", "electric_samples.json")}
        identifiers = ("project_id", "mesh_id", "mesh_job_id", "flow_simulation_id", "flow_job_id", "electric_simulation_id", "electric_job_id")
        validation = {
            "passed": True, "all_field_benchmark_checks_passed": True,
            "source": {**{key: state[key] for key in identifiers}, "file_sha256": hashes.copy()},
            "flow": {"status": "pass", "checks": {"continuity": {"pass": True}}},
            "electric": {"status": "pass", "checks": {"uniform_field": {"pass": True}}},
        }
        require_field_validation(validation, state, hashes)
        bad = copy.deepcopy(validation)
        bad["passed"] = False
        with self.assertRaisesRegex(ValueError, "processing is disabled"):
            require_field_validation(bad, state, hashes)
        bad = copy.deepcopy(validation)
        bad["source"]["file_sha256"]["flow_samples.json"] = "stale"
        with self.assertRaisesRegex(ValueError, "hashes do not match"):
            require_field_validation(bad, state, hashes)
        bad = copy.deepcopy(validation)
        bad["flow"]["checks"]["continuity"]["pass"] = False
        with self.assertRaisesRegex(ValueError, "not all passed"):
            require_field_validation(bad, state, hashes)

    def test_scalar_and_grid_extraction_and_pressure_diagnostic(self):
        state, flow, electric = validation_fixture()
        channel, sampler, pressure, potential, _ = extract_case(state, flow, electric)
        self.assertEqual(sampler.velocity_m_s.shape, (2, 3, 2, 3))
        self.assertEqual(pressure.shape, (2, 3, 2))
        diagnostic = field_diagnostics(state, channel, sampler, pressure, potential)
        self.assertAlmostEqual(diagnostic["pressure_drop_pa"], 0.06)
        self.assertAlmostEqual(diagnostic["export_grid_inlet_flux_m3_s"], state["flow_m3_s"])
        self.assertAlmostEqual(diagnostic["electric_vector_relative_max_error_uniform_reference"], 0)
        self.assertAlmostEqual(diagnostic["potential_relative_max_error_linear_reference"], 0)

    def test_incomplete_jobs_and_changed_registration_rejected(self):
        state, flow, electric = validation_fixture()
        state["flow_status"] = "JobStatusType.RUNNING"
        with self.assertRaisesRegex(ValueError, "not a completed successful job"):
            extract_case(state, flow, electric)
        state["flow_status"] = "JobStatusType.SUCCESS"
        electric["sample_xyz_m"] = electric["sample_xyz_m"].copy()
        electric["sample_xyz_m"][0] += 1e-8
        with self.assertRaisesRegex(ValueError, "do not match exactly"):
            extract_case(state, flow, electric)

    def test_missing_samples_tensor_order_and_volume_rejected(self):
        state, flow, electric = validation_fixture()
        invalid = copy.deepcopy(flow)
        invalid["sample_vector"][4] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite flat entries"):
            extract_case(state, invalid, electric)
        invalid = copy.deepcopy(flow)
        invalid["sample_xyz_m"][0], invalid["sample_xyz_m"][3] = 0.01, 0.02
        invalid_e = copy.deepcopy(electric)
        invalid_e["sample_xyz_m"] = invalid["sample_xyz_m"].copy()
        with self.assertRaisesRegex(ValueError, "tensor-grid order"):
            extract_case(state, invalid, invalid_e)
        invalid = copy.deepcopy(flow)
        invalid["gas_volume_m3"][0] *= 2
        with self.assertRaisesRegex(ValueError, "gas-volume output disagrees"):
            extract_case(state, invalid, electric)


if __name__ == "__main__":
    unittest.main()
