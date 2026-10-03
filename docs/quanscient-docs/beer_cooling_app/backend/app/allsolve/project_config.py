"""Generate Allsolve project configuration from simulation parameters."""

from typing import Any
from ..models.simulation_params import SimulationParams, ContainerShape, CoolingMethod


def generate_project_config(params: SimulationParams) -> dict[str, Any]:
    """
    Generate an Allsolve project configuration dictionary from simulation parameters.

    This creates a complete project configuration including:
    - Parameterized geometry (beer container)
    - Material definitions (beer, aluminum/glass)
    - Region definitions for boundary conditions
    - Mesh settings
    - Variable definitions for the simulation

    Args:
        params: User-specified simulation parameters

    Returns:
        Dictionary that can be passed to allsolve.import_project()
    """
    container_specs = params.get_container_specs()
    cooling_specs = params.get_cooling_specs()

    # Convert temperatures to Kelvin
    t_initial_k = params.initial_temp_celsius + 273.15
    t_coolant_k = cooling_specs["coolant_temp_celsius"] + 273.15

    # Calculate water level based on immersion
    # For fridge/freezer, immersion is 100% (all surfaces are cooled by air)
    is_immersion_method = params.cooling_method in [
        CoolingMethod.ICE_WATER,
        CoolingMethod.SALT_ICE,
    ]
    effective_immersion = params.immersion_level if is_immersion_method else 1.0
    water_level = container_specs["height"] * effective_immersion

    # Determine container material based on shape
    container_material = _get_container_material(params.container_shape)

    config = {
        "name": f"Beer Cooling - {params.container_shape.value} in {params.cooling_method.value}",
        "description": f"Transient heat transfer simulation of beer cooling from {params.initial_temp_celsius}°C",
        "dimension": 3,
        "verbose": True,
        "labels": ["beer-cooling", "heat-transfer"],
        # Geometry definitions (pass water_level for surface cutting)
        "geometries": _generate_geometries(container_specs, water_level),
        # Region definitions
        "regions": _generate_regions(
            water_level,
            container_specs["height"],
            container_specs["radius"],
            container_specs["wall_thickness"],
        ),
        # Variables
        "variables": [
            # Geometry parameters
            {
                "name": "beer_radius",
                "expression": container_specs["radius"]
                - container_specs["wall_thickness"],
            },
            {"name": "container_radius", "expression": container_specs["radius"]},
            {"name": "container_height", "expression": container_specs["height"]},
            {"name": "wall_thickness", "expression": container_specs["wall_thickness"]},
            # Thermal parameters
            {"name": "water_level", "expression": water_level},
            {"name": "T_initial", "expression": t_initial_k},
            {"name": "T_coolant", "expression": t_coolant_k},
            {"name": "h_submerged", "expression": cooling_specs["h_submerged"]},
            {"name": "h_exposed", "expression": cooling_specs["h_exposed"]},
            # Simulation control
            {"name": "t_end", "expression": params.simulation_duration_minutes * 60.0},
            {"name": "dt", "expression": 1.0},  # 1 second timestep
        ],
        # Materials
        "materials": [
            _get_beer_material(),
            container_material,
        ],
        # Mesh configuration - keep it coarse for fast simulation
        "meshes": [
            {
                "name": "cooling_mesh",
                "nodeType": "lambda",  # Fast starting nodes
                "scaleFactor": 1.0,
                "useMeshRefiner": False,  # Disable auto-refinement
                "curvedMesh": False,  # Disable curved mesh for speed
                "curvatureEnhancement": 1,  # Minimal curvature refinement
                "maxRunTimeMinutes": 10,
                "meshSizeMin": 0.003,  # 3mm minimum element size
                "meshSizeMax": 0.05,  # 50mm maximum element size
                "refinements": [
                    # Container wall - 6mm elements
                    {
                        "region": "container",
                        "maxSize": 0.006,
                    },
                    # Beer volume - 30mm elements (very coarse)
                    {"region": "beer", "maxSize": 0.03},
                ],
            }
        ],
    }

    return config


