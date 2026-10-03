"""Pure numerical/search tests; no SDK client, cloud job, or production fake field.

The synthetic provider below supplies explicitly prescribed RMS values only to
exercise the discrete search decision. Production uses Solver.basis and cached
complex Allsolve fields; this test provider is never available to the server.
"""
from __future__ import annotations

import math
import itertools
import sys
import unittest
from pathlib import Path

import numpy as np

CASE = Path(__file__).resolve().parents[2]
if str(CASE) not in sys.path:
    sys.path.insert(0, str(CASE))

from experiments.optimizer3d import (  # noqa: E402
    EDGE_PAIRS,
    FieldMesh,
    affordable_layouts,
    evaluate_layout,
    get_catalog,
    model_config,
    quietness_metric,
    rms_pressure,
    search,
    zone_points,
)


def quadratic(values):
    """A full quadratic polynomial, including all mixed 3D terms."""
    x, y, z = np.asarray(values).T
    return (2.3 + 0.7*x - 1.1*y + 0.4*z + 1.9*x*x - 0.8*y*y
            + 0.6*z*z + 0.3*x*y - 1.2*x*z + 0.9*y*z)


def tetra_mesh(vertices):
    vertices = np.asarray(vertices, dtype=float)
    nodes = np.concatenate((vertices, [(vertices[a]+vertices[b])/2 for a, b in EDGE_PAIRS]))
    return FieldMesh(nodes, np.arange(10, dtype=np.int64)[None, :])


def request_for_search(**changes):
    request = {
        "sources": [{"id": "source", "strength": 1.0}],
        "quiet_zones": [{"id": "reading", "center_m": [2.0, 2.0, 1.0],
                         "size_m": [0.4, 0.6], "target_pressure_pa": 1.0}],
        "budget_eur": 360.0,
        "max_objects": 3,
        "allowed_slot_ids": ["c", "a", "b"],
        "object_cost_eur": 120.0,
    }
    request.update(changes)
    return request


class PrescribedRmsBasis:
    """Transparent test stub: each prescribed RMS is converted to peak H."""

    def __init__(self, pressures):
        self.pressures = pressures
        self.calls = []

    def __call__(self, source_id, slots, queries):
        self.calls.append((source_id, slots))
        self.test_queries = queries
        rms = self.pressures[slots]
        values = np.full(len(queries), rms*math.sqrt(2), dtype=complex)
        return values, f"test-only-{source_id}-{'-'.join(slots) or 'baseline'}"


class FieldInterpolationTests(unittest.TestCase):
    def test_exact_full_quadratic_on_skew_tetrahedron(self):
        # Non-orthogonal, translated geometry detects a transposed inverse and
        # mixed-term or tetrahedral edge-node ordering errors.
        vertices = np.array([[1.2, -0.5, 2.0], [3.1, 0.4, 2.2],
                             [1.8, 2.3, 2.6], [0.9, 0.3, 4.4]])
        mesh = tetra_mesh(vertices)
        barycentric = np.random.default_rng(143).dirichlet(np.ones(4), size=120)
        queries = barycentric @ vertices
        locations = mesh.locate(queries)
        nodal = quadratic(mesh.points)
        np.testing.assert_allclose(mesh.sample(nodal, locations), quadratic(queries),
                                   rtol=2e-13, atol=2e-13)
        # Sampling must preserve complex phase; absolute value is taken only
        # after real/imaginary interpolation in the pressure combination.
        imaginary = quadratic(mesh.points[:, [2, 0, 1]])
        actual = mesh.sample(nodal+1j*imaginary, locations)
        expected = quadratic(queries)+1j*quadratic(queries[:, [2, 0, 1]])
        np.testing.assert_allclose(actual, expected, rtol=2e-13, atol=2e-13)

    def test_outside_tetrahedron_is_rejected_even_inside_bounding_box(self):
        mesh = tetra_mesh(np.eye(4, 3, k=-1))
        # These coordinates lie in the unit box but outside x+y+z <= 1.
        with self.assertRaisesRegex(ValueError, "outside solved 3D field"):
            mesh.locate([[0.5, 0.5, 0.5]])
        with self.assertRaisesRegex(ValueError, "outside solved 3D field"):
            mesh.locate([[1.2, 0.0, 0.0]])

    def test_curved_or_reordered_edge_nodes_are_rejected(self):
        mesh = tetra_mesh(np.eye(4, 3, k=-1))
        changed = mesh.points.copy()
        changed[4, 2] += 0.01
        with self.assertRaisesRegex(ValueError, "curved geometry or tetrahedron ordering"):
            FieldMesh(changed, mesh.cells)
        reordered = mesh.cells.copy()
        reordered[0, [4, 5]] = reordered[0, [5, 4]]
        with self.assertRaisesRegex(ValueError, "curved geometry or tetrahedron ordering"):
            FieldMesh(mesh.points, reordered)


