"""Build the QuietOffice Allsolve project in 3D.

Same idea as the 2D builder, with height:

- the room is its outline pulled up to the ceiling. As in 2D, a non-rectangular room is the
  bounding box of air plus full-height wall strips
- each noise source is a small pulsating sphere at mouth height, solved one at a time
- each screen is a box standing on the floor with the chosen panel height, so sound can pass
  over it
- the floor reflects. Walls and ceiling absorb. Absorbing panels absorb too; hard panels reflect
- pressure is read at ear height above each desk

A 3D wave solve is far larger than a 2D one: the number of unknowns grows with the cube of
frequency. `estimate_unknowns` is used to pick the solver and machine size.
"""

from typing import Any

from ..models.office import AIR_DENSITY, SPEED_OF_SOUND, OptimizationParams
from .project_builder import (
    ELEMENTS_PER_WAVELENGTH,
    TALKER_RADIUS_M,
    OfficeProject,
    screen_variables,
    source_variables,
    wall_strips,
)

try:
    import allsolve
except ImportError:  # the API can still start and report that the SDK is missing
    allsolve = None

# Second-order tetrahedra: about 8.5 elements per h^3 of volume and 1.36 unknowns per element.
UNKNOWNS_PER_CUBIC_MESH_SIZE = 11.5
DIRECT_SOLVER_LIMIT = 700_000


def room_volume(params: OptimizationParams) -> float:
    """Volume of the meshed air, taken as the bounding box of the room."""
    min_x, min_y, max_x, max_y = params.office.bounds
    return (max_x - min_x) * (max_y - min_y) * params.office.ceiling_height_m


def estimate_unknowns(params: OptimizationParams) -> int:
    """Rough number of pressure unknowns in one 3D solve at the highest frequency."""
    mesh_size = SPEED_OF_SOUND / (max(params.frequencies_hz) * ELEMENTS_PER_WAVELENGTH)
    return int(UNKNOWNS_PER_CUBIC_MESH_SIZE * room_volume(params) / mesh_size**3)


