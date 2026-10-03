"""Deterministic toy spectra for UI development, not Maxwell simulations."""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .models import DesignInput


@dataclass(frozen=True)
class ToySpectrum:
    wavelength_nm: NDArray[np.float64]
    unbound_response: NDArray[np.float64]
    bound_response: NDArray[np.float64]
    baseline_center_nm: float
    sensitivity_nm_per_coverage: float
    linewidth_nm: float


def toy_response(
    wavelength_nm: NDArray[np.float64], center_nm: float, linewidth_nm: float
) -> NDArray[np.float64]:
    """An arbitrary normalized Lorentzian dip for a visibly synthetic demo."""
    offset = (wavelength_nm - center_nm) / linewidth_nm
    return 1.0 - 0.42 / (1.0 + offset * offset)


def toy_parameters(design: DesignInput) -> tuple[float, float, float]:
    """Arbitrary smooth geometry mapping; coefficients carry no physical calibration."""
    center_nm = 600.0 + 0.12 * (design.period_nm - 600.0) + 0.025 * (
        design.pillar_height_nm - 300.0
    )
    sensitivity_nm_per_coverage = 4.0 * (design.pillar_diameter_nm / 250.0) * (
        design.pillar_height_nm / 300.0
    )
    linewidth_nm = 12.0 + 0.004 * (design.period_nm - 600.0)
    return center_nm, sensitivity_nm_per_coverage, linewidth_nm


def simulate_toy_spectra(design: DesignInput, assumed_coverage: float) -> ToySpectrum:
    wavelength_nm = np.linspace(450.0, 900.0, 451, dtype=np.float64)
    center_nm, sensitivity_nm_per_coverage, linewidth_nm = toy_parameters(design)
    return ToySpectrum(
        wavelength_nm=wavelength_nm,
        unbound_response=toy_response(wavelength_nm, center_nm, linewidth_nm),
        bound_response=toy_response(
            wavelength_nm,
            center_nm + sensitivity_nm_per_coverage * assumed_coverage,
            linewidth_nm,
        ),
        baseline_center_nm=center_nm,
        sensitivity_nm_per_coverage=sensitivity_nm_per_coverage,
        linewidth_nm=linewidth_nm,
    )
