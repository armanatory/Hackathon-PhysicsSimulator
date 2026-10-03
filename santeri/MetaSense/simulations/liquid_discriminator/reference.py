"""Independent lossless TE Fourier-modal reference for a 1D ridge/film grating.

Ey polarization, normal incidence, exp(+i omega t), +z propagation. The ridge
occupies the centered fraction of each period and its gaps contain the top liquid.
Orders=-orders..+orders. A direct 6N boundary-matching solve uses waves anchored
at the appropriate layer ends; propagation factors decay for evanescent modes.
No growing transfer matrices, Allsolve calls, or optimization data are used.

Reference method: Moharam et al., JOSA A 12, 1068 (1995),
https://doi.org/10.1364/JOSAA.12.001068 . This implementation is TE and isotropic
only; the scalar epsilon convolution must not be reused for TM polarization.
"""
from __future__ import annotations

import math
from numbers import Integral

import numpy as np


def _outgoing_q(eigenvalues):
    q = np.sqrt(np.asarray(eigenvalues, dtype=complex))
    # exp(-i*k0*q*d) must decay, hence Im(q)<=0 for exp(+i*omega*t).
    q = np.where(q.imag > 0, -q, q)
    return q


def _epsilon_convolution(mode_numbers, fill_factor, n_liquid, n_sin):
    if fill_factor == 0.0:
        return np.eye(len(mode_numbers)) * n_liquid**2
    if fill_factor == 1.0:
        return np.eye(len(mode_numbers)) * n_sin**2
    difference = mode_numbers[:, None] - mode_numbers[None, :]
    rectangle = fill_factor * np.sinc(difference * fill_factor) * (-1.0)**difference
    return n_liquid**2 * np.eye(len(mode_numbers)) + (n_sin**2-n_liquid**2) * rectangle


def _layer_blocks(W, q, k0, thickness):
    """E/F=i*dE/dz/k0 at top/bottom, for top-forward and bottom-backward amplitudes."""
    propagation = np.exp(-1j*k0*q*thickness)
    V = W*q[None, :]
    WP, VP = W*propagation[None, :], V*propagation[None, :]
    EtA, EtB = W.astype(complex).copy(), WP.copy()
    FtA, FtB = V.copy(), -VP.copy()
    EbA, EbB = WP.copy(), W.astype(complex).copy()
    FbA, FbB = VP.copy(), -V.copy()
    # At exact internal cutoff the two traveling solutions coincide. Use the
    # confluent linear solution E=a-i*k0*z*b, F=b for those columns instead.
    cutoff = np.abs(q) < 1e-7
    if np.any(cutoff):
        EtB[:, cutoff] = 0.0
        FtA[:, cutoff] = 0.0
        FtB[:, cutoff] = W[:, cutoff]
        EbA[:, cutoff] = W[:, cutoff]
        EbB[:, cutoff] = -1j*k0*thickness*W[:, cutoff]
        FbA[:, cutoff] = 0.0
        FbB[:, cutoff] = W[:, cutoff]
    return (EtA, EtB, FtA, FtB, EbA, EbB, FbA, FbB), propagation


