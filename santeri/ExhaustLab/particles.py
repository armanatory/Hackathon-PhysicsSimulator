"""Local particle postprocessing for a convex rectangular collector channel.

This module never generates solver fields or submits Allsolve jobs. The input
velocity and electric field must be supplied by the separately verified field
export path. Analytic fields belong in validation tests only. All units are SI.
See PARTICLE_MODEL.md for assumptions, provenance, and validation requirements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping, Protocol

import numpy as np


ELEMENTARY_CHARGE_C = 1.602176634e-19


@dataclass(frozen=True)
class RectangularChannel:
    """x is axial, y is plate gap, z is the finite plate span; origin at inlet."""

    length_m: float = 0.06
    gap_m: float = 0.006
    span_m: float = 0.02

    def __post_init__(self) -> None:
        if any(not math.isfinite(v) or v <= 0 for v in self.extent_m):
            raise ValueError("Channel dimensions must be finite and positive.")

    @property
    def extent_m(self) -> np.ndarray:
        return np.array([self.length_m, self.gap_m, self.span_m])


@dataclass(frozen=True)
class ParticleModel:
    diameter_m: float = 1e-6
    charge_e: float = 30.0
    gas_viscosity_pa_s: float = 1.81e-5
    mean_free_path_m: float = 65e-9

    def __post_init__(self) -> None:
        positive = (self.diameter_m, self.gas_viscosity_pa_s)
        if any(not math.isfinite(v) or v <= 0 for v in positive):
            raise ValueError("Diameter and gas viscosity must be finite and positive.")
        if not math.isfinite(self.mean_free_path_m) or self.mean_free_path_m < 0:
            raise ValueError("Mean free path must be finite and nonnegative.")
        if not math.isfinite(self.charge_e):
            raise ValueError("Charge in elementary charges must be finite.")

    @property
    def cunningham_factor(self) -> float:
        if self.mean_free_path_m == 0:
            return 1.0
        kn = 2 * self.mean_free_path_m / self.diameter_m
        return 1 + kn * (1.257 + 0.4 * math.exp(-1.1 / kn))

    @property
    def electrical_mobility_m2_v_s(self) -> float:
        """Signed mobility: positive charge drifts along E, negative against E."""
        return (
            self.charge_e * ELEMENTARY_CHARGE_C * self.cunningham_factor
            / (3 * math.pi * self.gas_viscosity_pa_s * self.diameter_m)
        )

    def slip_reynolds_number(self, electric_v_m: np.ndarray, gas_density_kg_m3: float = 1.2) -> np.ndarray:
        """Diagnostic for the Stokes assumption, based on electrical slip speed."""
        if not math.isfinite(gas_density_kg_m3) or gas_density_kg_m3 <= 0:
            raise ValueError("Gas density must be finite and positive.")
        slip = abs(self.electrical_mobility_m2_v_s) * np.linalg.norm(electric_v_m, axis=-1)
        return gas_density_kg_m3 * self.diameter_m * slip / self.gas_viscosity_pa_s


@dataclass(frozen=True)
class SampledFields:
    velocity_m_s: np.ndarray
    electric_v_m: np.ndarray
    covered: np.ndarray


class FieldSampler(Protocol):
    def sample(self, points_m: np.ndarray) -> SampledFields: ...


def _vectors(values: np.ndarray, label: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 2 or array.shape[1] != 3 or not np.isfinite(array).all():
        raise ValueError(f"{label} must have shape (N, 3) and finite SI values.")
    return array


class ScatteredFieldSampler:
    """Piecewise-linear tetrahedral interpolation; no out-of-hull extrapolation.

    The convex-hull interpolation is valid only for this convex, unobstructed
    rectangular fluid domain. It must not be reused across internal baffles,
    holes, or disconnected fluid regions; those require original mesh cells.
    The input points must cover the actual fluid boundaries, including inlet.
    Duplicate coordinates are merged only when all six field values agree.
    """

    def __init__(
        self,
        points_m: np.ndarray,
        velocity_m_s: np.ndarray,
        electric_v_m: np.ndarray,
        *,
        provenance: Mapping[str, Any] | None = None,
    ) -> None:
        # Optional irregular-cloud support; the primary regular-grid path
        # below requires NumPy only and does not import SciPy.
        try:
            from scipy.interpolate import LinearNDInterpolator
            from scipy.spatial import Delaunay, QhullError
        except ImportError as exc:
            raise ImportError("Scattered fields require optional SciPy; use RegularGridFieldSampler for regular exports.") from exc
        points = _vectors(points_m, "points_m")
        velocity = _vectors(velocity_m_s, "velocity_m_s")
        electric = _vectors(electric_v_m, "electric_v_m")
        if len(points) != len(velocity) or len(points) != len(electric):
            raise ValueError("Coordinates, velocity, and electric field need identical row counts.")
        values = np.column_stack((velocity, electric))
        unique_points, first, inverse = np.unique(points, axis=0, return_index=True, return_inverse=True)
        if not np.allclose(values, values[first][inverse], rtol=1e-10, atol=1e-12):
            raise ValueError("Duplicate field coordinates contain inconsistent values.")
        if len(unique_points) < 4:
            raise ValueError("At least four non-coplanar field points are required.")
        self._origin = unique_points.min(axis=0)
        self._scale = np.ptp(unique_points, axis=0)
        if (self._scale <= 0).any():
            raise ValueError("Field point cloud must span all three physical axes.")
        # Normalize coordinates to keep a thin channel well conditioned. This
        # preserves affine interpolation and physical units of the field data.
        try:
            tetrahedra = Delaunay((unique_points - self._origin) / self._scale)
        except QhullError as exc:
            raise ValueError("Field coordinates cannot form a valid 3D interpolation mesh.") from exc
        self._interpolator = LinearNDInterpolator(tetrahedra, values[first], fill_value=np.nan)
        self.provenance = dict(provenance or {})

    def sample(self, points_m: np.ndarray) -> SampledFields:
        points = _vectors(points_m, "query points_m")
        values = np.asarray(self._interpolator((points - self._origin) / self._scale))
        covered = np.isfinite(values).all(axis=1)
        return SampledFields(values[:, :3], values[:, 3:], covered)


class RegularGridFieldSampler:
    """NumPy trilinear interpolation on endpoint-inclusive rectilinear axes.

    Arrays have shape (nx, ny, nz, 3), with component order (x, y, z).
    Coordinates and field values must be finite. Query points beyond any
    supplied axis are marked uncovered and return NaN, never extrapolated.
    Cells may be nonuniform; no axis reordering or inferred units are applied.
    """

    def __init__(
        self,
        x_m: np.ndarray,
        y_m: np.ndarray,
        z_m: np.ndarray,
        velocity_m_s: np.ndarray,
        electric_v_m: np.ndarray,
        *,
        provenance: Mapping[str, Any] | None = None,
    ) -> None:
        axes = tuple(np.asarray(axis, dtype=float) for axis in (x_m, y_m, z_m))
        for axis in axes:
            if axis.ndim != 1 or len(axis) < 2 or not np.isfinite(axis).all() or not (np.diff(axis) > 0).all():
                raise ValueError("Each grid axis needs at least two finite, strictly increasing SI coordinates.")
        shape = tuple(len(axis) for axis in axes) + (3,)
        velocity = np.asarray(velocity_m_s, dtype=float)
        electric = np.asarray(electric_v_m, dtype=float)
        if velocity.shape != shape or electric.shape != shape:
            raise ValueError(f"Regular-grid fields must have shape {shape} and component order (x,y,z).")
        if not np.isfinite(velocity).all() or not np.isfinite(electric).all():
            raise ValueError("Every exported grid field value must be finite; missing samples must be repaired upstream.")
        self.axes_m = tuple(axis.copy() for axis in axes)
        self.velocity_m_s = velocity.copy()
        self.electric_v_m = electric.copy()
        self.provenance = dict(provenance or {})

    def sample(self, points_m: np.ndarray) -> SampledFields:
        points = _vectors(points_m, "query points_m")
        covered = np.ones(len(points), dtype=bool)
        for component, axis in enumerate(self.axes_m):
            covered &= (points[:, component] >= axis[0]) & (points[:, component] <= axis[-1])
        velocity = np.full((len(points), 3), np.nan)
        electric = np.full((len(points), 3), np.nan)
        query = points[covered]
        if len(query):
            indices = []
            fractions = []
            for component, axis in enumerate(self.axes_m):
                lower = np.clip(np.searchsorted(axis, query[:, component], side="right") - 1, 0, len(axis) - 2)
                indices.append(lower)
                fractions.append((query[:, component] - axis[lower]) / (axis[lower + 1] - axis[lower]))
            result_u = np.zeros((len(query), 3))
            result_e = np.zeros((len(query), 3))
            for i in (0, 1):
                for j in (0, 1):
                    for k in (0, 1):
                        cell = (indices[0] + i, indices[1] + j, indices[2] + k)
                        weight = (
                            (fractions[0] if i else 1 - fractions[0])
                            * (fractions[1] if j else 1 - fractions[1])
                            * (fractions[2] if k else 1 - fractions[2])
                        )[:, None]
                        result_u += weight * self.velocity_m_s[cell]
                        result_e += weight * self.electric_v_m[cell]
            velocity[covered] = result_u
            electric[covered] = result_e
        return SampledFields(velocity, electric, covered)


@dataclass(frozen=True)
class InletSamples:
    points_m: np.ndarray
    flux_weights_m3_s: np.ndarray

    def __post_init__(self) -> None:
        points = _vectors(self.points_m, "inlet points_m")
        weights = np.asarray(self.flux_weights_m3_s, dtype=float)
        if weights.shape != (len(points),) or not np.isfinite(weights).all() or (weights < 0).any():
            raise ValueError("Inlet flux weights must be a finite nonnegative vector matching points.")
        if not (weights.sum() > 0):
            raise ValueError("Positive inlet flow is required.")
        object.__setattr__(self, "points_m", points.copy())
        object.__setattr__(self, "flux_weights_m3_s", weights.copy())

    @property
    def normalized_weights(self) -> np.ndarray:
        return self.flux_weights_m3_s / self.flux_weights_m3_s.sum()


def flux_weighted_inlet(
    sampler: FieldSampler,
    channel: RectangularChannel,
    *,
    n_y: int = 24,
    n_z: int = 16,
) -> InletSamples:
    """Deterministic cell-center quadrature of positive carrier-gas inlet flux.

    A uniform inlet aerosol concentration is assumed. Each sample carries
    ux(y,z)*cell_area; no random sampling or unweighted particle counts are used.
    Reverse flow is rejected because the baseline assumes a unidirectional inlet.
    """
    if not isinstance(n_y, int) or not isinstance(n_z, int) or min(n_y, n_z) <= 0:
        raise ValueError("Inlet grid counts must be positive integers.")
    y = (np.arange(n_y) + 0.5) * channel.gap_m / n_y
    z = (np.arange(n_z) + 0.5) * channel.span_m / n_z
    yy, zz = np.meshgrid(y, z, indexing="ij")
    points = np.column_stack((np.zeros(yy.size), yy.ravel(), zz.ravel()))
    fields = sampler.sample(points)
    if not np.asarray(fields.covered).all() or not np.isfinite(fields.velocity_m_s).all():
        raise ValueError("Exported fields do not cover the complete deterministic inlet sample grid.")
    ux = np.asarray(fields.velocity_m_s)[:, 0]
    if (ux < -1e-12).any():
        raise ValueError("Reverse carrier-gas flow on the inlet is outside the baseline model.")
    area = channel.gap_m * channel.span_m / (n_y * n_z)
    return InletSamples(points, np.maximum(ux, 0) * area)


@dataclass
class TrajectoryResult:
    """Fractions always use total inlet weight, including unresolved trajectories."""

    states: np.ndarray
    reasons: np.ndarray
    terminal_points_m: np.ndarray
    terminal_times_s: np.ndarray
    normalized_weights: np.ndarray
    inlet_flux_m3_s: float
    max_step_s: float
    max_time_s: float
    paths: dict[int, np.ndarray] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "particle_count": len(self.states),
            "inlet_flux_m3_s": self.inlet_flux_m3_s,
            "max_step_s": self.max_step_s,
            "max_time_s": self.max_time_s,
        }
        for state in ("captured", "outlet", "unresolved"):
            selected = self.states == state
            report[f"{state}_count"] = int(selected.sum())
            report[f"{state}_fraction"] = float(self.normalized_weights[selected].sum())
        report["capture_upper_bound"] = report["captured_fraction"] + report["unresolved_fraction"]
        report["unresolved_reasons"] = {
            str(reason): int(((self.states == "unresolved") & (self.reasons == reason)).sum())
            for reason in np.unique(self.reasons[self.states == "unresolved"])
        }
        report["captured_by_wall"] = {
            wall: {
                "count": int(((self.states == "captured") & (self.reasons == wall)).sum()),
                "fraction": float(self.normalized_weights[(self.states == "captured") & (self.reasons == wall)].sum()),
            }
            for wall in ("wall_y_min", "wall_y_max", "wall_z_min", "wall_z_max")
        }
        return report


def _segment_boundary(points: np.ndarray, delta: np.ndarray, extent: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Earliest intersection fraction and plane number; lateral walls win ties."""
    fractions = np.full((len(points), 6), np.inf)
    # Order gives wall capture precedence for an exact wall/outlet corner tie.
    planes = ((1, 0.0), (1, extent[1]), (2, 0.0), (2, extent[2]), (0, 0.0), (0, extent[0]))
    for plane, (axis, boundary) in enumerate(planes):
        direction = delta[:, axis]
        outward = direction < 0 if boundary == 0 else direction > 0
        np.divide(boundary - points[:, axis], direction, out=fractions[:, plane], where=outward)
    fractions[(fractions < 0) | (fractions > 1)] = np.inf
    hit = np.argmin(fractions, axis=1)
    return fractions[np.arange(len(points)), hit], hit


