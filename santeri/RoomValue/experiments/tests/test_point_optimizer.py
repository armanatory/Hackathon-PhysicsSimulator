"""Pure listener-noise objective and cache-isolation tests; no cloud access.

Transfer functions below are explicitly synthetic test inputs. Production
search receives complex fields only from Solver.basis and never imports these.
"""
from __future__ import annotations

import itertools
import math
import sys
import unittest
from copy import deepcopy
from pathlib import Path

import numpy as np

CASE = Path(__file__).resolve().parents[2]
if str(CASE) not in sys.path:
    sys.path.insert(0, str(CASE))

from experiments.optimizer3d import (  # noqa: E402
    HERE,
    get_catalog,
    point_catalog,
    pressure_db,
    search_point,
    source_peak_strength,
)


def point_request(**changes):
    request = {
        "sources": [{"id": "first", "position_m": [1.5, 4.0, 1.4], "level_db": 80.0}],
        "listener_m": [2.5, 3.0, 1.2],
        "max_panels": 2,
        "allowed_slot_ids": ["c", "b", "a"],
    }
    request.update(changes)
    return request


class SyntheticTransfer:
    def __init__(self, values, listener):
        self.values = values
        self.listener = listener
        self.calls = []

    def __call__(self, source, slots, queries):
        np.testing.assert_allclose(queries, [self.listener])
        self.calls.append((source, slots))
        return np.asarray([self.values[slots]], dtype=complex), f"test-only-{source}-{slots}"