class PressureAndAreaTests(unittest.TestCase):
    def test_incoherent_power_does_not_phase_cancel_and_strength_scales(self):
        first = np.array([1+1j, 2-3j, -4j])
        second = -first
        strengths = [0.5, 2.0]
        expected = np.abs(first)*math.sqrt((0.5**2+2.0**2)/2)
        actual = rms_pressure([first, second], strengths)
        np.testing.assert_allclose(actual, expected)
        self.assertTrue(np.all(actual > 0))
        np.testing.assert_allclose(rms_pressure([first, second], [1.0, 4.0]), 2*actual)
        np.testing.assert_allclose(rms_pressure([first, 1j*second], strengths), actual)

    def test_area_ceiling_checks_worst_sample_and_reports_its_position(self):
        zone = {"id": "quiet", "center_m": [2.0, 3.0, 1.4],
                "size_m": [0.8, 0.6], "target_pressure_pa": 0.5}
        queries = zone_points(zone)
        self.assertEqual(queries.shape, (81, 3))
        np.testing.assert_allclose(queries.min(axis=0), [1.6, 2.7, 1.4])
        np.testing.assert_allclose(queries.max(axis=0), [2.4, 3.3, 1.4])
        pressure = np.full(81, 0.2)
        pressure[23] = 0.75
        baseline = np.ones(81)
        baseline[67] = 2.0
        evaluation = evaluate_layout(("a",), pressure, baseline, [zone], queries, 120, ["test-only"])
        self.assertFalse(evaluation["feasible"])
        self.assertLess(pressure.mean(), zone["target_pressure_pa"])
        result = evaluation["zones"][0]
        self.assertFalse(result["met_target"])
        self.assertEqual(result["treated_peak_pa"], 0.75)
        self.assertEqual(result["baseline_peak_pa"], 2.0)
        self.assertEqual(result["worst_point_m"], queries[23].tolist())
        self.assertAlmostEqual(result["reduction_db"], 20*math.log10(2/0.75))

    def test_relative_constraint_compares_area_maxima_at_different_points(self):
        zone = {"id": "quiet", "center_m": [2, 3, 1.4],
                "size_m": [0.8, 0.6], "target_reduction_db": 6}
        queries = zone_points(zone)
        baseline = np.full(81, 0.001)
        baseline[67] = 2.0
        pressure = np.full(81, 0.2)
        pressure[23] = 0.5
        # Pressure at the treated worst point increased 500 times versus its
        # own baseline. The selected area maximum still falls by 12.04 dB;
        # this mode intentionally constrains that area statistic.
        self.assertGreater(pressure[23]/baseline[23], 100)
        evaluation = evaluate_layout(("a",), pressure, baseline, [zone], queries,
                                     120, ["test-only"], "relative_pressure_reduction_db")
        result = evaluation["zones"][0]
        self.assertTrue(evaluation["feasible"])
        self.assertTrue(result["met_target"])
        self.assertEqual(result["baseline_peak_pa"], 2.0)
        self.assertEqual(result["treated_peak_pa"], 0.5)
        self.assertEqual(result["worst_point_m"], queries[23].tolist())
        self.assertAlmostEqual(result["reduction_db"], 20*math.log10(2/0.5))
        self.assertAlmostEqual(result["target_pressure_pa"], 2*10**(-6/20))


