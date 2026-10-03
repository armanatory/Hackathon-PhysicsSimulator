"""Build the QuietOffice Allsolve project from an office description.

The model is a 2D top-down slice of the office solved with harmonic acoustic waves:

- the room is air. A rectangular room is one rectangle. Any other outline is the bounding
  rectangle of air with a solid strip along every wall that is not on that rectangle; the
  strips seal the room off from the leftover corners (the SDK has no polygon primitive)
- the talker is a small pulsating disk (normal acceleration on its edge)
- each screen is a thin rectangle left out of the air domain, so it is sound-hard
- the walls absorb (no reflections, the simplest stable choice for a first version)

Every screen position is a project variable, so one project serves every layout: a sweep
overrides the variables and Allsolve remeshes per distinct geometry.
"""

import math
from dataclasses import dataclass
from typing import Any, List, Optional

from ..models.office import AIR_DENSITY, SPEED_OF_SOUND, Office, OptimizationParams

try:
    import allsolve
except ImportError:  # the API can still start and report that the SDK is missing
    allsolve = None

TALKER_RADIUS_M = 0.15
WALL_THICKNESS_M = 0.2
ON_BOUNDS_TOLERANCE_M = 1e-6
ELEMENTS_PER_WAVELENGTH = 6
PRESSURE_MAGNITUDE = "sqrt(pow(harm(2, p), 2) + pow(harm(3, p), 2))"


@dataclass
class OfficeProject:
    """Handles to the pieces of the project that the optimizer needs."""

    project: Any
    physics_set: Any
    air: Any
    mesh_size_m: float


@dataclass
class WallStrip:
    """A solid strip standing in for one wall that is not on the room's bounding rectangle."""

    name: str
    centre_x: float
    centre_y: float
    size_x: float
    size_y: float
    rotation_deg: Optional[float]  # None for walls that run along x or y


def wall_strips(office: Office, thickness: float = WALL_THICKNESS_M) -> List[WallStrip]:
    """Strips for every wall of the outline that does not lie on its bounding rectangle.

    Each strip sits just outside the room, so the room keeps its true size, and reaches one
    thickness past convex corners so neighbouring strips overlap and leave no gap.
    A rectangular room needs none.
    """
    outline = office.outline
    n = len(outline)
    min_x, min_y, max_x, max_y = office.bounds

    def on_bounds(a, b) -> bool:
        tol = ON_BOUNDS_TOLERANCE_M
        return (
            (abs(a.x - min_x) < tol and abs(b.x - min_x) < tol)
            or (abs(a.x - max_x) < tol and abs(b.x - max_x) < tol)
            or (abs(a.y - min_y) < tol and abs(b.y - min_y) < tol)
            or (abs(a.y - max_y) < tol and abs(b.y - max_y) < tol)
        )

    # Positive when the corners run counter-clockwise in x-y.
    signed_area = sum(outline[i].x * outline[(i + 1) % n].y - outline[(i + 1) % n].x * outline[i].y for i in range(n))
    orientation = 1.0 if signed_area > 0 else -1.0

    def convex(i: int) -> bool:
        prev, here, nxt = outline[i - 1], outline[i], outline[(i + 1) % n]
        cross = (here.x - prev.x) * (nxt.y - here.y) - (here.y - prev.y) * (nxt.x - here.x)
        return cross * orientation > 0

    strips: List[WallStrip] = []
    for i in range(n):
        a, b = outline[i], outline[(i + 1) % n]
        length = math.hypot(b.x - a.x, b.y - a.y)
        if length < 1e-9 or on_bounds(a, b):
            continue
        ux, uy = (b.x - a.x) / length, (b.y - a.y) / length
        # Outward normal: to the right of the direction of travel for a counter-clockwise outline.
        nx, ny = uy * orientation, -ux * orientation
        before = thickness if convex(i) else 0.0
        after = thickness if convex((i + 1) % n) else 0.0
        along = length + before + after
        shift = (after - before) / 2
        centre_x = (a.x + b.x) / 2 + ux * shift + nx * thickness / 2
        centre_y = (a.y + b.y) / 2 + uy * shift + ny * thickness / 2
        if abs(uy) < 1e-9:
            size_x, size_y, rotation = along, thickness, None
        elif abs(ux) < 1e-9:
            size_x, size_y, rotation = thickness, along, None
        else:
            size_x, size_y, rotation = along, thickness, math.degrees(math.atan2(uy, ux))
        strips.append(WallStrip(f"wall_{i}", centre_x, centre_y, size_x, size_y, rotation))
    return strips


