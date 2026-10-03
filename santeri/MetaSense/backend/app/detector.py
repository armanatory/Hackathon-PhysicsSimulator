"""Synthetic detector noise for the surrogate demonstration only."""

import numpy as np
from numpy.typing import NDArray


def add_synthetic_noise(
    response: NDArray[np.float64], noise_std_fraction: float, seed: int
) -> NDArray[np.float64]:
    rng = np.random.default_rng(seed)
    return np.clip(
        response + rng.normal(0.0, noise_std_fraction, size=response.shape),
        0.0,
        1.0,
    )