def _particle_velocity(sampler: FieldSampler, positions: np.ndarray, particle: ParticleModel) -> tuple[np.ndarray, np.ndarray]:
    fields = sampler.sample(positions)
    velocity = np.asarray(fields.velocity_m_s) + particle.electrical_mobility_m2_v_s * np.asarray(fields.electric_v_m)
    if velocity.shape != positions.shape or np.asarray(fields.covered).shape != (len(positions),):
        raise ValueError("Field sampler returned an invalid output shape.")
    covered = np.asarray(fields.covered, dtype=bool) & np.isfinite(velocity).all(axis=1)
    return velocity, covered


def integrate_trajectories(
    sampler: FieldSampler,
    channel: RectangularChannel,
    particle: ParticleModel,
    inlet: InletSamples,
    *,
    max_step_s: float = 0.01,
    max_time_s: float = 20.0,
    track_indices: tuple[int, ...] = (),
    path_stride: int = 10,
) -> TrajectoryResult:
    """Explicit midpoint integration of dx/dt = u + q*Cc*E/(3*pi*mu*d).

    Segment/plane intersection records the first wall or outlet event. If the
    first half-step reaches a boundary, its local linear event is terminal.
    This terminal approximation is tested by halving max_step_s. Uncovered
    interpolation points and the time limit are unresolved, never outlets.
    """
    if any(not math.isfinite(v) or v <= 0 for v in (max_step_s, max_time_s)):
        raise ValueError("Maximum step and integration time must be finite and positive.")
    if not isinstance(path_stride, int) or path_stride <= 0:
        raise ValueError("path_stride must be a positive integer.")
    points = inlet.points_m.copy()
    extent = channel.extent_m
    inside = (points[:, 0] >= 0) & (points[:, 0] < extent[0])
    inside &= (points[:, 1:] > 0).all(axis=1) & (points[:, 1:] < extent[1:]).all(axis=1)
    if not inside.all():
        raise ValueError("Seed centers must be in the open lateral channel interior, before the outlet.")
    if len(set(track_indices)) != len(track_indices) or any(i < 0 or i >= len(points) for i in track_indices):
        raise ValueError("track_indices must contain unique valid seed indices.")
    states = np.full(len(points), "active", dtype="U10")
    reasons = np.full(len(points), "", dtype="U32")
    terminal_times = np.zeros(len(points))
    tracks: dict[int, list[np.ndarray]] = {i: [np.r_[0.0, points[i]]] for i in track_indices}
    time_s = 0.0

    def finish(ids: np.ndarray, origins: np.ndarray, delta: np.ndarray, fractions: np.ndarray, planes: np.ndarray, dt: float) -> None:
        points[ids] = origins + fractions[:, None] * delta
        # Snap only the analytically intersected coordinate to its exact plane,
        # avoiding floating-point drift beyond endpoint-inclusive grid axes.
        plane_axes = np.array([1, 1, 2, 2, 0, 0])
        plane_values = np.array([0, extent[1], 0, extent[2], 0, extent[0]])
        points[ids, plane_axes[planes]] = plane_values[planes]
        terminal_times[ids] = time_s + fractions * dt
        states[ids] = np.where(planes < 4, "captured", np.where(planes == 5, "outlet", "unresolved"))
        labels = np.array(["wall_y_min", "wall_y_max", "wall_z_min", "wall_z_max", "inlet_backflow", "outlet"])
        reasons[ids] = labels[planes]
        # A midpoint may be covered while the proposed terminal plane is not.
        # Require endpoint coverage before accepting a wall/outlet conclusion.
        _, covered = _particle_velocity(sampler, points[ids], particle)
        states[ids[~covered]] = "unresolved"
        reasons[ids[~covered]] = "field_coverage_boundary"

    steps = 0
    while time_s < max_time_s and (states == "active").any():
        dt = min(max_step_s, max_time_s - time_s)
        active = np.flatnonzero(states == "active")
        origins = points[active].copy()
        v0, covered = _particle_velocity(sampler, origins, particle)
        missing = active[~covered]
        states[missing] = "unresolved"
        reasons[missing] = "field_coverage_start"
        terminal_times[missing] = time_s
        active, origins, v0 = active[covered], origins[covered], v0[covered]
        if not len(active):
            break
        euler_delta = dt * v0
        fractions, planes = _segment_boundary(origins, euler_delta, extent)
        early = fractions <= 0.5
        if early.any():
            finish(active[early], origins[early], euler_delta[early], fractions[early], planes[early], dt)
        active, origins, euler_delta = active[~early], origins[~early], euler_delta[~early]
        if len(active):
            midpoint = origins + 0.5 * euler_delta
            vmid, covered = _particle_velocity(sampler, midpoint, particle)
            missing = active[~covered]
            states[missing] = "unresolved"
            reasons[missing] = "field_coverage_midpoint"
            terminal_times[missing] = time_s
            active, origins, vmid = active[covered], origins[covered], vmid[covered]
            delta = dt * vmid
            fractions, planes = _segment_boundary(origins, delta, extent)
            event = np.isfinite(fractions)
            if event.any():
                finish(active[event], origins[event], delta[event], fractions[event], planes[event], dt)
            continuing = active[~event]
            points[continuing] = origins[~event] + delta[~event]
            terminal_times[continuing] = time_s + dt
        time_s += dt
        steps += 1
        for index, path in tracks.items():
            if states[index] != "active" and path[-1][0] < terminal_times[index]:
                path.append(np.r_[terminal_times[index], points[index]])
            elif states[index] == "active" and steps % path_stride == 0:
                path.append(np.r_[time_s, points[index]])

    active = states == "active"
    states[active] = "unresolved"
    reasons[active] = "time_limit"
    for index, path in tracks.items():
        if path[-1][0] < terminal_times[index]:
            path.append(np.r_[terminal_times[index], points[index]])
    return TrajectoryResult(
        states=states,
        reasons=reasons,
        terminal_points_m=points,
        terminal_times_s=terminal_times,
        normalized_weights=inlet.normalized_weights,
        inlet_flux_m3_s=float(inlet.flux_weights_m3_s.sum()),
        max_step_s=max_step_s,
        max_time_s=max_time_s,
        paths={index: np.asarray(path) for index, path in tracks.items()},
    )