def screen_variables(index: int) -> List[str]:
    """Names of the project variables that place screen number `index`."""
    return [f"s{index}_on", f"s{index}_x", f"s{index}_y", f"s{index}_w", f"s{index}_h"]


def build_office_project(client: Any, params: OptimizationParams) -> OfficeProject:
    """Create the project: variables, geometry, regions, material and physics."""
    office = params.office
    project = client.create_project(
        name=f"QuietOffice - {params.n_screens} screens",
        description="2D harmonic acoustics of an open-plan office with movable screens",
        labels=["quietoffice"],
        dimension=2,
    )

    first = office.slots[0]
    min_x, min_y, max_x, max_y = office.bounds
    strips = wall_strips(office)
    variables = [
        ("room_x0", min_x, "Room bounding rectangle, smallest x [m]"),
        ("room_y0", min_y, "Room bounding rectangle, smallest y [m]"),
        ("room_w", max_x - min_x, "Room bounding rectangle width [m]"),
        ("room_h", max_y - min_y, "Room bounding rectangle depth [m]"),
        ("src_x", office.source.x, "Talker x [m]"),
        ("src_y", office.source.y, "Talker y [m]"),
        ("src_r", TALKER_RADIUS_M, "Talker radius [m]"),
        ("freq", params.frequencies_hz[0], "Frequency [Hz]"),
        ("accel", 1.0, "Talker surface acceleration [m/s^2]"),
    ]
    for i in range(params.n_screens):
        on, x, y, w, h = screen_variables(i)
        variables += [
            (on, 0, f"Screen {i} present (1) or not (0)"),
            (x, first.x, f"Screen {i} centre x [m]"),
            (y, first.y, f"Screen {i} centre y [m]"),
            (w, params.screen_thickness_m, f"Screen {i} size along x [m]"),
            (h, params.screen_length_m, f"Screen {i} size along y [m]"),
        ]
    project.create_variables(variables)

    builder = project.geometry_builder()
    builder.add_rectangle(
        name="room",
        position=("room_x0", "room_y0"),
        size=("room_w", "room_h"),
        alignment=allsolve.CadAlignment.CORNER,
    )
    for strip in strips:
        builder.add_rectangle(
            name=strip.name,
            position=(strip.centre_x, strip.centre_y),
            size=(strip.size_x, strip.size_y),
            rotation=None if strip.rotation_deg is None else (0, 0, strip.rotation_deg),
        )
    builder.add_disk(name="talker", position=("src_x", "src_y"), radius="src_r")
    for i in range(params.n_screens):
        on, x, y, w, h = screen_variables(i)
        builder.add_rectangle(
            name=f"screen_{i}",
            position=(x, y),
            size=(w, h),
            enabled=f"eq({on}, 1)",
        )
    # The implicit final fragment-all splits the room into air + walls + talker + screens.
    builder.build(print_logs=False, on_error=allsolve.OnError.RAISE)

    everything = project.create_region_rule(
        name="everything",
        entity_type=allsolve.Region.SURFACE,
        bounding_box=(("room_x0 - 1", "room_y0 - 1", -1), ("room_x0 + room_w + 1", "room_y0 + room_h + 1", 1)),
    )
    # Talker and screens are all far smaller than the room, so a size filter finds them.
    obstacle_size = max(params.screen_length_m, 2 * TALKER_RADIUS_M) * 1.05
    obstacles = project.create_region_rule(
        name="obstacles",
        entity_type=allsolve.Region.SURFACE,
        max_size=(obstacle_size, obstacle_size, 1),
    )
    solid = obstacles  # everything that is not air
    movable = obstacles  # talker and screens: their edges are not walls
    if strips:
        # Wall strips are found by the name they were built with. Their small corner overlaps
        # also pass the size filter above, so take them back out of the movable set.
        strip_rules = [
            project.create_region_rule(
                name=f"{strip.name}_solid",
                entity_type=allsolve.Region.SURFACE,
                attribute_path=[("name", strip.name)],
            )
            for strip in strips
        ]
        wall_solid = project.create_region_computed(
            name="wall_solid",
            entity_type=allsolve.Region.SURFACE,
            operation=allsolve.RegionOperation.UNION,
            source_regions=[rule.id for rule in strip_rules],
        )
        movable = project.create_region_computed(
            name="movable",
            entity_type=allsolve.Region.SURFACE,
            operation=allsolve.RegionOperation.DIFFERENCE,
            source_regions=[obstacles.id, wall_solid.id],
        )
        solid = project.create_region_computed(
            name="solid",
            entity_type=allsolve.Region.SURFACE,
            operation=allsolve.RegionOperation.UNION,
            source_regions=[obstacles.id, wall_solid.id],
        )
    air = project.create_region_computed(
        name="air",
        entity_type=allsolve.Region.SURFACE,
        operation=allsolve.RegionOperation.DIFFERENCE,
        source_regions=[everything.id, solid.id],
    )
    talker = project.create_region_rule(
        name="talker",
        entity_type=allsolve.Region.SURFACE,
        bounding_box=(
            ("src_x - 1.1 * src_r", "src_y - 1.1 * src_r", -1),
            ("src_x + 1.1 * src_r", "src_y + 1.1 * src_r", 1),
        ),
    )
    talker_edge = project.create_region_computed(
        name="talker_edge",
        entity_type=allsolve.Region.CURVE,
        operation=allsolve.RegionOperation.BOUNDARY,
        source_regions=[talker.id],
    )
    if not strips:
        walls = project.create_region_computed(
            name="walls",
            entity_type=allsolve.Region.CURVE,
            operation=allsolve.RegionOperation.BOUNDARY,
            source_regions=[everything.id],
        )
    else:
        # Every edge of the air that is not the talker or a screen is a wall.
        air_edges = project.create_region_computed(
            name="air_edges",
            entity_type=allsolve.Region.CURVE,
            operation=allsolve.RegionOperation.BOUNDARY,
            source_regions=[air.id],
        )
        movable_edges = project.create_region_computed(
            name="movable_edges",
            entity_type=allsolve.Region.CURVE,
            operation=allsolve.RegionOperation.BOUNDARY,
            source_regions=[movable.id],
        )
        walls = project.create_region_computed(
            name="walls",
            entity_type=allsolve.Region.CURVE,
            operation=allsolve.RegionOperation.DIFFERENCE,
            source_regions=[air_edges.id, movable_edges.id],
        )

    project.create_material(
        name="Air",
        description="Air, 20 C",
        color="#99D9FF",
        target_region=air,
        density=AIR_DENSITY,
        speed_of_sound=SPEED_OF_SOUND,
    )

    physics_set = project.get_default_physics_set()
    acoustics = physics_set.add_physics(allsolve.Physics.AcousticWaves(target=air))
    acoustics.add_interactions(
        [
            allsolve.Interaction.AcousticWavesNormalAcceleration(
                name="Talker",
                acoustic_waves_normal_acceleration="accel",
                target=talker_edge,
            ),
            allsolve.Interaction.AcousticWavesAbsorbingBoundary(name="Walls", target=walls),
        ]
    )

    mesh_size = SPEED_OF_SOUND / (max(params.frequencies_hz) * ELEMENTS_PER_WAVELENGTH)
    return OfficeProject(project=project, physics_set=physics_set, air=air, mesh_size_m=mesh_size)


def desk_output_name(index: int) -> str:
    return f"desk_{index:02d}"


REFERENCE_OUTPUT = "ref_1m"


def add_probe_outputs(simulation: Any, params: OptimizationParams) -> None:
    """One value output per desk, plus the 1 m reference point used for calibration."""
    office = params.office
    probes = [(desk_output_name(i), desk.x, desk.y) for i, desk in enumerate(office.desks)]
    probes.append((REFERENCE_OUTPUT, office.source.x + 1.0, office.source.y))
    simulation.add_outputs(
        [
            allsolve.Output.ValueOutput(
                name=name,
                expression=f"interpolate(reg.air, {PRESSURE_MAGNITUDE}, [{x}, {y}, 0])",
            )
            for name, x, y in probes
        ]
    )