class PointObjectiveTests(unittest.TestCase):
    catalog = {"assumptions": ["Synthetic transfer functions used only in this test."]}

    def test_sphere_level_conversion_uses_rms_reference_and_peak_basis(self):
        # 80 dB re 20 microPa is 0.2 Pa RMS. A peak-normalized transfer needs
        # sqrt(2) times that pressure, otherwise every result is 3.01 dB low.
        self.assertAlmostEqual(source_peak_strength(80), math.sqrt(2)*0.2)
        self.assertAlmostEqual(pressure_db(0.2), 80.0)
        defaults = get_catalog()["point_defaults"]
        self.assertAlmostEqual(source_peak_strength(defaults["sources"][0]["level_db"]), 1.0)

    def test_twenty_db_source_change_multiplies_pressure_by_ten(self):
        results = []
        for level in (60.0, 80.0):
            request = point_request(allowed_slot_ids=["a"], max_panels=1)
            request["sources"][0]["level_db"] = level
            provider = SyntheticTransfer({(): 1, ("a",): 0.1}, request["listener_m"])
            results.append(search_point(request, provider, lambda _: None, self.catalog))
        lower, higher = results
        for key in ("baseline", "optimal_layout"):
            self.assertAlmostEqual(higher[key]["pressure_rms_pa"], 10*lower[key]["pressure_rms_pa"])
            self.assertAlmostEqual(higher[key]["noise_db"]-lower[key]["noise_db"], 20)
        self.assertAlmostEqual(lower["baseline"]["noise_db"], 60)
        self.assertAlmostEqual(higher["baseline"]["noise_db"], 80)
        self.assertAlmostEqual(lower["optimal_layout"]["reduction_db"], 20)
        self.assertAlmostEqual(higher["optimal_layout"]["reduction_db"], 20)

    def test_two_sources_add_incoherent_power_despite_opposite_complex_phase(self):
        for second_level in (80.0, 70.0):
            with self.subTest(second_level=second_level):
                request = point_request(
                    sources=[{"id": "first", "position_m": [1.5, 4, 1.4], "level_db": 80},
                             {"id": "second", "position_m": [3.5, 2, 1.0], "level_db": second_level}],
                    allowed_slot_ids=[], max_panels=0,
                )
                calls = []

                def provider(source, slots, queries):
                    calls.append((source, slots))
                    # Equal-level coherent sources would cancel here. The
                    # documented independent-source model must retain power.
                    value = 1 if source == "first" else -1
                    return np.asarray([value], dtype=complex), f"test-only-{source}"

                result = search_point(request, provider, lambda _: None, self.catalog)
                first_pressure = 20e-6*10**(80/20)
                second_pressure = 20e-6*10**(second_level/20)
                expected_pressure = math.hypot(first_pressure, second_pressure)
                expected_noise = 10*math.log10(10**(80/10)+10**(second_level/10))
                self.assertAlmostEqual(result["baseline"]["pressure_rms_pa"], expected_pressure)
                self.assertAlmostEqual(result["baseline"]["noise_db"], expected_noise)
                self.assertGreater(result["baseline"]["pressure_rms_pa"], first_pressure)
                self.assertEqual(calls, [("first", ()), ("second", ())])
                self.assertEqual(result["search"]["source_combination"], "incoherent_power_sum")

    def test_all_subsets_are_evaluated_even_after_an_improving_layout(self):
        request = point_request(max_panels=3)
        provider = SyntheticTransfer(
            {(): 1, ("a",): 0.3, ("b",): 0.2, ("c",): 0.25,
             ("a", "b"): 0.15, ("a", "c"): 0.12, ("b", "c"): 0.14,
             ("a", "b", "c"): 0.01}, request["listener_m"],
        )
        progress = []
        result = search_point(request, provider, progress.append, self.catalog)
        expected_subsets = [slots for count in range(4)
                            for slots in itertools.combinations(["a", "b", "c"], count)]
        self.assertEqual([slots for _, slots in provider.calls], expected_subsets)
        self.assertEqual(result["search"]["evaluated_layouts"], 8)
        self.assertEqual(result["search"]["total_layouts"], 8)
        self.assertEqual(progress[-1]["evaluated"], 8)
        self.assertEqual(result["optimal_layout"]["slot_ids"], ["a", "b", "c"])
        self.assertAlmostEqual(result["optimal_layout"]["pressure_rms_pa"], 0.002)
        self.assertAlmostEqual(result["optimal_layout"]["noise_db"], 40)
        self.assertAlmostEqual(result["optimal_layout"]["reduction_db"], 40)
        self.assertEqual(result["objective"], "minimize_listener_noise")
        self.assertEqual(result["noise_metric"], "normalized_spl_db")
        self.assertTrue(all(e["status"] == "SUCCESS" for e in result["evaluations"]))

    def test_best_layout_can_use_fewer_panels_than_the_limit(self):
        request = point_request(max_panels=2)
        provider = SyntheticTransfer(
            {(): 1, ("a",): 0.2, ("b",): 0.5, ("c",): 0.6,
             ("a", "b"): 0.4, ("a", "c"): 0.3, ("b", "c"): 0.7}, request["listener_m"],
        )
        result = search_point(request, provider, lambda _: None, self.catalog)
        self.assertEqual(result["optimal_layout"]["slot_ids"], ["a"])
        self.assertEqual(result["optimal_layout"]["object_count"], 1)
        self.assertEqual(result["search"]["evaluated_layouts"], 7)
        self.assertTrue(any(len(slots) == 2 for _, slots in provider.calls))

    def test_harmful_panels_select_untreated_room(self):
        request = point_request(allowed_slot_ids=["a", "b"], max_panels=2)
        provider = SyntheticTransfer({(): 1, ("a",): 2, ("b",): 3, ("a", "b"): 4}, request["listener_m"])
        result = search_point(request, provider, lambda _: None, self.catalog)
        self.assertEqual(result["optimal_layout"]["slot_ids"], [])
        self.assertEqual(result["optimal_layout"]["object_count"], 0)
        self.assertEqual(result["optimal_layout"]["reduction_db"], 0)
        self.assertEqual(result["optimal_layout"], result["baseline"])
        self.assertEqual(len(result["evaluations"]), 4)

    def test_exact_pressure_tie_prefers_fewer_panels(self):
        request = point_request(allowed_slot_ids=["a", "b"], max_panels=2)
        provider = SyntheticTransfer({(): 1, ("a",): 0.5, ("b",): 0.7, ("a", "b"): 0.5}, request["listener_m"])
        result = search_point(request, provider, lambda _: None, self.catalog)
        self.assertEqual(result["optimal_layout"]["slot_ids"], ["a"])
        self.assertEqual(result["evaluations"][1]["pressure_rms_pa"], result["evaluations"][3]["pressure_rms_pa"])

    def test_zero_limit_or_no_available_positions_evaluates_only_baseline(self):
        for limit, slots in ((0, ["a", "b"]), (6, [])):
            with self.subTest(limit=limit, slots=slots):
                request = point_request(max_panels=limit, allowed_slot_ids=slots)
                provider = SyntheticTransfer({(): 1-2j}, request["listener_m"])
                result = search_point(request, provider, lambda _: None, self.catalog)
                self.assertEqual(result["optimal_layout"]["object_count"], 0)
                self.assertEqual(result["search"]["total_layouts"], 1)
                self.assertEqual(provider.calls, [("first", ())])
                self.assertAlmostEqual(result["baseline"]["pressure_rms_pa"], 0.2*math.sqrt(5))