class GeometryFeasibilityTests(unittest.TestCase):
    def test_selectable_sources_and_objects_have_disjoint_valid_physical_domains(self):
        # Independently check spatial invariants needed by the production PDE.
        # Overlapping prescribed source surfaces or overlapping damped objects
        # would change source normalization or double-count a physical object.
        catalog = get_catalog()
        config = model_config(catalog)
        bounds = np.asarray(catalog["room"]["size_m"], dtype=float)

        def xyz(value):
            return np.asarray([value[key] for key in ("x", "y", "z")])

        sources = [g for g in config["geometries"] if g["type"] == "sphere"]
        objects = [g for g in config["geometries"] if g["type"] == "box" and g["name"] != "room"]
        for source in sources:
            with self.subTest(source=source["name"]):
                center, radius = xyz(source["position"]), source["radius"]
                self.assertGreater(radius, 0)
                self.assertTrue(np.all(center-radius > 0))
                self.assertTrue(np.all(center+radius < bounds))
        for first, second in itertools.combinations(sources, 2):
            with self.subTest(sources=(first["name"], second["name"])):
                distance = np.linalg.norm(xyz(first["position"])-xyz(second["position"]))
                self.assertGreater(distance, first["radius"]+second["radius"])
        for item in objects:
            with self.subTest(object=item["name"]):
                origin, size = xyz(item["position"]), xyz(item["size"])
                self.assertTrue(np.all(size > 0))
                self.assertTrue(np.all(origin >= 0))
                self.assertTrue(np.all(origin+size <= bounds+1e-9))
        for first, second in itertools.combinations(objects, 2):
            with self.subTest(objects=(first["name"], second["name"])):
                overlap = (np.minimum(xyz(first["position"])+xyz(first["size"]),
                                      xyz(second["position"])+xyz(second["size"]))
                           - np.maximum(xyz(first["position"]), xyz(second["position"])))
                self.assertFalse(np.all(overlap > 1e-9))
        for source, item in itertools.product(sources, objects):
            with self.subTest(source=source["name"], object=item["name"]):
                center = xyz(source["position"])
                nearest = np.clip(center, xyz(item["position"]),
                                  xyz(item["position"])+xyz(item["size"]))
                self.assertGreater(np.linalg.norm(center-nearest), source["radius"])


