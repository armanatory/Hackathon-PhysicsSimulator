"""Search bookkeeping tests with explicit synthetic fixtures; no cloud jobs."""
import copy
import math
import random
import unittest

from search import (REQUIRED_OUTPUTS, generate_candidates, make_points,
                    scalar_outputs, update_candidates, validate_outputs)


def request(count=2, samples=3):
    return {"candidate_count": count, "seed": 42, "film_thickness_nm": 100.0,
            "minimum_feature_nm": 50.0, "wavelength_min_nm": 900.0,
            "wavelength_max_nm": 1100.0, "wavelength_samples": samples,
            "geometry_bounds": {"period_nm": {"min": 450.0, "max": 550.0},
                                "fill_factor": {"min": 0.3, "max": 0.7},
                                "ridge_height_nm": {"min": 80.0, "max": 220.0}},
            "liquids": [{"label": "Water", "n": 1.33}, {"label": "Glycerol-water", "n": 1.38}]}


def outputs(point, reflectance=0.2):
    """Lossless scalar fixture with all identity and metadata fields explicit."""
    pin = 1e-15
    result = {name: 0.0 for name in REQUIRED_OUTPUTS}
    result.update({name: point[name] for name in
                   ("candidate_id", "input_index", "wavelength_nm", "n_liquid",
                    "period_nm", "fill_factor", "ridge_height_nm", "film_thickness_nm")})
    result.update(specified_incident_power_W=pin, entrance_forward_power_W=pin,
                  entrance_backward_power_W=pin*reflectance, exit_forward_power_W=pin*(1-reflectance),
                  reflectance=reflectance, transmittance=1-reflectance,
                  coherent_reflectance=reflectance, coherent_transmittance=1-reflectance,
                  incident_normalization_ratio=1.0, exterior_diffraction_cutoff_ratio=0.88,
                  wavelength_frequency_ratio=1.0, entrance_material_admittance_ratio=1.0,
                  exit_material_admittance_ratio=1.0, local_reflectance=reflectance,
                  local_transmittance=1-reflectance,
                  entrance_local_forward_power_W=pin, entrance_local_backward_power_W=pin*reflectance,
                  exit_local_forward_power_W=pin*(1-reflectance))
    for plane in ("entrance", "exit"):
        net = result[plane+"_forward_power_W"]-result[plane+"_backward_power_W"]
        result[plane+"_net_flux_W"] = net
        result[plane+"_poynting_flux_W"] = net
        result[plane+"_local_directional_flux_W"] = net
    return result


def rows_for(candidates, req, values=None):
    rows = []
    for point in make_points(candidates, req):
        value = 0.2 if values is None else values[(point["candidate_id"], point["input_index"], point["wavelength_nm"])]
        rows.append({**point, "outputs": outputs(point, value), "valid": True,
                     "error": None, "status": "completed", "stage": "coarse", "sweep_index": len(rows)})
    return rows


class CandidateGenerationTests(unittest.TestCase):
    def test_reproducible_private_rng_and_lhs_strata(self):
        req = request(count=24, samples=11)
        random.seed(671)
        before = random.getstate()
        a, b = generate_candidates(req), generate_candidates(req)
        self.assertEqual(random.getstate(), before)
        self.assertEqual(a, b)
        for name, bounds in req["geometry_bounds"].items():
            strata = [int(24*(candidate["geometry"][name]-bounds["min"])/(bounds["max"]-bounds["min"])) for candidate in a]
            self.assertEqual(sorted(strata), list(range(24)))
        for candidate in a:
            geometry = candidate["geometry"]
            self.assertGreaterEqual(geometry["width_nm"], 50)
            self.assertGreaterEqual(geometry["gap_nm"], 50)
            self.assertAlmostEqual(geometry["width_nm"]+geometry["gap_nm"], geometry["period_nm"])
            self.assertEqual(candidate["total_solves"], 22)
            self.assertIsNone(candidate["score"])
            self.assertFalse(candidate["valid"])
        changed = copy.deepcopy(req)
        changed["seed"] += 1
        self.assertNotEqual(a, generate_candidates(changed))

    def test_minimum_feature_failure_rejects_before_any_jobs(self):
        req = request()
        req["geometry_bounds"]["fill_factor"]["min"] = 0.05
        with self.assertRaisesRegex(ValueError, "minimum"):
            generate_candidates(req)

    def test_point_pair_order_and_explicit_refinement_grid(self):
        req = request()
        candidates = generate_candidates(req)
        points = make_points(candidates, req)
        self.assertEqual(len(points), 12)
        self.assertEqual([point["input_index"] for point in points], [0, 1]*6)
        self.assertEqual([point["wavelength_nm"] for point in points[:6]], [900, 900, 1000, 1000, 1100, 1100])
        finer = make_points(candidates[:1], req, wavelengths=[999, 1000, 1001])
        self.assertEqual(len(finer), 6)
        self.assertEqual(finer[0]["n_liquid"], 1.33)
        self.assertEqual(finer[1]["n_liquid"], 1.38)


