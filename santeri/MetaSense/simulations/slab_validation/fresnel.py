"""Lossless normal-incidence slab reference and SI traveling-wave readout.

All phasors use exp(+i * omega * time), so a wave propagating in +z has
exp(-i * k * z). The analytic transmitted amplitude is evaluated at the
right slab face; the incident and reflected amplitudes are at the left face.
Field amplitudes at other monitor locations must be translated to those
planes before comparing complex r/t. Power R/T do not require that translation
in the lossless exterior media used here.

These formulas assume real positive refractive indices, relative permeability
one, a planar lossless slab, normal incidence, and x-polarized electric field.
They are an ANALYTIC REFERENCE, never a solver or experimental result.
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from numbers import Complex, Real


VACUUM_IMPEDANCE_OHM = 376.730313412
ANALYTIC_LABEL = "analytic_fresnel_reference"
PHASOR_CONVENTION = "exp(+i omega t); E = E_cos - i E_sin"


def _real(name: str, value: float, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if positive and result <= 0.0:
        raise ValueError(f"{name} must be positive")
    return result


def _nonnegative(name: str, value: float) -> float:
    result = _real(name, value)
    if result < 0.0:
        raise ValueError(f"{name} must be nonnegative")
    return result


def _phasor(name: str, value: complex) -> complex:
    if isinstance(value, bool) or not isinstance(value, Complex):
        raise ValueError(f"{name} must be a finite complex number")
    result = complex(value)
    if not (math.isfinite(result.real) and math.isfinite(result.imag)):
        raise ValueError(f"{name} must be finite")
    return result


def wave_impedance(refractive_index: float) -> float:
    """Return Z0/n in ohms for a nonmagnetic, lossless dielectric."""
    index = _real("refractive_index", refractive_index, positive=True)
    impedance = VACUUM_IMPEDANCE_OHM / index
    if not math.isfinite(impedance) or impedance <= 0.0:
        raise ValueError("refractive_index gives an unrepresentable impedance")
    return impedance


@dataclass(frozen=True)
class SlabReference:
    wavelength_m: float
    thickness_m: float
    n_slab: float
    n_left: float
    n_right: float
    r: complex
    t: complex
    R: float
    T: float
    label: str = ANALYTIC_LABEL
    phasor_convention: str = PHASOR_CONVENTION

    @property
    def energy_residual(self) -> float:
        return self.R + self.T - 1.0


def slab_reference(
    wavelength_m: float,
    thickness_m: float,
    n_slab: float,
    n_left: float = 1.0,
    n_right: float = 1.0,
) -> SlabReference:
    """Calculate complex r/t and flux-normalized R/T for one dielectric slab.

    r = E_reflected/E_incident and t = E_transmitted/E_incident.
    Consequently T = (n_right/n_left) * |t|^2, including unequal exteriors.
    Wavelength is the vacuum wavelength, and dimensions are in meters.
    """
    wavelength = _real("wavelength_m", wavelength_m, positive=True)
    thickness = _nonnegative("thickness_m", thickness_m)
    slab = _real("n_slab", n_slab, positive=True)
    left = _real("n_left", n_left, positive=True)
    right = _real("n_right", n_right, positive=True)
    phase = 2.0 * math.pi * (slab * (thickness / wavelength))
    if not math.isfinite(phase):
        raise ValueError("the slab optical phase must be finite")

    def interface(a: float, b: float) -> tuple[float, float]:
        # Scaling avoids overflowing a+b for individually finite indices.
        scale = max(a, b)
        a_scaled, b_scaled = a / scale, b / scale
        return ((a_scaled - b_scaled) / (a_scaled + b_scaled),
                2.0 * a_scaled / (a_scaled + b_scaled))

    r01, t01 = interface(left, slab)
    r12, t12 = interface(slab, right)
    propagation = cmath.exp(-1j * phase)
    denominator = 1.0 + r01 * r12 * propagation**2
    if denominator == 0:
        raise ValueError("index contrast cannot be resolved in floating-point precision")
    r = (r01 + r12 * propagation**2) / denominator
    t = t01 * t12 * propagation / denominator
    R = abs(r) ** 2
    T = right / left * abs(t) ** 2
    if not all(math.isfinite(value) for value in (r.real, r.imag, t.real, t.imag, R, T)):
        raise ValueError("indices give unrepresentable Fresnel amplitudes or powers")
    return SlabReference(wavelength, thickness, slab, left, right, r, t, R, T)


def quadrature_to_phasor(cosine: float, sine: float) -> complex:
    """Convert E_cos cos(omega t) + E_sin sin(omega t) to our phasor.

    Applies to either E or H; units are preserved. Real fields are
    Re[(E_cos - i E_sin) * exp(+i omega t)].
    """
    return complex(_real("cosine", cosine), -_real("sine", sine))


@dataclass(frozen=True)
class TravelingWaves:
    forward: complex
    backward: complex
    impedance_ohm: float


def traveling_wave_fields(
    E_x: complex, H_y: complex, refractive_index: float
) -> TravelingWaves:
    """Split colocalized complex E_x [V/m], H_y [A/m] into +z/-z E waves.

    H_y = (E_forward - E_backward)/Z. Fields must be sampled in a
    homogeneous nonmagnetic medium away from interfaces and PML regions.
    This decomposition assumes propagating normal-incidence waves; it is
    not a general extraction of evanescent fields or diffraction orders.
    """
    electric = _phasor("E_x", E_x)
    magnetic = _phasor("H_y", H_y)
    impedance = wave_impedance(refractive_index)
    forward = (electric + impedance * magnetic) / 2.0
    backward = (electric - impedance * magnetic) / 2.0
    if not all(math.isfinite(component) for value in (forward, backward)
               for component in (value.real, value.imag)):
        raise ValueError("fields give unrepresentable traveling-wave amplitudes")
    return TravelingWaves(forward, backward, impedance)


def directional_power_density(electric_amplitude: complex, refractive_index: float) -> float:
    """Return positive time-averaged power magnitude in W/m^2.

    For peak-amplitude phasors P = |E|^2/(2 Z). Give propagation direction
    separately; backward power is a positive magnitude for reflectance.
    """
    amplitude = _phasor("electric_amplitude", electric_amplitude)
    try:
        power = abs(amplitude) ** 2 / (2.0 * wave_impedance(refractive_index))
    except OverflowError as error:
        raise ValueError("electric_amplitude gives unrepresentable power") from error
    if not math.isfinite(power):
        raise ValueError("electric_amplitude gives unrepresentable power")
    return power


@dataclass(frozen=True)
class PowerReadout:
    r: complex
    t: complex
    R: float
    T: float
    incident_power_w_m2: float
    reflected_power_w_m2: float
    transmitted_power_w_m2: float
    n_left: float
    n_right: float
    label: str = "complex_field_readout"

    @property
    def energy_residual(self) -> float:
        """R + T - 1, expected to vanish only for a lossless solved system."""
        return self.R + self.T - 1.0


def normalize_readout(
    incident_forward: complex,
    reflected_backward: complex,
    transmitted_forward: complex,
    n_left: float = 1.0,
    n_right: float = 1.0,
    *,
    label: str = "complex_field_readout",
) -> PowerReadout:
    """Normalize directional fields by incident power, never net input flux.

    The incident wave can come from a separate homogeneous calibration run
    or a verified total-field split at the input monitor. Pass field amplitudes
    in V/m. The right monitor must exclude incoming waves from its boundary.
    """
    incident = _phasor("incident_forward", incident_forward)
    reflected = _phasor("reflected_backward", reflected_backward)
    transmitted = _phasor("transmitted_forward", transmitted_forward)
    left = _real("n_left", n_left, positive=True)
    right = _real("n_right", n_right, positive=True)
    if not isinstance(label, str) or not label.strip():
        raise ValueError("label must be a nonempty provenance string")
    incident_power = directional_power_density(incident, left)
    if incident_power <= 0.0:
        raise ValueError("incident_forward must have a positive representable power")
    reflected_power = directional_power_density(reflected, left)
    transmitted_power = directional_power_density(transmitted, right)
    r, t = reflected / incident, transmitted / incident
    R, T = reflected_power / incident_power, transmitted_power / incident_power
    if not all(math.isfinite(value) for value in (R, T, r.real, r.imag, t.real, t.imag)):
        raise ValueError("normalized readout must be finite")
    return PowerReadout(r, t, R, T, incident_power, reflected_power,
                        transmitted_power, left, right, label)


@dataclass(frozen=True)
class ReferenceComparison:
    reference_label: str
    readout_label: str
    reflectance_error: float
    transmittance_error: float
    energy_residual: float
    power_tolerance: float
    energy_tolerance: float
    reflectance_pass: bool
    transmittance_pass: bool
    energy_pass: bool

    @property
    def passed(self) -> bool:
        return self.reflectance_pass and self.transmittance_pass and self.energy_pass


def compare_to_reference(
    reference: SlabReference,
    readout: PowerReadout,
    *,
    power_tolerance: float = 0.01,
    energy_tolerance: float = 0.01,
) -> ReferenceComparison:
    """Check absolute R/T errors and |R+T-1| independently.

    This checks supplied data only; a passing analytic self-test is not
    evidence that a cloud solver's source, boundaries, or fields were verified.
    """
    power_tol = _nonnegative("power_tolerance", power_tolerance)
    energy_tol = _nonnegative("energy_tolerance", energy_tolerance)
    if reference.n_left != readout.n_left or reference.n_right != readout.n_right:
        raise ValueError("reference and readout exterior refractive indices must match")
    for name, value in (("reference.R", reference.R), ("reference.T", reference.T),
                        ("readout.R", readout.R), ("readout.T", readout.T)):
        _nonnegative(name, value)
    r_error = abs(readout.R - reference.R)
    t_error = abs(readout.T - reference.T)
    energy = readout.energy_residual
    return ReferenceComparison(
        reference.label, readout.label, r_error, t_error, energy,
        power_tol, energy_tol, r_error <= power_tol, t_error <= power_tol,
        abs(energy) <= energy_tol,
    )