def build_office_project_3d(client: Any, params: OptimizationParams, log: Any = None) -> OfficeProject:
    """Create the 3D project: variables, geometry, regions, material and physics.

    `log` is an optional RunLog that records every request made to Allsolve.
    """

    def sent(step: str, message: str, data: Any = None) -> None:
        if log is not None:
            log.add("sent", step, message, data)

    def received(step: str, message: str, data: Any = None) -> None:
        if log is not None:
            log.add("received", step, message, data)

    office = params.office
    project = client.create_project(
        name=f"QuietOffice 3D - {params.n_screens} screens",
        description="3D harmonic acoustics of an open-plan office with movable screens",
        labels=["quietoffice", "3d"],
        dimension=3,
    )

    received("project", f"Allsolve created 3D project {project.id}", {"project_id": project.id, "dimension": 3})

    first = office.slots[0]
    min_x, min_y, max_x, max_y = office.bounds
    ceiling = office.ceiling_height_m
    panel_height = min(params.screen_height_m, ceiling)
    strips = wall_strips(office)
    variables = [
        ("room_x0", min_x, "Room bounding box, smallest x [m]"),
        ("room_y0", min_y, "Room bounding box, smallest y [m]"),
        ("room_w", max_x - min_x, "Room bounding box width [m]"),
        ("room_h", max_y - min_y, "Room bounding box depth [m]"),
        ("room_z", ceiling, "Ceiling height [m]"),
        ("src_z", params.source_height_m, "Source height [m]"),
        ("src_r", TALKER_RADIUS_M, "Source radius [m]"),
        ("panel_z", panel_height, "Screen height [m]"),
        ("freq", params.frequencies_hz[0], "Frequency [Hz]"),
        ("accel", 1.0, "Source surface acceleration [m/s^2]"),
    ]
    for i, source in enumerate(office.sources):
        sx, sy, amp = source_variables(i)
        variables += [
            (sx, source.x, f"Source {i} x [m]"),
            (sy, source.y, f"Source {i} y [m]"),
            (amp, 1 if i == 0 else 0, f"Source {i} active (1) or silent (0)"),
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
    sent(
        "variables",
        f"Created {len(variables)} project variables (room, sources, screens, frequency)",
        {"variables": {name: value for name, value, _ in variables}},
    )

    builder = project.geometry_builder()
    builder.add_box(
        name="room",
        position=("room_x0", "room_y0", 0),
        size=("room_w", "room_h", "room_z"),
        alignment=allsolve.CadAlignment.CORNER,
    )
    for strip in strips:
        builder.add_box(
            name=strip.name,
            position=(strip.centre_x, strip.centre_y, "room_z / 2"),
            size=(strip.size_x, strip.size_y, "room_z"),
            rotation=None if strip.rotation_deg is None else (0, 0, strip.rotation_deg),
        )
    for i in range(len(office.sources)):
        sx, sy, _ = source_variables(i)
        builder.add_sphere(name=f"source_{i}", position=(sx, sy, "src_z"), radius="src_r")
    for i in range(params.n_screens):
        on, x, y, w, h = screen_variables(i)
        builder.add_box(
            name=f"screen_{i}",
            position=(x, y, "panel_z / 2"),
            size=(w, h, "panel_z"),
            enabled=f"eq({on}, 1)",
        )
    # The implicit final fragment-all splits the room into air + walls + talker + screens.
    sent(
        "geometry",
        f"Sent geometry: room, {len(strips)} wall strips, {len(office.sources)} sources, {params.n_screens} movable screens",
        {"wall_strips": [strip.name for strip in strips], "sources": len(office.sources), "screens": params.n_screens},
    )
    builder.build(print_logs=False, on_error=allsolve.OnError.RAISE)
    received("geometry", "Allsolve built the geometry")

    everything = project.create_region_rule(
        name="everything",
        entity_type=allsolve.Region.VOLUME,
        bounding_box=(
            ("room_x0 - 1", "room_y0 - 1", -1),
            ("room_x0 + room_w + 1", "room_y0 + room_h + 1", "room_z + 1"),
        ),
    )
    # Talker and screens are far smaller than the room in plan, so a size filter finds them.
    obstacle_size = max(params.screen_length_m, 2 * TALKER_RADIUS_M) * 1.05
    obstacles = project.create_region_rule(
        name="obstacles",
        entity_type=allsolve.Region.VOLUME,
        max_size=(obstacle_size, obstacle_size, ceiling + 0.1),
    )
    solid = obstacles  # everything that is not air
    movable = obstacles  # talker and screens
    if strips:
        strip_rules = [
            project.create_region_rule(
                name=f"{strip.name}_solid",
                entity_type=allsolve.Region.VOLUME,
                attribute_path=[("name", strip.name)],
            )
            for strip in strips
        ]
        wall_solid = project.create_region_computed(
            name="wall_solid",
            entity_type=allsolve.Region.VOLUME,
            operation=allsolve.RegionOperation.UNION,
            source_regions=[rule.id for rule in strip_rules],
        )
        movable = project.create_region_computed(
            name="movable",
            entity_type=allsolve.Region.VOLUME,
            operation=allsolve.RegionOperation.DIFFERENCE,
            source_regions=[obstacles.id, wall_solid.id],
        )
        solid = project.create_region_computed(
            name="solid",
            entity_type=allsolve.Region.VOLUME,
            operation=allsolve.RegionOperation.UNION,
            source_regions=[obstacles.id, wall_solid.id],
        )
    air = project.create_region_computed(
        name="air",
        entity_type=allsolve.Region.VOLUME,
        operation=allsolve.RegionOperation.DIFFERENCE,
        source_regions=[everything.id, solid.id],
    )
    source_surfaces = []
    for i in range(len(office.sources)):
        sx, sy, _ = source_variables(i)
        body = project.create_region_rule(
            name=f"source_{i}",
            entity_type=allsolve.Region.VOLUME,
            bounding_box=(
                (f"{sx} - 1.1 * src_r", f"{sy} - 1.1 * src_r", "src_z - 1.1 * src_r"),
                (f"{sx} + 1.1 * src_r", f"{sy} + 1.1 * src_r", "src_z + 1.1 * src_r"),
            ),
        )
        source_surfaces.append(
            project.create_region_computed(
                name=f"source_{i}_surface",
                entity_type=allsolve.Region.SURFACE,
                operation=allsolve.RegionOperation.BOUNDARY,
                source_regions=[body.id],
            )
        )

    # Which faces of the air reflect. Everything else absorbs.
    air_faces = project.create_region_computed(
        name="air_faces",
        entity_type=allsolve.Region.SURFACE,
        operation=allsolve.RegionOperation.BOUNDARY,
        source_regions=[air.id],
    )
    floor = project.create_region_rule(
        name="floor",
        entity_type=allsolve.Region.SURFACE,
        bounding_box=(
            ("room_x0 - 1", "room_y0 - 1", -0.01),
            ("room_x0 + room_w + 1", "room_y0 + room_h + 1", 0.01),
        ),
    )
    if params.screen_absorbing:
        not_absorbing = [floor.id] + [surface.id for surface in source_surfaces]
    else:
        movable_faces = project.create_region_computed(
            name="movable_faces",
            entity_type=allsolve.Region.SURFACE,
            operation=allsolve.RegionOperation.BOUNDARY,
            source_regions=[movable.id],
        )
        not_absorbing = [floor.id, movable_faces.id]  # movable includes the sources
    reflecting = project.create_region_computed(
        name="reflecting",
        entity_type=allsolve.Region.SURFACE,
        operation=allsolve.RegionOperation.UNION,
        source_regions=not_absorbing,
    )
    absorbing = project.create_region_computed(
        name="absorbing",
        entity_type=allsolve.Region.SURFACE,
        operation=allsolve.RegionOperation.DIFFERENCE,
        source_regions=[air_faces.id, reflecting.id],
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
                name=f"Source {i}",
                # sn(1) makes it oscillate at the simulation frequency. A constant value would be a
                # steady push, which a harmonic simulation answers with silence.
                acoustic_waves_normal_acceleration=f"accel * {source_variables(i)[2]} * sn(1)",
                target=surface,
            )
            for i, surface in enumerate(source_surfaces)
        ]
        + [allsolve.Interaction.AcousticWavesAbsorbingBoundary(name="Walls and ceiling", target=absorbing)]
    )

    # Small problems fit a direct solve on one large machine. Larger ones need the iterative
    # domain-decomposition solver on several.
    unknowns = estimate_unknowns(params)
    if unknowns <= DIRECT_SOLVER_LIMIT:
        solver_mode, node_count = allsolve.SolverMode.DIRECT, 1
    elif unknowns <= 1_500_000:
        solver_mode, node_count = allsolve.SolverMode.ITERATIVE, 4
    else:
        solver_mode, node_count = allsolve.SolverMode.ITERATIVE, 8

    mesh_size = SPEED_OF_SOUND / (max(params.frequencies_hz) * ELEMENTS_PER_WAVELENGTH)
    sent(
        "physics",
        f"Set up acoustic waves in air: {len(office.sources)} pulsating sources, absorbing walls",
        {"physics": "AcousticWaves", "density": AIR_DENSITY, "speed_of_sound": SPEED_OF_SOUND, "mesh_size_m": round(mesh_size, 4)},
    )
    return OfficeProject(
        project=project,
        physics_set=physics_set,
        air=air,
        mesh_size_m=mesh_size,
        solver_mode=solver_mode,
        node_type=allsolve.CPU.CORES_4_64GB,
        node_count=node_count,
        probe_height_m=params.ear_height_m,
        reference_height_m=params.source_height_m,
        max_run_time_minutes=120,
    )
