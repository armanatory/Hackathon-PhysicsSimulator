"""The solver script that lets one cloud machine solve many layouts.

A normal sweep gives every solve its own machine, and Allsolve runs at most 100 at once. A
machine spends most of that time starting up and loading the mesh; the solve itself is short.
In the one-mesh model a layout is only a different air density, so a machine that has loaded
the mesh can go on to solve one layout after another.

The script written here replaces the generated solve. The sweep variable `batch` tells a
machine which share of the layouts is its own. It solves every (layout, source, band) of that
share and returns all probe pressures as one list.
"""

from typing import List, Sequence

from ..models.office import AIR_DENSITY, OptimizationParams
from .project_builder import SCREEN_DENSITY_RATIO

BATCH_VARIABLE = "batch"
PRESSURES_OUTPUT = "pressures"  # [layout][source][band][probe], flattened
SECONDS_OUTPUT = "solve_seconds"  # one per solve, in the same order


def probe_points(params: OptimizationParams) -> List[List[float]]:
    """Where the pressure is read: every listening point, then the 1 m point of each source."""
    office = params.office
    points = [[p.x, p.y, 0.0] for p in office.receivers()]
    for s in range(len(office.sources)):
        ref = office.reference_point(s)
        points.append([ref.x, ref.y, 0.0])
    return points


def batch_script(params: OptimizationParams, layouts: Sequence[Sequence[int]], layouts_per_machine: int, frequencies: Sequence[float]) -> str:
    """Python for the cloud solver: solve this machine's share of `layouts` on the loaded mesh.

    `frequencies` are the bands this simulation solves: those its mesh is fine enough for.
    """
    office = params.office
    slots = {}
    for slot in office.slots:
        vertical = slot.orientation == "v"
        slots[slot.id] = (
            slot.x,
            slot.y,
            params.screen_thickness_m if vertical else params.screen_length_m,
            params.screen_length_m if vertical else params.screen_thickness_m,
        )
    points = [value for point in probe_points(params) for value in point]
    edges = ", ".join(f"reg.source_{s}_edge" for s in range(len(office.sources)))
    return f'''import time as _time

_SLOTS = {slots!r}  # slot id -> (centre x, centre y, size x, size y)
_LAYOUTS = {[list(layout) for layout in layouts]!r}
_FREQUENCIES = {list(frequencies)!r}
_POINTS = {points!r}
_SOURCE_EDGES = [{edges}]
_PER_MACHINE = {layouts_per_machine}

_first = int(round(expr.{BATCH_VARIABLE})) * _PER_MACHINE
_magnitude = qs.sqrt(qs.pow(qs.harm(2, fld.p, 3), 2.0) + qs.pow(qs.harm(3, fld.p, 3), 2.0))
_pressures, _seconds = [], []
for _layout in _LAYOUTS[_first:_first + _PER_MACHINE]:
    # A screen is air made very heavy inside its rectangle, exactly as in the material.
    _rho = qs.expression({AIR_DENSITY})
    for _slot in _layout:
        _sx, _sy, _sw, _sh = _SLOTS[_slot]
        _rho = _rho + {AIR_DENSITY * (SCREEN_DENSITY_RATIO - 1)} * qs.ifpositive(_sw / 2.0 - qs.abs(qs.getx() - _sx), 1.0, 0.0) * qs.ifpositive(_sh / 2.0 - qs.abs(qs.gety() - _sy), 1.0, 0.0)
    for _edge in _SOURCE_EDGES:
        for _frequency in _FREQUENCIES:
            _started = _time.perf_counter()
            qs.setfundamentalfrequency(_frequency)
            _form = qs.formulation()
            _form += qs.integral(reg.air, 3, qs.predefinedacousticwave(qs.dof(fld.p), qs.tf(fld.p), par.c(), _rho, 0, "oo2"))
            _form += qs.integral(_edge, 3, (expr.accel * qs.sn(1)) * qs.tf(fld.p))
            _form += qs.integral(reg.walls, 3, qs.predefinedacousticradiation(qs.dof(fld.p), qs.tf(fld.p), par.c(), _rho, 0.0))
            _form.allsolve(relrestol=1e-06, maxnumit=1000, nltol=1e-05, maxnumnlit=1000, relaxvalue=-1)
            _pressures += list(qs.allinterpolate(reg.air, _magnitude, _POINTS))
            _seconds.append(_time.perf_counter() - _started)
qs.setoutputvalue("{PRESSURES_OUTPUT}", _pressures)
qs.setoutputvalue("{SECONDS_OUTPUT}", _seconds)
print("QuietOffice batch", int(round(expr.{BATCH_VARIABLE})), "solved", len(_seconds), "systems in", round(sum(_seconds), 2), "s")
'''
