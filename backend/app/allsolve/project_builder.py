"""Build the QuietOffice Allsolve project from an office description.

The model is a 2D top-down slice of the office solved with harmonic acoustic waves:

- the room is a rectangle of air
- the talker is a small pulsating disk (normal acceleration on its edge)
- each screen is a thin rectangle left out of the air domain, so it is sound-hard
- the outer walls absorb (no reflections, the simplest stable choice for a first version)

Every screen position is a project variable, so one project serves every layout: a sweep
overrides the variables and Allsolve remeshes per distinct geometry.
"""

from dataclasses import dataclass
from typing import Any, List

from ..models.office import AIR_DENSITY, SPEED_OF_SOUND, OptimizationParams

try:
    import allsolve
except ImportError:  # the API can still start and report that the SDK is missing
    allsolve = None

TALKER_RADIUS_M = 0.15
ELEMENTS_PER_WAVELENGTH = 6
PRESSURE_MAGNITUDE = "sqrt(pow(harm(2, p), 2) + pow(harm(3, p), 2))"


@dataclass
class OfficeProject:
    """Handles to the pieces of the project that the optimizer needs."""

    project: Any
    physics_set: Any
    air: Any
    mesh_size_m: float


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
    variables = [
        ("room_w", office.width_m, "Room width [m]"),
        ("room_h", office.height_m, "Room depth [m]"),
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
        position=(0, 0),
        size=("room_w", "room_h"),
        alignment=allsolve.CadAlignment.CORNER,
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
    # The implicit final fragment-all splits the room into air + talker + screens.
    builder.build(print_logs=False, on_error=allsolve.OnError.RAISE)

    everything = project.create_region_rule(
        name="everything",
        entity_type=allsolve.Region.SURFACE,
        bounding_box=((-1, -1, -1), ("room_w + 1", "room_h + 1", 1)),
    )
    # Talker and screens are all far smaller than the room, so a size filter finds them.
    obstacle_size = max(params.screen_length_m, 2 * TALKER_RADIUS_M) * 1.05
    obstacles = project.create_region_rule(
        name="obstacles",
        entity_type=allsolve.Region.SURFACE,
        max_size=(obstacle_size, obstacle_size, 1),
    )
    air = project.create_region_computed(
        name="air",
        entity_type=allsolve.Region.SURFACE,
        operation=allsolve.RegionOperation.DIFFERENCE,
        source_regions=[everything.id, obstacles.id],
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
    walls = project.create_region_computed(
        name="walls",
        entity_type=allsolve.Region.CURVE,
        operation=allsolve.RegionOperation.BOUNDARY,
        source_regions=[everything.id],
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