def timestep_convergence(
    sampler: FieldSampler,
    channel: RectangularChannel,
    particle: ParticleModel,
    inlet: InletSamples,
    *,
    max_step_s: float = 0.01,
    max_time_s: float = 20.0,
    levels: int = 3,
) -> dict[str, Any]:
    """Same inlet grid at dt, dt/2, dt/4; report changes without declaring success.

    The caller must choose capture-fraction and terminal-time tolerances and
    also converge the inlet grid, exported field sampling, and solver mesh.
    """
    if not isinstance(levels, int) or levels < 2:
        raise ValueError("At least two timestep-convergence levels are required.")
    results = [
        integrate_trajectories(sampler, channel, particle, inlet,
            max_step_s=max_step_s / (2 ** level), max_time_s=max_time_s)
        for level in range(levels)
    ]
    reports = [result.summary() for result in results]
    changes = []
    for coarse, fine, coarse_report, fine_report in zip(results, results[1:], reports, reports[1:]):
        resolved_same = (coarse.states == fine.states) & (fine.states != "unresolved")
        changes.append({
            "coarse_step_s": coarse.max_step_s,
            "fine_step_s": fine.max_step_s,
            "capture_fraction_absolute_change": abs(fine_report["captured_fraction"] - coarse_report["captured_fraction"]),
            "outlet_fraction_absolute_change": abs(fine_report["outlet_fraction"] - coarse_report["outlet_fraction"]),
            "changed_classification_weight": float(fine.normalized_weights[coarse.states != fine.states].sum()),
            "max_terminal_time_change_s": float(np.max(np.abs(fine.terminal_times_s[resolved_same] - coarse.terminal_times_s[resolved_same]))) if resolved_same.any() else None,
        })
    return {"levels": reports, "successive_changes": changes}
