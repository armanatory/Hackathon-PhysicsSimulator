"""Independent analytic limits and Fourier convergence for the TE reference."""
import cmath
import math
import unittest

from reference import reflectance_transmittance


def film_amplitudes(n0, nf, ns, thickness, wavelength):
    r01, r12 = (n0-nf)/(n0+nf), (nf-ns)/(nf+ns)
    phase = cmath.exp(-2j*math.pi*nf*thickness/wavelength)
    denominator = 1.0+r01*r12*phase*phase
    return ((r01+r12*phase*phase)/denominator,
            (2*n0/(n0+nf))*(2*nf/(nf+ns))*phase/denominator)


class TEReferenceTests(unittest.TestCase):
    def assertComplexClose(self, actual, expected):
        self.assertLess(abs(complex(actual["real"], actual["imag"])-expected), 1e-11)

    def test_zero_ridge_height_matches_flat_film(self):
        result = reflectance_transmittance(500, 0.63, 0, 173, 1030, 1.333, 2.01, 1.45)
        r, t = film_amplitudes(1.333, 2.01, 1.45, 173, 1030)
        self.assertComplexClose(result["r0"], r)
        self.assertComplexClose(result["t0"], t)
        self.assertAlmostEqual(result["R"], abs(r)**2, places=12)
        self.assertAlmostEqual(result["T"], 1.45/1.333*abs(t)**2, places=12)

    def test_full_fill_is_one_homogeneous_film(self):
        result = reflectance_transmittance(500, 1, 127, 173, 1030, 1.333, 2.01, 1.45)
        r, t = film_amplitudes(1.333, 2.01, 1.45, 300, 1030)
        self.assertComplexClose(result["r0"], r)
        self.assertComplexClose(result["t0"], t)

    def test_empty_ridge_region_has_only_liquid_propagation_phase(self):
        result = reflectance_transmittance(500, 0, 127, 173, 1030, 1.333, 2.01, 1.45)
        r, t = film_amplitudes(1.333, 2.01, 1.45, 173, 1030)
        phase = cmath.exp(-2j*math.pi*1.333*127/1030)
        self.assertComplexClose(result["r0"], r*phase*phase)
        self.assertComplexClose(result["t0"], t*phase)

    def test_empty_zero_thickness_stack_is_liquid_glass_interface(self):
        result = reflectance_transmittance(500, 0.5, 0, 0, 1000, 1.333, 2, 1.45)
        r, t = (1.333-1.45)/(1.333+1.45), 2*1.333/(1.333+1.45)
        self.assertComplexClose(result["r0"], r)
        self.assertComplexClose(result["t0"], t)
        self.assertAlmostEqual(result["R"]+result["T"], 1.0, places=12)

    def test_internal_cutoff_uses_finite_linear_solution(self):
        # n_sin*period==wavelength: +/-1 film modes are exactly at cutoff.
        result = reflectance_transmittance(500, 0.5, 150, 200, 1000, 1.333, 2, 1.45)
        self.assertAlmostEqual(result["R"]+result["T"], 1.0, places=10)
        self.assertLess(result["linear_system_relative_residual"], 1e-12)

    def test_grating_order_convergence_and_lossless_power(self):
        results = [reflectance_transmittance(510, 0.57, 180, 160, 1020, 1.333, 2.01, 1.45, orders=n)
                   for n in (5, 9, 13)]
        for result in results:
            self.assertAlmostEqual(result["R"]+result["T"], 1.0, places=10)
            self.assertEqual(result["propagating_top_orders"], [0])
            self.assertEqual(result["propagating_bottom_orders"], [0])
            self.assertAlmostEqual(result["R"], result["R0"], places=12)
        self.assertLess(abs(results[-1]["R"]-results[-2]["R"]), 1e-4)
        self.assertLess(abs(results[-1]["R"]-results[-2]["R"]), abs(results[-2]["R"]-results[0]["R"]))

    def test_propagating_diffraction_orders_are_in_total_power(self):
        result = reflectance_transmittance(1000, 0.5, 150, 160, 900, 1.333, 2.01, 1.45)
        self.assertEqual(result["propagating_bottom_orders"], [-1, 0, 1])
        self.assertGreater(result["T"]-result["T0"], 1e-4)
        self.assertAlmostEqual(result["R"]+result["T"], 1.0, places=10)

    def test_thick_layer_high_orders_do_not_create_growing_exponentials(self):
        result = reflectance_transmittance(500, 0.5, 2500, 2000, 1000, 1.333, 2.01, 1.45, orders=20)
        self.assertLessEqual(result["maximum_layer_propagation_magnitude"], 1.0+1e-14)
        self.assertAlmostEqual(result["R"]+result["T"], 1.0, places=10)


if __name__ == "__main__":
    unittest.main()