def _generate_geometries(container_specs: dict, water_level: float) -> list[dict]:
    """Generate geometry definitions for the beer container following the 4-cylinder split method.

    IMPORTANT: In Allsolve, cylinder 'position' is the center of the cylinder volume,
    and 'axis' is the full height vector.

    1. Lower outer cylinder: z from 0 to water_level
    2. Lower inner cylinder: z from wall to water_level
    3. Upper outer cylinder: z from water_level to height
    4. Upper inner cylinder: z from water_level to height - wall
    """
    radius = container_specs["radius"]
    height = container_specs["height"]
    wall = container_specs["wall_thickness"]
    inner_radius = radius - wall

    # Ensure water_level is within valid range to avoid zero-height cylinders
    water_level = max(wall * 1.5, min(water_level, height - wall * 1.5))

    # Cylinder 1: Lower outer container (z from 0 to water_level)
    cyl1_h = water_level
    cyl1_pos_z = cyl1_h / 2.0

    # Cylinder 2: Lower inner beer (z from wall to water_level)
    cyl2_h = water_level - wall
    cyl2_pos_z = wall + (cyl2_h / 2.0)

    # Cylinder 3: Upper outer container (z from water_level to height)
    cyl3_h = height - water_level
    cyl3_pos_z = water_level + (cyl3_h / 2.0)

    # Cylinder 4: Upper inner beer (z from water_level to height - wall)
    cyl4_h = (height - wall) - water_level
    cyl4_pos_z = water_level + (cyl4_h / 2.0)

    geometries = [
        # Cylinder 1: Immersed container outer
        {
            "type": "cylinder",
            "name": "container_lower",
            "position": {"x": 0, "y": 0, "z": cyl1_pos_z},
            "axis": {"x": 0, "y": 0, "z": cyl1_h},
            "radius": radius,
        },
        # Cylinder 2: Immersed beer volume
        {
            "type": "cylinder",
            "name": "beer_lower",
            "position": {"x": 0, "y": 0, "z": cyl2_pos_z},
            "axis": {"x": 0, "y": 0, "z": cyl2_h},
            "radius": inner_radius,
        },
        # Cylinder 3: Non-immersed container outer
        {
            "type": "cylinder",
            "name": "container_upper",
            "position": {"x": 0, "y": 0, "z": cyl3_pos_z},
            "axis": {"x": 0, "y": 0, "z": cyl3_h},
            "radius": radius,
        },
        # Cylinder 4: Non-immersed beer volume
        {
            "type": "cylinder",
            "name": "beer_upper",
            "position": {"x": 0, "y": 0, "z": cyl4_pos_z},
            "axis": {"x": 0, "y": 0, "z": cyl4_h},
            "radius": inner_radius,
        },
        # Explicit fragmentAll to ensure all parts are merged correctly
        {
            "type": "fragmentAll",
            "name": "partition_geometry",
        },
    ]

    return geometries