class DiscreteSearchTests(unittest.TestCase):
    catalog = {"assumptions": ["Synthetic bases supplied only by this unit test."]}

    def test_affordable_enumeration_honors_budget_count_and_zero_price(self):
        request = request_for_search(budget_eur=240, max_objects=3)
        self.assertEqual(affordable_layouts(request), [(), ("a",), ("b",), ("c",),
                                                       ("a", "b"), ("a", "c"), ("b", "c")])
        request["budget_eur"] = 119.99
        self.assertEqual(affordable_layouts(request), [()])
        request.update(object_cost_eur=0, budget_eur=0, max_objects=2)
        self.assertEqual(len(affordable_layouts(request)), sum(math.comb(3, n) for n in range(3)))
        request["max_objects"] = 0
        self.assertEqual(affordable_layouts(request), [()])

    def test_all_winning_count_candidates_are_compared_before_tie_break(self):
        provider = PrescribedRmsBasis({(): 2, ("a",): 0.9, ("b",): 0.7, ("c",): 0.8})
        progress = []
        result = search(request_for_search(), provider, progress.append, self.catalog)
        self.assertTrue(result["feasible"])
        self.assertEqual(result["optimal_layout"]["slot_ids"], ["b"])
        self.assertEqual(result["optimal_layout"]["object_count"], 1)
        self.assertEqual(provider.calls, [("source", ()), ("source", ("a",)),
                                          ("source", ("b",)), ("source", ("c",))])
        self.assertEqual(result["search"]["evaluated_layouts"], 4)
        self.assertEqual(result["search"]["total_layouts"], 8)
        self.assertEqual(result["search"]["exhaustive_through_count"], 1)
        self.assertEqual(progress[-1]["evaluated"], 4)

    def test_search_does_not_assume_each_object_improves_pressure(self):
        # Singles all worsen the field; combinations can still succeed. A
        # three-object configuration would improve more, but count wins.
        provider = PrescribedRmsBasis({(): 2, ("a",): 2.1, ("b",): 2.2, ("c",): 2.3,
                                       ("a", "b"): 0.9, ("a", "c"): 0.7,
                                       ("b", "c"): 0.8, ("a", "b", "c"): 0.1})
        result = search(request_for_search(), provider, lambda _: None, self.catalog)
        self.assertEqual(result["optimal_layout"]["slot_ids"], ["a", "c"])
        self.assertEqual(result["optimal_layout"]["object_count"], 2)
        self.assertEqual(result["search"]["evaluated_layouts"], 7)
        self.assertFalse(any(len(slots) == 3 for _, slots in provider.calls))

    def test_infeasible_returns_explicit_failure_and_best_available(self):
        request = request_for_search(budget_eur=240)
        request["quiet_zones"][0]["target_pressure_pa"] = 0.5
        provider = PrescribedRmsBasis({(): 2, ("a",): 1.4, ("b",): 1.3, ("c",): 1.5,
                                       ("a", "b"): 1.2, ("a", "c"): 1.1, ("b", "c"): 1.25})
        result = search(request, provider, lambda _: None, self.catalog)
        self.assertFalse(result["feasible"])
        self.assertIsNone(result["optimal_layout"])
        self.assertEqual(result["best_available_layout"]["slot_ids"], ["a", "c"])
        self.assertFalse(result["best_available_layout"]["feasible"])
        self.assertTrue(all(not layout["feasible"] for layout in result["evaluations"]))
        self.assertEqual(result["search"]["evaluated_layouts"], result["search"]["total_layouts"])
        self.assertEqual(result["search"]["exhaustive_through_count"], 2)

    def test_untreated_room_can_be_zero_object_optimum(self):
        provider = PrescribedRmsBasis({(): 0.8})
        result = search(request_for_search(), provider, lambda _: None, self.catalog)
        self.assertTrue(result["feasible"])
        self.assertEqual(result["optimal_layout"]["slot_ids"], [])
        self.assertEqual(result["optimal_layout"]["cost_eur"], 0)
        self.assertEqual(provider.calls, [("source", ())])

    def test_two_sources_use_both_strengths_and_every_zone_must_pass(self):
        request = request_for_search(
            sources=[{"id": "first", "strength": 2}, {"id": "second", "strength": 0.5}],
            allowed_slot_ids=["a"], max_objects=1,
        )
        request["quiet_zones"].append({"id": "sleep", "center_m": [3, 2, 1],
                                       "size_m": [0.3, 0.3], "target_pressure_pa": 0.2})
        calls = []

        def provider(source, slots, queries):
            calls.append((source, slots))
            # Baseline RMS is sqrt((2*1)^2 + (.5*2)^2)/sqrt(2).
            amplitude = 1.0 if source == "first" else 2.0
            values = np.full(len(queries), amplitude, dtype=complex)
            if slots:
                values[:81] *= 0.1
                values[81:] *= 0.3
            return values, f"test-only-{source}-{slots}"

        result = search(request, provider, lambda _: None, self.catalog)
        self.assertFalse(result["feasible"])
        self.assertEqual(calls, [("first", ()), ("second", ()), ("first", ("a",)), ("second", ("a",))])
        baseline_rms = math.sqrt(5/2)
        zones = result["best_available_layout"]["zones"]
        self.assertAlmostEqual(zones[0]["baseline_peak_pa"], baseline_rms)
        self.assertAlmostEqual(zones[0]["treated_peak_pa"], baseline_rms*0.1)
        self.assertAlmostEqual(zones[1]["treated_peak_pa"], baseline_rms*0.3)
        self.assertTrue(zones[0]["met_target"])
        self.assertFalse(zones[1]["met_target"])

    def test_pressure_only_legacy_request_keeps_absolute_semantics(self):
        legacy = request_for_search()
        self.assertEqual(quietness_metric(legacy), "absolute_rms_pressure_pa")
        explicit = request_for_search(quietness_metric="absolute_rms_pressure_pa")
        pressures = {(): 2, ("a",): 0.9, ("b",): 0.7, ("c",): 0.8}
        legacy_result = search(legacy, PrescribedRmsBasis(pressures), lambda _: None, self.catalog)
        explicit_result = search(explicit, PrescribedRmsBasis(pressures), lambda _: None, self.catalog)
        self.assertEqual(legacy_result, explicit_result)
        self.assertEqual(legacy_result["quietness_metric"], "absolute_rms_pressure_pa")
        self.assertEqual(legacy_result["optimal_layout"]["slot_ids"], ["b"])

    def test_zero_relative_reduction_selects_untreated_minimum_count(self):
        request = request_for_search()
        request["quiet_zones"][0] = {"id": "quiet", "center_m": [2, 3, 1.4],
                                      "size_m": [0.4, 0.4], "target_reduction_db": 0}
        # A reduction-only request without an explicit metric selects relative
        # semantics, while pressure-only saved jobs retain their old mode.
        self.assertEqual(quietness_metric(request), "relative_pressure_reduction_db")
        provider = PrescribedRmsBasis({(): 0.8})
        result = search(request, provider, lambda _: None, self.catalog)
        self.assertTrue(result["feasible"])
        self.assertEqual(result["optimal_layout"]["object_count"], 0)
        self.assertEqual(result["optimal_layout"]["zones"][0]["reduction_db"], 0)
        self.assertEqual(result["search"]["evaluated_layouts"], 1)
        self.assertEqual(provider.calls, [("source", ())])

    def test_relative_weak_layouts_return_infeasible_with_best_available(self):
        request = request_for_search(quietness_metric="relative_pressure_reduction_db", max_objects=1)
        request["quiet_zones"][0]["target_reduction_db"] = 6
        provider = PrescribedRmsBasis({(): 2, ("a",): 1.8, ("b",): 1.9, ("c",): 1.7})
        result = search(request, provider, lambda _: None, self.catalog)
        self.assertFalse(result["feasible"])
        self.assertIsNone(result["optimal_layout"])
        self.assertEqual(result["best_available_layout"]["slot_ids"], ["c"])
        self.assertFalse(result["best_available_layout"]["feasible"])
        self.assertAlmostEqual(result["best_available_layout"]["zones"][0]["reduction_db"],
                               20*math.log10(2/1.7))
        self.assertEqual(result["search"]["evaluated_layouts"], result["search"]["total_layouts"])
        self.assertTrue(all(not item["feasible"] for item in result["evaluations"]))

    def test_relative_tie_uses_db_margin_despite_unequal_zone_baselines(self):
        request = request_for_search(quietness_metric="relative_pressure_reduction_db",
                                     allowed_slot_ids=["b", "a"], max_objects=1)
        request["quiet_zones"] = [
            {"id": "quiet", "center_m": [2, 3, 1.4], "size_m": [0.4, 0.4], "target_reduction_db": 6},
            {"id": "loud", "center_m": [3, 2, 1.0], "size_m": [0.4, 0.4], "target_reduction_db": 6},
        ]
        baseline = np.repeat([0.01, 100.0], 81)
        calls = []

        def provider(source, slots, queries):
            calls.append(slots)
            reductions = {(): [0, 0], ("a",): [8, 18], ("b",): [12, 7]}[slots]
            pressure = baseline*10**(-np.repeat(reductions, 81)/20)
            return pressure.astype(complex)*math.sqrt(2), f"test-only-{slots}"

        result = search(request, provider, lambda _: None, self.catalog)
        self.assertTrue(result["feasible"])
        self.assertEqual(result["optimal_layout"]["slot_ids"], ["a"])
        self.assertEqual(calls, [(), ("a",), ("b",)])
        a, b = result["evaluations"][1:]
        self.assertGreater(b["minimum_margin_pa"], a["minimum_margin_pa"])
        self.assertAlmostEqual(a["selection_score"], 2.0)
        self.assertAlmostEqual(b["selection_score"], 1.0)

    def test_source_strengths_affect_both_relative_and_absolute_constraints(self):
        def provider(source, slots, queries):
            attenuation = {"first": 0.1, "second": 0.8}[source] if slots else 1.0
            return np.full(len(queries), math.sqrt(2)*attenuation, dtype=complex), f"test-only-{source}-{slots}"

        for metric in ("relative_pressure_reduction_db", "absolute_rms_pressure_pa"):
            for strengths, feasible in (([2.0, 0.5], True), ([0.5, 2.0], False)):
                with self.subTest(metric=metric, strengths=strengths):
                    request = request_for_search(quietness_metric=metric,
                        sources=[{"id": "first", "strength": strengths[0]},
                                 {"id": "second", "strength": strengths[1]}],
                        allowed_slot_ids=["a"], max_objects=1)
                    request["quiet_zones"][0].update(target_pressure_pa=0.6, target_reduction_db=6)
                    result = search(request, provider, lambda _: None, self.catalog)
                    self.assertEqual(result["feasible"], feasible)
                    baseline = math.hypot(*strengths)
                    treated = math.hypot(strengths[0]*0.1, strengths[1]*0.8)
                    zone = result["best_available_layout"]["zones"][0]
                    self.assertAlmostEqual(zone["baseline_peak_pa"], baseline)
                    self.assertAlmostEqual(zone["treated_peak_pa"], treated)
                    self.assertAlmostEqual(zone["reduction_db"], 20*math.log10(baseline/treated))


if __name__ == "__main__":
    unittest.main()