class ScalarValidationTests(unittest.TestCase):
    def setUp(self):
        req = request()
        self.point = make_points(generate_candidates(req), req)[0]
        self.valid = outputs(self.point)

    def test_sdk_archive_and_flat_decoders(self):
        table = {"nostep": {name: [value] for name, value in self.valid.items()}}
        self.assertEqual(scalar_outputs(table), self.valid)
        self.assertEqual(scalar_outputs({"simulation_id": "fixture", "public_output_values": table}), self.valid)
        self.assertEqual(scalar_outputs(self.valid), self.valid)
        self.assertEqual(validate_outputs(self.valid), [])

    def test_malformed_and_nonfinite_outputs_cannot_pass(self):
        for malformed in ({"nostep": {"R": [0.1, 0.2]}}, {"R": True}, {"R": "0.1"}, {"nostep": None}):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                scalar_outputs(malformed)
        bad = dict(self.valid, transmittance=float("nan"))
        self.assertTrue(validate_outputs(scalar_outputs(bad)))
        bad = dict(self.valid)
        del bad["exit_material_admittance_ratio"]
        self.assertTrue(validate_outputs(bad))
        self.assertTrue(validate_outputs(dict(self.valid, entrance_forward_power_W=0)))

    def test_each_fixed_gate_rejects_bad_evidence(self):
        changes = [
            {"exit_forward_power_W": 0.75e-15},
            {"specified_incident_power_W": 0.97e-15},
            {"exit_backward_power_W": 0.002e-15},
            {"entrance_crosspolarized_power_W": 0.0002e-15},
            {"exit_crosspolarized_power_W": 0.0002e-15},
            {"exterior_diffraction_cutoff_ratio": 0.900002},
            {"entrance_material_admittance_ratio": 1.0000001},
            {"exit_material_admittance_ratio": 0.9999999},
            {"wavelength_frequency_ratio": 1.000001},
            {"reflectance": 0.21},
            {"entrance_poynting_flux_W": 0.806e-15,
             "entrance_local_forward_power_W": 1.006e-15,
             "entrance_local_directional_flux_W": 0.806e-15,
             "entrance_coherent_local_flux_difference_W": 0.006e-15},
        ]
        for changed in changes:
            with self.subTest(changed=changed):
                self.assertTrue(validate_outputs(dict(self.valid, **changed)))

    def test_equal_evanescent_local_forward_backward_excess_is_not_rejected_as_flux(self):
        # Reactive content contributes equal local forward/backward split power.
        # It leaves normal flux and coherent propagating R/T unchanged.
        changed = dict(self.valid)
        excess = 0.1e-15
        for plane in ("entrance", "exit"):
            changed[plane+"_local_forward_power_W"] += excess
            changed[plane+"_local_backward_power_W"] += excess
        local_pin = changed["entrance_local_forward_power_W"]
        changed["local_reflectance"] = changed["entrance_local_backward_power_W"]/local_pin
        changed["local_transmittance"] = changed["exit_local_forward_power_W"]/local_pin
        changed["local_energy_residual"] = 1-(changed["entrance_local_backward_power_W"]+changed["exit_local_forward_power_W"])/local_pin
        self.assertEqual(validate_outputs(changed), [])


class RankingTests(unittest.TestCase):
    def test_scores_only_complete_paired_common_wavelengths(self):
        req = request()
        candidates = generate_candidates(req)
        values = {(cid, index, wavelength): value for cid in (0, 1)
                  for wavelength, pair in [(900, (0.2, 0.25)), (1000, (0.5, 0.15)), (1100, (0.1, 0.3))]
                  for index, value in enumerate(pair)}
        rows = rows_for(candidates, req, values)
        update_candidates(candidates, req, rows[:8])
        self.assertTrue(candidates[0]["valid"])
        self.assertAlmostEqual(candidates[0]["score"], 0.35)
        self.assertEqual(candidates[0]["wavelength_nm"], 1000)
        self.assertEqual((candidates[0]["R_A"], candidates[0]["R_B"]), (0.5, 0.15))
        self.assertFalse(candidates[0]["verified"])
        self.assertIsNone(candidates[1]["score"])
        self.assertEqual(candidates[1]["completed_solves"], 2)
        self.assertEqual(candidates[1]["status"], "running")

    def test_invalid_failed_duplicate_mismatched_and_reference_rows_do_not_rank(self):
        req = request(count=1)
        for change in ("gate", "failure", "duplicate", "metadata", "reference", "grid"):
            candidates = generate_candidates(req)
            rows = rows_for(candidates, req)
            if change == "gate":
                rows[0]["outputs"]["incident_normalization_ratio"] = 1.03
            elif change == "failure":
                rows[0].update(valid=False, error="Cloud solve failed", outputs=None)
            elif change == "duplicate":
                rows.append(copy.deepcopy(rows[0]))
            elif change == "metadata":
                rows[0]["outputs"]["input_index"] = 1
            elif change == "reference":
                rows[0]["engine"] = "rcwa"
            else:
                rows[0]["wavelength_nm"] = 901
            with self.subTest(change=change):
                update_candidates(candidates, req, rows)
                self.assertFalse(candidates[0]["valid"])
                self.assertFalse(candidates[0]["verified"])
                self.assertIsNone(candidates[0]["score"])
                self.assertTrue(candidates[0]["error"])

    def test_empty_progress_and_repeat_updates_are_deterministic(self):
        req = request(count=1)
        candidates = generate_candidates(req)
        update_candidates(candidates, req, [])
        self.assertEqual(candidates[0]["status"], "queued")
        rows = rows_for(candidates, req)
        update_candidates(candidates, req, rows)
        snapshot = copy.deepcopy(candidates)
        update_candidates(candidates, req, list(reversed(rows)))
        self.assertEqual(candidates, snapshot)


if __name__ == "__main__":
    unittest.main()