def _generate_regions(
    water_level: float,
    container_height: float,
    radius: float,
    wall_thickness: float,
) -> list[dict]:
    """Generate region definitions for materials and boundary conditions.

    With immersion split geometry (after implicit fragmentAll):
    - Beer: union of beer_lower and beer_upper volumes
    - Container: (container_lower - beer_lower) + (container_upper - beer_upper)
    - Submerged surface: outer boundary of lower domain (intersected with outer surface)
    - Exposed surface: outer boundary of upper domain (intersected with outer surface)
    """
    return [
        # =========================================================
        # VOLUME REGIONS - Base entities from CAD
        # =========================================================
        # Beer lower volume
        {
            "name": "beer_lower",
            "type": "regionRule",
            "entityType": "volume",
            "attributePath": [{"key": "name", "value": "beer_lower"}],
        },
        # Beer upper volume
        {
            "name": "beer_upper",
            "type": "regionRule",
            "entityType": "volume",
            "attributePath": [{"key": "name", "value": "beer_upper"}],
        },
        # Container lower (includes the inner beer volume initially)
        {
            "name": "container_lower_all",
            "type": "regionRule",
            "entityType": "volume",
            "attributePath": [{"key": "name", "value": "container_lower"}],
        },
        # Container upper (includes the inner beer volume initially)
        {
            "name": "container_upper_all",
            "type": "regionRule",
            "entityType": "volume",
            "attributePath": [{"key": "name", "value": "container_upper"}],
        },
        # =========================================================
        # COMPUTED VOLUME REGIONS - Isolate shells and combine
        # =========================================================
        # Container lower shell = (all lower) - (beer lower)
        {
            "name": "container_lower",
            "type": "computed",
            "entityType": "volume",
            "operation": "difference",
            "regions": ["container_lower_all", "beer_lower"],
        },
        # Container upper shell = (all upper) - (beer upper)
        {
            "name": "container_upper",
            "type": "computed",
            "entityType": "volume",
            "operation": "difference",
            "regions": ["container_upper_all", "beer_upper"],
        },
        # Combined beer volume (for material assignment)
        {
            "name": "beer",
            "type": "computed",
            "entityType": "volume",
            "operation": "union",
            "regions": ["beer_lower", "beer_upper"],
        },
        # Combined container volume (for material assignment)
        {
            "name": "container",
            "type": "computed",
            "entityType": "volume",
            "operation": "union",
            "regions": ["container_lower", "container_upper"],
        },
        # Combined domain (all volumes)
        {
            "name": "all_domain",
            "type": "computed",
            "entityType": "volume",
            "operation": "union",
            "regions": ["beer", "container"],
        },
        # Lower domain (for boundary extraction)
        {
            "name": "lower_domain",
            "type": "computed",
            "entityType": "volume",
            "operation": "union",
            "regions": ["beer_lower", "container_lower"],
        },
        # Upper domain (for boundary extraction)
        {
            "name": "upper_domain",
            "type": "computed",
            "entityType": "volume",
            "operation": "union",
            "regions": ["beer_upper", "container_upper"],
        },
        # =========================================================
        # SURFACE REGIONS - Split at water level
        # =========================================================
        # Full outer boundary (all external surfaces)
        {
            "name": "outer_surface",
            "type": "computed",
            "entityType": "surface",
            "operation": "boundary",
            "regions": ["all_domain"],
        },
        # Lower boundary (includes internal interface at water level)
        {
            "name": "lower_boundary",
            "type": "computed",
            "entityType": "surface",
            "operation": "boundary",
            "regions": ["lower_domain"],
        },
        # Upper boundary (includes internal interface at water level)
        {
            "name": "upper_boundary",
            "type": "computed",
            "entityType": "surface",
            "operation": "boundary",
            "regions": ["upper_domain"],
        },
        # Submerged outer surface = lower_boundary intersected with outer_surface
        # This excludes the internal interface at water level
        {
            "name": "submerged_surface",
            "type": "computed",
            "entityType": "surface",
            "operation": "intersection",
            "regions": ["lower_boundary", "outer_surface"],
        },
        # Exposed outer surface = upper_boundary intersected with outer_surface
        # This excludes the internal interface at water level
        {
            "name": "exposed_surface",
            "type": "computed",
            "entityType": "surface",
            "operation": "intersection",
            "regions": ["upper_boundary", "outer_surface"],
        },
    ]


def _get_beer_material() -> dict:
    """Get material properties for beer (water-like liquid)."""
    return {
        "name": "Beer",
        "target": "beer",
        "color": "#FFD700",
        "description": "Beer liquid (water-like properties)",
        "density": 1000.0,  # kg/m³
        "thermalConductivity": 1.2,  # W/(m·K) - effective with natural convection
        "heatCapacity": 4184.0,  # J/(kg·K)
    }


def _get_container_material(shape: ContainerShape) -> dict:
    """Get material properties for the container based on its type."""
    if shape == ContainerShape.CAN:
        return {
            "name": "Aluminum",
            "target": "container",
            "color": "#C0C0C0",
            "description": "Aluminum can material",
            "density": 2700.0,  # kg/m³
            "thermalConductivity": 237.0,  # W/(m·K)
            "heatCapacity": 900.0,  # J/(kg·K)
        }
    else:
        # Glass for bottles and pint glasses
        return {
            "name": "Glass",
            "target": "container",
            "color": "#8B4513",
            "description": "Glass container material",
            "density": 2500.0,  # kg/m³
            "thermalConductivity": 1.0,  # W/(m·K)
            "heatCapacity": 840.0,  # J/(kg·K)
        }
