"""Analytic checks for the cloud script's scalar mode decomposition; no SDK/jobs."""
import ast
import math
import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("source_readout.py")
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
function = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "_coherent_powers")
namespace = {}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)
coherent_powers = namespace["_coherent_powers"]
Y0 = 1.0 / 376.7303136671465
AREA = 500e-9 * 100e-9


def quadratures(ex=0j, ey=0j, hx=0j, hy=0j):
    result = {}
    for name, value in [("Ex", ex), ("Ey", ey), ("Hx", hx), ("Hy", hy)]:
        result[name + "_cos"] = value.real
        result[name + "_sin"] = -value.imag
    return result


class ModeReadoutTests(unittest.TestCase):
    def assertRelativeEqual(self, actual, expected):
        self.assertTrue(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-30),
                        f"{actual} != {expected}")

    def test_fresnel_interface_with_different_liquid_and_glass_admittances(self):
        n_in, n_out = 1.333, 1.451
        Y_in, Y_out = n_in*Y0, n_out*Y0
        r = (n_in-n_out)/(n_in+n_out)
        t = 2.0*n_in/(n_in+n_out)
        # Arbitrary nonzero phase exercises E_cos-iE_sin and the Ey/Hx sign.
        phase = complex(math.cos(0.71), math.sin(0.71))
        incident = coherent_powers(quadratures(ey=phase*(1+r), hx=-Y_in*phase*(1-r)), Y_in, AREA)
        transmitted = coherent_powers(quadratures(ey=phase*t, hx=-Y_out*phase*t), Y_out, AREA)
        specified = AREA*Y_in/2.0
        self.assertRelativeEqual(incident["forward"], specified)
        self.assertRelativeEqual(incident["backward"]/specified, r*r)
        self.assertRelativeEqual(transmitted["forward"]/specified, (n_out/n_in)*t*t)
        self.assertRelativeEqual((incident["backward"]+transmitted["forward"])/specified, 1.0)
        self.assertLess(transmitted["backward"]/specified, 1e-28)
        self.assertEqual(incident["crosspolarized"], 0.0)

    def test_counterpropagating_modes_and_crosspolarization(self):
        Y = 1.4*Y0
        xf, xb, yf, yb = 0.03+0.02j, -0.01+0.04j, 0.7-0.6j, -0.2+0.1j
        means = quadratures(ex=xf+xb, ey=yf+yb, hx=-Y*(yf-yb), hy=Y*(xf-xb))
        result = coherent_powers(means, Y, AREA)
        scale = AREA*Y/2.0
        self.assertRelativeEqual(result["forward"], scale*(abs(xf)**2+abs(yf)**2))
        self.assertRelativeEqual(result["backward"], scale*(abs(xb)**2+abs(yb)**2))
        self.assertRelativeEqual(result["crosspolarized"], scale*(abs(xf)**2+abs(xb)**2))
        poynting = AREA/2.0*((means["Ex_cos"]*means["Hy_cos"]+means["Ex_sin"]*means["Hy_sin"])
                            -(means["Ey_cos"]*means["Hx_cos"]+means["Ey_sin"]*means["Hx_sin"]))
        self.assertRelativeEqual(result["forward"]-result["backward"], poynting)

    def test_zero_mean_evanescent_content_is_not_propagating_zeroth_power(self):
        Y = 1.4*Y0
        # Purely reactive Ey/Hx relation, varying as a nonzero Fourier harmonic.
        # It has zero mean and zero real flux but positive local directional splits.
        samples = [complex(math.cos(2*math.pi*i/16), math.sin(2*math.pi*i/16))
                   for i in range(16)]
        ey = sum(samples)/len(samples)
        hx = sum(1j*Y*value for value in samples)/len(samples)
        result = coherent_powers(quadratures(ey=ey, hx=hx), Y, AREA)
        local_forward = sum(abs(value-(1j*Y*value)/Y)**2 for value in samples)*AREA*Y/(8*len(samples))
        local_backward = sum(abs(value+(1j*Y*value)/Y)**2 for value in samples)*AREA*Y/(8*len(samples))
        self.assertRelativeEqual(local_forward, local_backward)
        self.assertGreater(local_forward, 0.0)
        self.assertLess(result["forward"]/local_forward, 1e-28)
        self.assertLess(result["backward"]/local_backward, 1e-28)


if __name__ == "__main__":
    unittest.main()