class SourceProfileTests(unittest.TestCase):
    def test_canonical_selected_subset_reuses_original_air_partition_cache(self):
        catalog = get_catalog()
        request = deepcopy(catalog["point_defaults"])
        request["sources"].append({"id": catalog["sources"][1]["id"],
                                  "position_m": catalog["sources"][1]["position_m"], "level_db": 70})
        profile, cache = point_catalog(request, catalog)
        self.assertEqual(cache, HERE)
        self.assertEqual(profile["sources"], catalog["sources"])
        self.assertIsNot(profile["sources"], catalog["sources"])

    def test_moved_source_isolated_and_original_catalog_unchanged(self):
        catalog = get_catalog()
        original = deepcopy(catalog)
        request = deepcopy(catalog["point_defaults"])
        request["sources"][0]["position_m"][0] += 0.25
        profile, cache = point_catalog(request, catalog)
        self.assertNotEqual(cache, HERE)
        self.assertEqual(cache.parent, HERE / "scenarios")
        self.assertEqual(len(profile["sources"]), len(request["sources"]))
        self.assertEqual(profile["sources"][0]["position_m"], request["sources"][0]["position_m"])
        self.assertEqual(catalog, original)
        profile["sources"][0]["position_m"][0] += 0.1
        self.assertEqual(catalog, original)
        self.assertNotEqual(profile["sources"][0]["position_m"], request["sources"][0]["position_m"])

    def test_cache_geometry_depends_on_positions_but_not_levels_listener_or_cap(self):
        catalog = get_catalog()
        request = deepcopy(catalog["point_defaults"])
        request["sources"][0]["position_m"][0] += 0.25
        _, first_cache = point_catalog(request, catalog)
        revised = deepcopy(request)
        revised["sources"][0]["level_db"] += 10
        revised["listener_m"][0] += 0.2
        revised["max_panels"] = 3
        revised["allowed_slot_ids"] = []
        _, same_cache = point_catalog(revised, catalog)
        self.assertEqual(first_cache, same_cache)
        revised["sources"][0]["position_m"][0] += 0.1
        _, other_cache = point_catalog(revised, catalog)
        self.assertNotEqual(first_cache, other_cache)

    def test_unknown_source_id_cannot_create_a_custom_cache(self):
        catalog = get_catalog()
        request = deepcopy(catalog["point_defaults"])
        request["sources"][0]["id"] = "../../unsafe-path"
        with self.assertRaisesRegex(ValueError, "dataset catalog"):
            point_catalog(request, catalog)


if __name__ == "__main__":
    unittest.main()
