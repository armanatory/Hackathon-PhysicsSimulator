"""Readout checks catch field signs, SI units, normalization, and gates."""

import math

import pytest

from .fresnel import (
    VACUUM_IMPEDANCE_OHM,
    compare_to_reference,
    directional_power_density,
    normalize_readout,
    quadrature_to_phasor,
    slab_reference,
    traveling_wave_fields,
    wave_impedance,
)


def test_quadratures_follow_positive_time_phasor_convention():
    phasor = quadrature_to_phasor(2.0, 3.0)
    assert phasor == 2.0 - 3.0j
    for phase in (0, math.pi / 6, math.pi / 2, math.pi):
        reconstructed = (phasor * complex(math.cos(phase), math.sin(phase))).real
        expected = 2.0 * math.cos(phase) + 3.0 * math.sin(phase)
        assert reconstructed == pytest.approx(expected, abs=1e-14)


@pytest.mark.parametrize("index", [1.0, 1.33, 1.5, 2.25])
def test_colocated_fields_recover_both_traveling_waves(index):
    forward, backward = 2.0 + 1.0j, -0.3 + 0.4j
    impedance = VACUUM_IMPEDANCE_OHM / index
    waves = traveling_wave_fields(forward + backward, (forward - backward) / impedance, index)
    assert waves.forward == pytest.approx(forward, abs=1e-14)
    assert waves.backward == pytest.approx(backward, abs=1e-14)
    assert waves.impedance_ohm == pytest.approx(impedance)


def test_backward_wave_has_opposite_magnetic_field_sign():
    electric = 1 + 2j
    waves = traveling_wave_fields(electric, -electric / wave_impedance(1.0), 1.0)
    assert waves.forward == pytest.approx(0j, abs=1e-14)
    assert waves.backward == pytest.approx(electric, abs=1e-14)


def test_power_is_peak_phasor_si_poynting_flux():
    assert directional_power_density(2 + 0j, 1.5) == pytest.approx(3 / VACUUM_IMPEDANCE_OHM)


def test_readout_matches_quarter_wave_reference_for_arbitrary_incident_amplitude():
    reference = slab_reference(1000e-9, 1000e-9 / 6, 1.5)
    incident = 2 + 3j
    # Synthetic fixture verifies readout math only; it is not solver output.
    readout = normalize_readout(incident, reference.r * incident, reference.t * incident,
                               label="synthetic_test_fixture")
    assert readout.r == pytest.approx(reference.r)
    assert readout.t == pytest.approx(reference.t)
    assert readout.R == pytest.approx(reference.R)
    assert readout.T == pytest.approx(reference.T)
    assert readout.incident_power_w_m2 == pytest.approx(13 / (2 * VACUUM_IMPEDANCE_OHM))
    comparison = compare_to_reference(reference, readout, power_tolerance=1e-12,
                                      energy_tolerance=1e-12)
    assert comparison.passed
    assert comparison.reference_label == "analytic_fresnel_reference"
    assert comparison.readout_label == "synthetic_test_fixture"


def test_unequal_exteriors_require_index_ratio_for_power_transmission():
    readout = normalize_readout(2 + 0j, 0j, 4 / 3 + 0j, n_left=1.0, n_right=2.25)
    assert abs(readout.t) ** 2 == pytest.approx(4 / 9)
    assert readout.T == pytest.approx(1.0)
    assert readout.energy_residual == pytest.approx(0.0)


def test_input_net_flux_is_not_used_as_incident_normalization():
    waves = traveling_wave_fields(1.5 + 0j, 0.5 / wave_impedance(1.0), 1.0)
    readout = normalize_readout(waves.forward, waves.backward, math.sqrt(0.75))
    assert readout.R == pytest.approx(0.25)
    assert readout.T == pytest.approx(0.75)


def test_energy_balance_does_not_hide_wrong_reflection_and_transmission():
    reference = slab_reference(1000e-9, 1000e-9 / 6, 1.5)
    readout = normalize_readout(1, math.sqrt(reference.R + 0.05), math.sqrt(reference.T - 0.05))
    comparison = compare_to_reference(reference, readout, power_tolerance=0.01, energy_tolerance=0.01)
    assert comparison.energy_pass
    assert not comparison.reflectance_pass
    assert not comparison.transmittance_pass
    assert not comparison.passed


def test_reference_proximity_does_not_hide_energy_imbalance():
    reference = slab_reference(1000e-9, 1000e-9 / 6, 1.5)
    readout = normalize_readout(1, math.sqrt(reference.R + 0.008), math.sqrt(reference.T + 0.008))
    comparison = compare_to_reference(reference, readout, power_tolerance=0.01, energy_tolerance=0.01)
    assert comparison.reflectance_pass
    assert comparison.transmittance_pass
    assert not comparison.energy_pass
    assert not comparison.passed


def test_comparison_rejects_different_exterior_media():
    reference = slab_reference(1000e-9, 0, 1.5)
    readout = normalize_readout(1, 0, 1, n_right=1.5)
    with pytest.raises(ValueError, match="indices must match"):
        compare_to_reference(reference, readout)


@pytest.mark.parametrize("amplitude", [0, 0j, 1e-300])
def test_readout_rejects_zero_or_underflowed_incident_power(amplitude):
    with pytest.raises(ValueError, match="positive representable power"):
        normalize_readout(amplitude, 0, 1)


@pytest.mark.parametrize("value", [complex(float("nan"), 0), complex(0, float("inf")), float("inf"), True, "1"])
def test_readout_rejects_invalid_complex_fields(value):
    with pytest.raises(ValueError):
        traveling_wave_fields(value, 1, 1.0)
    with pytest.raises(ValueError):
        traveling_wave_fields(1, value, 1.0)
    with pytest.raises(ValueError):
        normalize_readout(1, value, 1)
    with pytest.raises(ValueError):
        normalize_readout(1, 0, value)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), 1 + 0j, True])
def test_readout_rejects_invalid_medium_index(value):
    with pytest.raises(ValueError):
        traveling_wave_fields(1, 0, value)
    with pytest.raises(ValueError):
        normalize_readout(1, 0, 1, n_right=value)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True])
@pytest.mark.parametrize("parameter", ["power_tolerance", "energy_tolerance"])
def test_comparison_rejects_invalid_tolerances(value, parameter):
    reference = slab_reference(1000e-9, 0, 1.5)
    readout = normalize_readout(1, 0, 1)
    with pytest.raises(ValueError):
        compare_to_reference(reference, readout, **{parameter: value})
