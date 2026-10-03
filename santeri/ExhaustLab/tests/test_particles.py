"""Analytic validation only: none of these fields are claimed as Allsolve data."""

import unittest

import numpy as np

from ExhaustLab.particles import (
    InletSamples,
    ParticleModel,
    RectangularChannel,
    RegularGridFieldSampler,
    flux_weighted_inlet,
    integrate_trajectories,
    timestep_convergence,
)


def analytic_grid(channel, velocity=(0.05, 0.0, 0.0), electric=(0.0, 0.0, 0.0)):
    axes = tuple(np.array([0.0, endpoint]) for endpoint in channel.extent_m)
    shape = (2, 2, 2, 3)
    return RegularGridFieldSampler(
        *axes,
        np.broadcast_to(velocity, shape),
        np.broadcast_to(electric, shape),
        provenance={"kind": "analytic_test_only"},
    )


class ParticleValidationTests(unittest.TestCase):
    def test_uniform_drift_matches_exact_wall_times_and_weighted_capture(self):
        channel = RectangularChannel()
        particle = ParticleModel()
        axial_speed = 0.05
        drift_speed = 0.6 * channel.gap_m * axial_speed / channel.length_m
        field = (0, drift_speed / particle.electrical_mobility_m2_v_s, 0)
        sampler = analytic_grid(channel, electric=field)
        inlet = flux_weighted_inlet(sampler, channel, n_y=10, n_z=3)
        result = integrate_trajectories(sampler, channel, particle, inlet,
            max_step_s=0.037, max_time_s=2.0, track_indices=(0, 29), path_stride=3)
        hit_times = (channel.gap_m - inlet.points_m[:, 1]) / drift_speed
        outlet_time = channel.length_m / axial_speed
        exact_capture = hit_times <= outlet_time
        np.testing.assert_array_equal(result.states == "captured", exact_capture)
        np.testing.assert_allclose(result.terminal_times_s, np.minimum(hit_times, outlet_time), atol=1e-12)
        self.assertAlmostEqual(result.summary()["captured_fraction"], 0.6)
        self.assertEqual(result.summary()["unresolved_count"], 0)
        for index, path in result.paths.items():
            self.assertEqual(path.shape[1], 4)  # time, x, y, z
            np.testing.assert_allclose(path[-1, 1:], result.terminal_points_m[index])

    def test_zero_charge_reaches_outlet_despite_electric_field(self):
        channel = RectangularChannel(gap_m=0.004)
        sampler = analytic_grid(channel, electric=(0, 50000, 0))
        inlet = flux_weighted_inlet(sampler, channel, n_y=7, n_z=5)
        result = integrate_trajectories(sampler, channel, ParticleModel(charge_e=0), inlet,
            max_step_s=0.021, max_time_s=2.0)
        self.assertTrue((result.states == "outlet").all())
        np.testing.assert_allclose(result.terminal_points_m[:, 0], channel.length_m)
        np.testing.assert_allclose(result.terminal_points_m[:, 1:], inlet.points_m[:, 1:])
        self.assertAlmostEqual(result.summary()["outlet_fraction"], 1.0)

    def test_negative_charge_reverses_wall_capture_direction(self):
        channel = RectangularChannel()
        sampler = analytic_grid(channel, electric=(0, 100000, 0))
        inlet = flux_weighted_inlet(sampler, channel, n_y=3, n_z=2)
        result = integrate_trajectories(sampler, channel, ParticleModel(charge_e=-100), inlet,
            max_step_s=0.013, max_time_s=2.0)
        self.assertTrue((result.states == "captured").all())
        self.assertTrue((result.reasons == "wall_y_min").all())
        np.testing.assert_array_equal(result.terminal_points_m[:, 1], np.zeros(6))

    def test_trilinear_interpolation_of_affine_fields_and_no_extrapolation(self):
        axes = (np.array([0, 0.01, 0.06]), np.array([0, 0.002, 0.006]), np.array([0, 0.02]))
        xx, yy, zz = np.meshgrid(*axes, indexing="ij")
        velocity = np.stack((2 * xx + yy, zz - yy, 3 * xx + zz), axis=-1)
        electric = 10 * velocity
        sampler = RegularGridFieldSampler(*axes, velocity, electric)
        points = np.array([[0.023, 0.003, 0.011], [0.06, 0.006, 0.02], [0.0600001, 0.003, 0.01]])
        fields = sampler.sample(points)
        expected = np.array([[2 * x + y, z - y, 3 * x + z] for x, y, z in points[:2]])
        np.testing.assert_allclose(fields.velocity_m_s[:2], expected, atol=1e-15)
        np.testing.assert_allclose(fields.electric_v_m[:2], 10 * expected, atol=1e-14)
        np.testing.assert_array_equal(fields.covered, [True, True, False])
        self.assertTrue(np.isnan(fields.velocity_m_s[2]).all())

    def test_flux_weighting_uses_local_axial_velocity(self):
        channel = RectangularChannel()
        axes = tuple(np.array([0.0, endpoint]) for endpoint in channel.extent_m)
        _, yy, _ = np.meshgrid(*axes, indexing="ij")
        velocity = np.zeros((2, 2, 2, 3))
        velocity[..., 0] = yy / channel.gap_m
        sampler = RegularGridFieldSampler(*axes, velocity, np.zeros_like(velocity))
        inlet = flux_weighted_inlet(sampler, channel, n_y=2, n_z=1)
        np.testing.assert_allclose(inlet.normalized_weights, [0.25, 0.75])
        self.assertAlmostEqual(inlet.flux_weights_m3_s.sum(), 0.5 * channel.gap_m * channel.span_m)

    def test_coverage_and_time_limits_are_unresolved_not_escaped(self):
        channel = RectangularChannel()
        sampler = analytic_grid(channel)
        inlet = flux_weighted_inlet(sampler, channel, n_y=2, n_z=2)
        limited = integrate_trajectories(sampler, channel, ParticleModel(charge_e=0), inlet,
            max_step_s=0.05, max_time_s=0.2)
        self.assertTrue((limited.states == "unresolved").all())
        self.assertTrue((limited.reasons == "time_limit").all())
        self.assertEqual(limited.summary()["outlet_fraction"], 0.0)
        self.assertEqual(limited.summary()["capture_upper_bound"], 1.0)
        axes = (np.array([0, 0.03]), np.array([0, channel.gap_m]), np.array([0, channel.span_m]))
        shape = (2, 2, 2, 3)
        incomplete = RegularGridFieldSampler(*axes, np.broadcast_to((0.05, 0, 0), shape), np.zeros(shape))
        missing = integrate_trajectories(incomplete, channel, ParticleModel(charge_e=0), inlet,
            max_step_s=0.011, max_time_s=2.0)
        self.assertTrue((missing.states == "unresolved").all())
        self.assertTrue(np.char.startswith(missing.reasons, "field_coverage").all())
        self.assertEqual(missing.summary()["outlet_fraction"], 0.0)
        # Even a large step from a covered midpoint cannot label an uncovered
        # outlet as resolved. This guards against insetting export endpoints.
        near_outlet = InletSamples(np.array([[0.025, 0.003, 0.01]]), np.ones(1))
        boundary_missing = integrate_trajectories(incomplete, channel, ParticleModel(charge_e=0), near_outlet,
            max_step_s=2.0, max_time_s=2.0)
        self.assertEqual(boundary_missing.states[0], "unresolved")
        self.assertEqual(boundary_missing.reasons[0], "field_coverage_boundary")

    def test_timestep_refinement_reduces_nonuniform_drift_time_error(self):
        channel = RectangularChannel()
        particle = ParticleModel()
        axes = tuple(np.array([0.0, endpoint]) for endpoint in channel.extent_m)
        _, yy, _ = np.meshgrid(*axes, indexing="ij")
        velocity = np.zeros((2, 2, 2, 3))
        velocity[..., 0] = 0.01
        electric = np.zeros_like(velocity)
        growth_rate = 0.2
        electric[..., 1] = growth_rate * yy / particle.electrical_mobility_m2_v_s
        sampler = RegularGridFieldSampler(*axes, velocity, electric)
        inlet = InletSamples(np.array([[0, channel.gap_m / 2, channel.span_m / 2]]), np.ones(1))
        exact_time = np.log(2) / growth_rate
        errors = []
        for dt in (0.5, 0.25, 0.125):
            result = integrate_trajectories(sampler, channel, particle, inlet, max_step_s=dt, max_time_s=10)
            self.assertEqual(result.states[0], "captured")
            errors.append(abs(result.terminal_times_s[0] - exact_time))
        self.assertLess(errors[1], errors[0])
        self.assertLess(errors[2], errors[1])
        self.assertLess(errors[2], 0.003)
        convergence = timestep_convergence(sampler, channel, particle, inlet,
            max_step_s=0.5, max_time_s=10)
        self.assertEqual(len(convergence["levels"]), 3)
        self.assertEqual(convergence["successive_changes"][-1]["changed_classification_weight"], 0)


if __name__ == "__main__":
    unittest.main()
