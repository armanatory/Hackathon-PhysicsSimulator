"""Analytic-only validation of the export-grid refinement adapter."""

import unittest

import numpy as np

from ExhaustLab.analyze_convergence import downsample_sampler
from ExhaustLab.particles import RegularGridFieldSampler


class GridRefinementAdapterTests(unittest.TestCase):
    def test_downsampling_preserves_source_nodes_endpoints_and_changes_interpolant(self):
        axes = tuple(np.linspace(0, 1, 5) for _ in range(3))
        xx, _, _ = np.meshgrid(*axes, indexing="ij")
        velocity = np.zeros((5, 5, 5, 3))
        velocity[..., 0] = xx ** 2
        full = RegularGridFieldSampler(*axes, velocity, np.zeros_like(velocity), provenance={"test_only": True})
        coarse = downsample_sampler(full)
        self.assertEqual(coarse.velocity_m_s.shape, (3, 3, 3, 3))
        np.testing.assert_array_equal(coarse.velocity_m_s, full.velocity_m_s[::2, ::2, ::2])
        for axis in coarse.axes_m:
            self.assertEqual(axis[0], 0)
            self.assertEqual(axis[-1], 1)
        query = np.array([[0.25, 0.5, 0.5]])
        self.assertAlmostEqual(full.sample(query).velocity_m_s[0, 0], 0.0625)
        self.assertAlmostEqual(coarse.sample(query).velocity_m_s[0, 0], 0.125)
        np.testing.assert_array_equal(full.velocity_m_s, velocity)  # source remains unchanged

    def test_even_axis_cannot_silently_drop_endpoint(self):
        axes = (np.linspace(0, 1, 6), np.linspace(0, 1, 5), np.linspace(0, 1, 5))
        fields = np.zeros((6, 5, 5, 3))
        sampler = RegularGridFieldSampler(*axes, fields, fields)
        with self.assertRaisesRegex(ValueError, "odd number"):
            downsample_sampler(sampler)


if __name__ == "__main__":
    unittest.main()
