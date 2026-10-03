"""Build the real, dispersive Si3N4 grating model and lockstep cloud batches.

Setup builds CAD in Allsolve. Batch creation never starts meshes or simulations;
the runner owns quota checks and their lifecycle.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import allsolve


HERE = Path(__file__).resolve().parent
_SOURCE_PATHS: dict[str, Path] = {}
PERIOD_Y_M = 100e-9
DEFAULT_CLEARANCE_M = 1000e-9


def silicon_nitride_index(wavelength_nm: float) -> float:
    """Luke 2015 lossless Sellmeier fit; its wavelength argument is in micrometres."""
    l2 = (float(wavelength_nm) * 1e-3) ** 2
    return math.sqrt(1 + 3.0249 * l2 / (l2 - 0.1353406**2)
                     + 40314 * l2 / (l2 - 1239.842**2))


def silica_index(wavelength_nm: float) -> float:
    """Malitson 1965 fused-silica Sellmeier fit, with wavelength in micrometres."""
    l2 = (float(wavelength_nm) * 1e-3) ** 2
    return math.sqrt(1 + 0.6961663 * l2 / (l2 - 0.0684043**2)
                     + 0.4079426 * l2 / (l2 - 0.1162414**2)
                     + 0.8974794 * l2 / (l2 - 9.896161**2))


def _midpoint(bounds: dict) -> float:
    return (float(bounds["min"]) + float(bounds["max"])) / 2


def _source(project) -> Path:
    return _SOURCE_PATHS.get(project.id, HERE / "source_readout.py")


def create_experiment(client, request: dict, source_path: Path):
    """Create a six-volume periodic ridge cell, material regions, and order-2 E physics."""
    source_path = Path(source_path).resolve()
    source = source_path.read_text(encoding="utf-8")
    geometry = request["geometry_bounds"]
    wavelength_nm = (float(request["wavelength_min_nm"]) + float(request["wavelength_max_nm"])) / 2
    project = client.create_project(
        name="MetaSense liquid discriminator",
        description="Real normal-incidence TE Si3N4 grating cloud search. Explicit liquid indices; bulk refractometry, not biochemical binding or an experiment.",
    )
    client.set_current_project(project)
    _SOURCE_PATHS[project.id] = source_path
    project.create_variables([
        ("candidate_id", 0, "Candidate identifier"),
        ("input_index", 0, "Explicit liquid input identifier"),
        ("wavelength", wavelength_nm * 1e-9, "Vacuum wavelength, m"),
        ("wavelength_um", "wavelength*1e6", "Dispersion argument, micrometres"),
        ("frequency", "299792458/wavelength", "Optical frequency, Hz"),
        ("period_x", _midpoint(geometry["period_nm"]) * 1e-9, "Grating period, m"),
        ("period_y", PERIOD_Y_M, "Fixed invariant-direction period, m"),
        ("fill_factor", _midpoint(geometry["fill_factor"]), "Ridge width / x period"),
        ("ridge_width", "period_x*fill_factor", "Si3N4 ridge width, m"),
        ("ridge_left", "period_x*(1-fill_factor)/2", "Each liquid groove width, m"),
        ("ridge_height", _midpoint(geometry["ridge_height_nm"]) * 1e-9, "Ridge height, m"),
        ("film_thickness", float(request["film_thickness_nm"]) * 1e-9, "Continuous Si3N4 film thickness, m"),
        ("clearance", DEFAULT_CLEARANCE_M, "Liquid above highest ridge and glass below film, m"),
        ("bbox_eps", 1e-9, "Region selection tolerance, m; below the smallest allowed feature"),
        ("n_liquid", float(request["liquids"][0]["n"]), "Explicit constant real liquid index"),
        ("n_sin", "sqrt(1+3.0249*wavelength_um*wavelength_um/(wavelength_um*wavelength_um-0.1353406*0.1353406)+40314*wavelength_um*wavelength_um/(wavelength_um*wavelength_um-1239.842*1239.842))", "Luke 2015 lossless Si3N4 Sellmeier fit"),
        ("n_substrate", "sqrt(1+0.6961663*wavelength_um*wavelength_um/(wavelength_um*wavelength_um-0.0684043*0.0684043)+0.4079426*wavelength_um*wavelength_um/(wavelength_um*wavelength_um-0.1162414*0.1162414)+0.8974794*wavelength_um*wavelength_um/(wavelength_um*wavelength_um-9.896161*9.896161))", "Malitson 1965 lossless fused-silica fit"),
        ("E0", 1, "Peak incident TE Ey field, V/m"),
        ("write_fields", 0, "Enable field artifacts only for selected finalist runs"),
    ])
    builder = project.geometry_builder()
    for name, position, size in [
        ("top_liquid", (0, 0, "-ridge_height-clearance"), ("period_x", "period_y", "clearance")),
        ("left_groove", (0, 0, "-ridge_height"), ("ridge_left", "period_y", "ridge_height")),
        ("ridge", ("ridge_left", 0, "-ridge_height"), ("ridge_width", "period_y", "ridge_height")),
        ("right_groove", ("ridge_left+ridge_width", 0, "-ridge_height"), ("ridge_left", "period_y", "ridge_height")),
        ("film", (0, 0, 0), ("period_x", "period_y", "film_thickness")),
        ("substrate", (0, 0, "film_thickness"), ("period_x", "period_y", "clearance")),
    ]:
        builder.add_box(name=name, position=position, size=size, alignment=allsolve.CadAlignment.CORNER)
    builder.build(print_logs=False, on_error=allsolve.OnError.STRICT)

    regions = {}
    volumes = {
        "top_liquid": (("-bbox_eps", "-bbox_eps", "-ridge_height-clearance-bbox_eps"), ("period_x+bbox_eps", "period_y+bbox_eps", "-ridge_height+bbox_eps")),
        "left_groove": (("-bbox_eps", "-bbox_eps", "-ridge_height-bbox_eps"), ("ridge_left+bbox_eps", "period_y+bbox_eps", "bbox_eps")),
        "ridge": (("ridge_left-bbox_eps", "-bbox_eps", "-ridge_height-bbox_eps"), ("ridge_left+ridge_width+bbox_eps", "period_y+bbox_eps", "bbox_eps")),
        "right_groove": (("ridge_left+ridge_width-bbox_eps", "-bbox_eps", "-ridge_height-bbox_eps"), ("period_x+bbox_eps", "period_y+bbox_eps", "bbox_eps")),
        "film": (("-bbox_eps", "-bbox_eps", "-bbox_eps"), ("period_x+bbox_eps", "period_y+bbox_eps", "film_thickness+bbox_eps")),
        "substrate": (("-bbox_eps", "-bbox_eps", "film_thickness-bbox_eps"), ("period_x+bbox_eps", "period_y+bbox_eps", "film_thickness+clearance+bbox_eps")),
        "domain": (("-bbox_eps", "-bbox_eps", "-ridge_height-clearance-bbox_eps"), ("period_x+bbox_eps", "period_y+bbox_eps", "film_thickness+clearance+bbox_eps")),
    }
    for name, bounds in volumes.items():
        regions[name] = project.create_region_rule(name=name, entity_type=allsolve.Region.VOLUME, bounding_box=bounds)
    bottom, top = "-ridge_height-clearance", "film_thickness+clearance"
    surfaces = {
        "entrance": (("-bbox_eps", "-bbox_eps", f"{bottom}-bbox_eps"), ("period_x+bbox_eps", "period_y+bbox_eps", f"{bottom}+bbox_eps")),
        "exit": (("-bbox_eps", "-bbox_eps", f"{top}-bbox_eps"), ("period_x+bbox_eps", "period_y+bbox_eps", f"{top}+bbox_eps")),
        "xmin": (("-bbox_eps", "-bbox_eps", f"{bottom}-bbox_eps"), ("bbox_eps", "period_y+bbox_eps", f"{top}+bbox_eps")),
        "xmax": (("period_x-bbox_eps", "-bbox_eps", f"{bottom}-bbox_eps"), ("period_x+bbox_eps", "period_y+bbox_eps", f"{top}+bbox_eps")),
        "ymin": (("-bbox_eps", "-bbox_eps", f"{bottom}-bbox_eps"), ("period_x+bbox_eps", "bbox_eps", f"{top}+bbox_eps")),
        "ymax": (("-bbox_eps", "period_y-bbox_eps", f"{bottom}-bbox_eps"), ("period_x+bbox_eps", "period_y+bbox_eps", f"{top}+bbox_eps")),
    }
    for name, bounds in surfaces.items():
        regions[name] = project.create_region_rule(name=name, entity_type=allsolve.Region.SURFACE, bounding_box=bounds)
    regions["liquid"] = project.create_region_computed(name="liquid", entity_type=allsolve.Region.VOLUME,
        operation=allsolve.RegionOperation.UNION, source_regions=[regions[name] for name in ("top_liquid", "left_groove", "right_groove")])
    regions["silicon_nitride"] = project.create_region_computed(name="silicon_nitride", entity_type=allsolve.Region.VOLUME,
        operation=allsolve.RegionOperation.UNION, source_regions=[regions["ridge"], regions["film"]])
    for name, region_name, epsilon in [
        ("Explicit liquid index", "liquid", "n_liquid*n_liquid*epsilon0"),
        ("Si3N4 Luke 2015 dispersion", "silicon_nitride", "n_sin*n_sin*epsilon0"),
        ("Fused silica Malitson 1965 dispersion", "substrate", "n_substrate*n_substrate*epsilon0"),
    ]:
        project.create_material(name=name, target_region=regions[region_name], electric_permittivity=epsilon,
                                magnetic_permeability="mu0", electric_conductivity="0")
    physics_set = project.get_default_physics_set()
    em = physics_set.add_physics(allsolve.Physics.ElectromagneticWaves(target=regions["domain"].id))
    em.set_field_interpolation_order(2)
    em.save()
    interactions = [
        allsolve.Interaction.ElectromagneticWavesAbsorbingBoundary(name="Open liquid entrance", target=regions["entrance"].id),
        allsolve.Interaction.ElectromagneticWavesAbsorbingBoundary(name="Open silica exit", target=regions["exit"].id),
    ]
    for axis, direction, period in [("x", (1, 0, 0), "period_x"), ("y", (0, 1, 0), "period_y")]:
        interactions.append(allsolve.Interaction.ElectromagneticWavesPeriodicity(
            name=f"Zero phase {axis} periodicity", electromagnetic_waves_periodicity_anti_periodicity=False,
            target_1=regions[axis + "min"].id, target_2=regions[axis + "max"].id,
            electromagnetic_waves_periodicity_translation_direction=direction,
            electromagnetic_waves_periodicity_translation_distance=period,
        ))
    em.add_interactions(interactions)
    metadata = {
        "project_id": project.id, "project_url": client.get_url(project),
        "physics_set_id": physics_set.id, "created_at": datetime.now(timezone.utc).isoformat(),
        "sdk_version": version("allsolve"), "source_path": str(source_path),
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "region_ids": {name: region.id for name, region in regions.items()},
        "field_order": 2, "harmonics": [2, 3], "periodic_multiplier_order": 2,
        "polarization": "Ey (TE)", "period_y_nm": 100, "clearance_nm": 1000, "region_selection_tolerance_nm": 1,
        "materials": {"silicon_nitride": "Luke 2015 lossless Sellmeier", "substrate": "Malitson 1965 lossless fused silica", "liquids": "Explicit constant real indices"},
    }
    return project, metadata


def create_batch(project, request: dict, points: list[dict], stage: str = "coarse",
                 clearance_nm: float = 1000, write_fields: bool = False, source_path: Path | None = None):
    """Prepare a mesh override and harmonic simulation for exactly these paired points."""
    if stage not in {"coarse", "fine"} or not points:
        raise ValueError("A batch needs points and stage coarse or fine")
    if not math.isfinite(clearance_nm) or clearance_nm <= 0:
        raise ValueError("Clearance must be positive and finite")
    rows = []
    for point in points:
        row = {key: float(point[key]) for key in (
            "candidate_id", "input_index", "wavelength_nm", "n_liquid", "period_nm", "fill_factor", "ridge_height_nm", "film_thickness_nm")}
        if not all(math.isfinite(value) for value in row.values()):
            raise ValueError("All batch point values must be finite")
        if min(row[key] for key in ("wavelength_nm", "n_liquid", "period_nm", "ridge_height_nm", "film_thickness_nm")) <= 0 or not 0 < row["fill_factor"] < 1:
            raise ValueError("Batch dimensions/indices must be positive and fill factor between zero and one")
        cutoff = max(row["n_liquid"], silica_index(row["wavelength_nm"])) * max(row["period_nm"], 100) / row["wavelength_nm"]
        if cutoff > 0.9 + 1e-12:
            raise ValueError("Batch point violates the exterior diffraction cutoff margin")
        rows.append(row)
    resolution = 12 if stage == "coarse" else 18
    wavelengths = [row["wavelength_nm"] for row in rows]
    lambda_min_m = min(wavelengths) * 1e-9
    n_exterior = max(max(row["n_liquid"], silica_index(row["wavelength_nm"])) for row in rows)
    n_sin_max = max(silicon_nitride_index(wavelength) for wavelength in wavelengths)
    dielectric_max = lambda_min_m / (n_sin_max * resolution)
    ridge_size = min(dielectric_max, *(row["ridge_height_nm"] * 1e-9 / 3 for row in rows),
                     *(row["period_nm"] * row["fill_factor"] * 1e-9 / 3 for row in rows),
                     *(row["period_nm"] * (1 - row["fill_factor"]) * 1e-9 / 3 for row in rows))
    film_size = min(dielectric_max, *(row["film_thickness_nm"] * 1e-9 / 3 for row in rows))
    unique = uuid4().hex[:8]
    batch_name = f"{stage}-{unique}"
    overrides = [(variable, [row[key] * scale for row in rows]) for variable, key, scale in [
        ("candidate_id", "candidate_id", 1), ("input_index", "input_index", 1),
        ("wavelength", "wavelength_nm", 1e-9), ("n_liquid", "n_liquid", 1),
        ("period_x", "period_nm", 1e-9), ("fill_factor", "fill_factor", 1),
        ("ridge_height", "ridge_height_nm", 1e-9), ("film_thickness", "film_thickness_nm", 1e-9),
    ]]
    overrides.extend([("clearance", [clearance_nm * 1e-9] * len(rows)), ("write_fields", [int(write_fields)] * len(rows))])
    sweep = project.create_variable_overrides(name=batch_name, overrides=overrides, sweep_type=allsolve.SweepType.SPECIFIC_VALUES)
    regions = {region.name: region for region in project.get_regions()}
    node = allsolve.CPU.CORES_3_10GB_FAST_START if stage == "coarse" else allsolve.CPU.CORES_4_64GB
    settings = allsolve.MeshSettings(
        name=f"{batch_name} mesh", max_run_time_minutes=15 if stage == "coarse" else 20, node_type=node.value, scale_factor=1,
        mesh_size_max=lambda_min_m / (n_exterior * resolution), mesh_size_min=min(ridge_size, film_size) / 2,
        use_mesh_refiner=False, variable_overrides=[sweep], refinements=[
            allsolve.MeshRefinement(region=regions["ridge"], max_size=ridge_size),
            allsolve.MeshRefinement(region=regions["film"], max_size=film_size),
        ],
    )
    mesh = project.create_mesh(settings)
    instance = mesh.get_override(sweep)
    physics_set = project.get_default_physics_set()
    simulation = project.create_simulation_harmonic(
        name=batch_name, description="Lockstep actual TE grating R/T for two explicit liquid-index inputs",
        max_run_time_minutes=15 if stage == "coarse" else 30, mesh=mesh, physics_set=physics_set, variable_overrides=sweep,
        fundamental_frequency="frequency", solver_tolerance="1e-9",
    )
    simulation.set_runtime(allsolve.Runtime(node_type=node))
    simulation.disabled_script_sections = [allsolve.DisableableSection.FORMULATIONS, allsolve.DisableableSection.SOLVE]
    simulation.save()
    source = (Path(source_path) if source_path is not None else _source(project)).read_text(encoding="utf-8")
    simulation.set_scripts([allsolve.Script(name="source_readout.py", section_name=allsolve.CustomSection.AFTER_FORMULATIONS_CREATED, content=source)])
    metadata = {
        "name": batch_name, "stage": stage, "project_id": project.id, "physics_set_id": physics_set.id,
        "sweep_id": sweep.id, "mesh_id": mesh.id, "mesh_instance_id": instance.id,
        "simulation_id": simulation.id, "points": [dict(point) for point in points], "point_count": len(points),
        "resolution_per_material_wavelength": resolution,
        "mesh_size_max_m": lambda_min_m / (n_exterior * resolution), "ridge_mesh_size_max_m": ridge_size,
        "film_mesh_size_max_m": film_size, "clearance_nm": clearance_nm, "write_fields": write_fields,
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "node_type": node.value,
        "mesh_cores": 3 if stage == "coarse" else 4, "simulation_cores": 3 if stage == "coarse" else 4,
        "mesh_status": None, "simulation_status": None, "mesh_job_id": None, "simulation_job_id": None,
    }
    return instance, simulation, metadata
