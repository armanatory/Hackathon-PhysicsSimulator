"""Independent reference checks with known thin-film limiting cases."""

import math

import pytest

from .fresnel import ANALYTIC_LABEL, slab_reference


WAVELENGTH = 1000e-9


def test_vacuum_has_no_reflection_and_correct_propagation_phase():
    reference = slab_reference(WAVELENGTH, WAVELENGTH / 4, 1.0)
    assert reference.label == ANALYTIC_LABEL
    assert reference.r == pytest.approx(0j, abs=1e-14)
    assert reference.t == pytest.approx(-1j, abs=1e-14)
    assert reference.R == pytest.approx(0.0, abs=1e-14)
    assert reference.T == pytest.approx(1.0, abs=1e-14)


def test_zero_thickness_reduces_to_exterior_fresnel_interface():
    reference = slab_reference(WAVELENGTH, 0.0, 4.0, n_left=1.0, n_right=1.5)
    assert reference.r == pytest.approx(-0.2 + 0j, abs=1e-14)
    assert reference.t == pytest.approx(0.8 + 0j, abs=1e-14)
    assert reference.R == pytest.approx(0.04, abs=1e-14)
    assert reference.T == pytest.approx(0.96, abs=1e-14)


def test_quarter_wave_dielectric_slab_expected_reflection_and_transmission():
    reference = slab_reference(WAVELENGTH, WAVELENGTH / (4.0 * 1.5), 1.5)
    assert reference.r == pytest.approx(-5.0 / 13.0 + 0j, abs=1e-14)
    assert reference.t == pytest.approx(-12j / 13.0, abs=1e-14)
    assert reference.R == pytest.approx(0.14792899408284024, abs=1e-14)
    assert reference.T == pytest.approx(0.8520710059171598, abs=1e-14)
    assert reference.energy_residual == pytest.approx(0.0, abs=1e-14)


def test_half_wave_slab_returns_zero_reflection():
    reference = slab_reference(WAVELENGTH, WAVELENGTH / (2.0 * 1.5), 1.5)
    assert reference.r == pytest.approx(0j, abs=1e-14)
    assert reference.t == pytest.approx(-1 + 0j, abs=1e-14)
    assert reference.R == pytest.approx(0.0, abs=1e-14)
    assert reference.T == pytest.approx(1.0, abs=1e-14)


def test_quarter_wave_antireflection_with_unequal_exteriors():
    left, right = 1.0, 2.25
    slab = math.sqrt(left * right)
    reference = slab_reference(WAVELENGTH, WAVELENGTH / (4 * slab), slab, left, right)
    assert reference.r == pytest.approx(0j, abs=1e-14)
    assert reference.t == pytest.approx(-1j * math.sqrt(left / right), abs=1e-14)
    assert abs(reference.t) ** 2 == pytest.approx(4.0 / 9.0, abs=1e-14)
    assert reference.T == pytest.approx(1.0, abs=1e-14)


@pytest.mark.parametrize("thickness", [0.0, 35e-9, 100e-9, 311e-9, 700e-9, 1e-6])
@pytest.mark.parametrize("indices", [(1.0, 1.5, 1.0), (1.33, 2.1, 1.0), (1.0, 1.2, 2.0)])
def test_lossless_slab_energy_balance_over_phase_and_index_contrasts(thickness, indices):
    left, slab, right = indices
    reference = slab_reference(WAVELENGTH, thickness, slab, left, right)
    assert 0 <= reference.R <= 1.0
    assert 0 <= reference.T <= 1.0 + 1e-14
    assert reference.R + reference.T == pytest.approx(1.0, abs=2e-14)


@pytest.mark.parametrize("parameter", ["wavelength_m", "n_slab", "n_left", "n_right"])
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), -float("inf"), 1 + 0j, True, "1"])
def test_rejects_invalid_positive_real_parameters(parameter, value):
    arguments = dict(wavelength_m=WAVELENGTH, thickness_m=100e-9, n_slab=1.5,
                     n_left=1.0, n_right=1.0)
    arguments[parameter] = value
    with pytest.raises(ValueError):
        slab_reference(**arguments)


@pytest.mark.parametrize("thickness", [-1, float("nan"), float("inf"), -float("inf"), 0j, True])
def test_rejects_invalid_thickness(thickness):
    with pytest.raises(ValueError):
        slab_reference(WAVELENGTH, thickness, 1.5)