def reflectance_transmittance(period_nm, fill_factor, ridge_height_nm,
                             film_thickness_nm, wavelength_nm, n_liquid,
                             n_sin, n_substrate, orders=9):
    """Return all propagating-order R/T plus R0/T0 and complex zeroth amplitudes.

    Thicknesses/period/wavelength are all in nm. Indices are real, positive and
    supplied at this wavelength. ``orders=9`` means 19 retained Fourier modes.
    Amplitudes are referenced at the top of the ridge layer and bottom of the film;
    homogeneous exterior clearance only changes their phases, not their powers.
    This independent reference is for validation, not an Allsolve result.
    """
    names = ("period_nm", "fill_factor", "ridge_height_nm", "film_thickness_nm",
             "wavelength_nm", "n_liquid", "n_sin", "n_substrate")
    inputs = (period_nm, fill_factor, ridge_height_nm, film_thickness_nm,
              wavelength_nm, n_liquid, n_sin, n_substrate)
    values = dict(zip(names, map(float, inputs)))
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("RCWA inputs must be finite real numbers")
    if min(values[name] for name in ("period_nm", "wavelength_nm", "n_liquid", "n_sin", "n_substrate")) <= 0:
        raise ValueError("Period, wavelength, and indices must be positive")
    if not 0 <= values["fill_factor"] <= 1:
        raise ValueError("fill_factor must lie in [0,1]")
    if min(values["ridge_height_nm"], values["film_thickness_nm"]) < 0:
        raise ValueError("Layer thicknesses must be nonnegative")
    if isinstance(orders, bool) or not isinstance(orders, Integral) or orders < 0:
        raise ValueError("orders must be a nonnegative integer")
    period_nm, fill_factor, ridge_height_nm, film_thickness_nm, wavelength_nm, n_liquid, n_sin, n_substrate = (values[name] for name in names)
    modes = np.arange(-orders, orders+1)
    count = len(modes)
    k0 = 2.0*np.pi/wavelength_nm
    kx_over_k0 = modes*wavelength_nm/period_nm
    epsilon = _epsilon_convolution(modes, fill_factor, n_liquid, n_sin)
    eigenvalues, W1 = np.linalg.eigh(epsilon-np.diag(kx_over_k0**2))
    q1 = _outgoing_q(eigenvalues)
    q2 = _outgoing_q(n_sin**2-kx_over_k0**2)
    qtop = _outgoing_q(n_liquid**2-kx_over_k0**2)
    qbottom = _outgoing_q(n_substrate**2-kx_over_k0**2)
    identity = np.eye(count, dtype=complex)
    layer1, propagation1 = _layer_blocks(W1, q1, k0, ridge_height_nm)
    layer2, propagation2 = _layer_blocks(identity, q2, k0, film_thickness_nm)
    Et1A, Et1B, Ft1A, Ft1B, Eb1A, Eb1B, Fb1A, Fb1B = layer1
    Et2A, Et2B, Ft2A, Ft2B, Eb2A, Eb2B, Fb2A, Fb2B = layer2
    zero = np.zeros((count, count), dtype=complex)
    # Unknowns: r, a1(top), b1(bottom), a2(top), b2(bottom), t.
    matrix = np.block([
        [identity, -Et1A, -Et1B, zero, zero, zero],
        [-np.diag(qtop), -Ft1A, -Ft1B, zero, zero, zero],
        [zero, Eb1A, Eb1B, -Et2A, -Et2B, zero],
        [zero, Fb1A, Fb1B, -Ft2A, -Ft2B, zero],
        [zero, zero, zero, Eb2A, Eb2B, -identity],
        [zero, zero, zero, Fb2A, Fb2B, -np.diag(qbottom)],
    ])
    incident = np.zeros(count, dtype=complex)
    incident[orders] = 1.0
    rhs = np.concatenate((-incident, -qtop*incident, np.zeros(4*count, dtype=complex)))
    solution = np.linalg.solve(matrix, rhs)
    reflected, transmitted = solution[:count], solution[-count:]
    # Evanescent orders have Re(q)=0 and carry no far-field normal power.
    Rm = qtop.real/n_liquid * np.abs(reflected)**2
    Tm = qbottom.real/n_liquid * np.abs(transmitted)**2
    R, T = float(np.sum(Rm)), float(np.sum(Tm))
    r0, t0 = reflected[orders], transmitted[orders]
    return {
        "label": "independent_te_rcwa_reference", "synthetic": False,
        "R": R, "T": T, "R0": float(Rm[orders]), "T0": float(Tm[orders]),
        "energy_residual": 1.0-R-T,
        "r0": {"real": float(r0.real), "imag": float(r0.imag)},
        "t0": {"real": float(t0.real), "imag": float(t0.imag)},
        "orders": int(orders), "mode_count": count,
        "order_numbers": modes.tolist(), "R_orders": Rm.tolist(), "T_orders": Tm.tolist(),
        "propagating_top_orders": modes[qtop.real > 0].tolist(),
        "propagating_bottom_orders": modes[qbottom.real > 0].tolist(),
        "linear_system_relative_residual": float(np.linalg.norm(matrix@solution-rhs)/np.linalg.norm(rhs)),
        "maximum_layer_propagation_magnitude": float(max(np.max(np.abs(propagation1)), np.max(np.abs(propagation2)))),
        "phasor_convention": "exp(+i omega t); +z exp(-i k0 q z)",
        "inputs": values,
    }
