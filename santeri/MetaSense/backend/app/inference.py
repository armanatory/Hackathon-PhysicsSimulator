"""Fit assumed coverage back to the same toy response family."""

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize_scalar

from .optics import toy_response


def estimate_toy_coverage(
    wavelength_nm: NDArray[np.float64],
    noisy_response: NDArray[np.float64],
    baseline_center_nm: float,
    sensitivity_nm_per_coverage: float,
    linewidth_nm: float,
) -> float:
    """A toy inverse fit, not calibrated concentration or binding inference."""

    def residual(coverage: float) -> float:
        predicted = toy_response(
            wavelength_nm,
            baseline_center_nm + sensitivity_nm_per_coverage * coverage,
            linewidth_nm,
        )
        return float(np.mean((predicted - noisy_response) ** 2))

    fit = minimize_scalar(residual, bounds=(0.0, 1.0), method="bounded")
    if not fit.success:
        raise RuntimeError("Synthetic coverage fitting failed")
    return float(np.clip(fit.x, 0.0, 1.0))
