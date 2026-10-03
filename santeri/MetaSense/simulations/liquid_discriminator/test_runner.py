"""Offline orchestration regressions with explicitly synthetic cloud fixtures.

These fixtures exercise scheduling and evidence handling, never the optical
solver or real credentials. The Allsolve SDK constructors remain real in the
batch-configuration test; their project/client operations are replaced locally.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

CASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CASE))
sys.path.insert(0, str(CASE / "backend"))

from app.discriminator_models import DiscriminatorRequest
from allsolve.simulation.simulation_output_data import SimulationOutputData
from simulations.liquid_discriminator import physics, runner
from simulations.liquid_discriminator.search import REQUIRED_OUTPUTS, make_points


def request(**overrides):
    supplied = DiscriminatorRequest.model_validate({
        "candidate_count": 2, "wavelength_samples": 3,
        "max_parallel_cores": 7, **overrides,
    }).model_dump()
    # Normalize default numeric values exactly as a persisted request is loaded.
    return DiscriminatorRequest.model_validate(supplied).model_dump()


def worker(folder, **overrides):
    """Construct local state without invoking Worker.__init__ or an SDK client."""
    instance = runner.Worker.__new__(runner.Worker)
    instance.folder = folder
    instance.folder.mkdir(parents=True, exist_ok=True)
    instance.request = request(**overrides)
    instance.report = runner.initial_report(instance.request)
    instance.report["status"] = "running"
    instance.state = {"batches": [], "results": [], "phase": "search",
                      "project_id": "fixture-project", "project_url": "https://example.test/project"}
    instance.active_statuses = []
    instance.project = SimpleNamespace(id="fixture-project")
    instance.source_path = runner.HERE / "source_readout.py"
    return instance


def optical_outputs(point, reflectance=0.2):
    """Lossless scalar fixture with mutually consistent powers and metadata."""
    pin = 1e-15
    values = {name: 0.0 for name in REQUIRED_OUTPUTS}
    values.update(point)
    values.update(
        specified_incident_power_W=pin, entrance_forward_power_W=pin,
        entrance_backward_power_W=pin * reflectance,
        exit_forward_power_W=pin * (1 - reflectance),
        reflectance=reflectance, transmittance=1 - reflectance,
        coherent_reflectance=reflectance, coherent_transmittance=1 - reflectance,
        incident_normalization_ratio=1.0, exterior_diffraction_cutoff_ratio=0.88,
        wavelength_frequency_ratio=1.0, entrance_material_admittance_ratio=1.0,
        exit_material_admittance_ratio=1.0, local_reflectance=reflectance,
        local_transmittance=1 - reflectance,
        entrance_local_forward_power_W=pin,
        entrance_local_backward_power_W=pin * reflectance,
        exit_local_forward_power_W=pin * (1 - reflectance),
    )
    for plane in ("entrance", "exit"):
        net = values[plane + "_forward_power_W"] - values[plane + "_backward_power_W"]
        values[plane + "_net_flux_W"] = net
        values[plane + "_poynting_flux_W"] = net
        values[plane + "_local_directional_flux_W"] = net
    return values


def result(point, stage="search", reflectance=0.2):
    return {**point, "stage": stage, "outputs": optical_outputs(point, reflectance),
            "valid": True, "error": None, "status": "completed"}


@pytest.fixture
def cloud_jobs(monkeypatch):
    """Jobs carry real SDK status enums but never contact Allsolve."""
    real_job = runner.allsolve.Job

    class FixtureJob:
        statuses = {}
        for name in ("SUCCESS", "ERROR", "ABORTED", "PARTIAL_SUCCESS", "QUEUED", "SUBMITTED"):
            locals()[name] = getattr(real_job, name)

        def __init__(self, project_id, job_id):
            self.id = job_id

        def get_status(self):
            return self.statuses[self.id]

        def refresh_status(self, delay_s=0):
            return self.get_status()

        @staticmethod
        def refresh_statuses(jobs, delay_s=0):
            return None

        def _get_logs(self, limit=1000):
            return []

    monkeypatch.setattr(runner.allsolve, "Job", FixtureJob)
    return FixtureJob


class FixtureSimulation:
    def __init__(self, points, jobs, *, child_statuses=None, missing=(), parent_status=None):
        self.points = points
        self.rows = [SimpleNamespace(job_index=i, job_id=f"fixture-child-{i}", rowid=100 + i, overrides={})
                     for i in range(len(points)) if i not in missing]
        statuses = child_statuses or {}
        jobs.statuses.update({row.job_id: statuses.get(row.job_index, jobs.SUCCESS) for row in self.rows})
        jobs.statuses["fixture-parent"] = parent_status or jobs.SUCCESS
        self.parent = jobs("fixture-project", "fixture-parent")
        self.outputs = {i: optical_outputs(point, 0.2 + 0.2 * point["input_index"])
                        for i, point in enumerate(points)}
        self.start_count = 0

    def get_output_data(self, refresh=True):
        return FixtureOutputData(self)

    def get_output_values(self, index, refresh=False):
        # Real SDK arguments address sorted row positions, not row.job_index.
        return self.get_output_data().to_dict(index)

    def _get_job(self):
        return self.parent

    def start(self):
        self.start_count += 1


class FixtureOutputData(SimulationOutputData):
    """Use real SDK row sorting and to_dict indexing with local scalar storage."""
    def __init__(self, simulation):
        self.simulation = simulation
        self._simulations_sorted = None
        self._database = SimpleNamespace(simulations_by_row_id={row.rowid: row for row in simulation.rows})

    def _get_steps_sorted(self):
        return [SimpleNamespace(raw_step="nostep", rowid=1)]

    def _get_sweep_and_step_values_grouped_by_header(self, simulation_id, step_id):
        submitted_index = self._database.simulations_by_row_id[simulation_id].job_index
        return {name: [value] for name, value in self.simulation.outputs[submitted_index].items()}


def search_batch(instance):
    points = make_points(instance.report["candidates"], instance.request)
    batch = {"name": "search 1", "stage": "search", "points": points,
             "cores_per_child": 3, "status": "running", "mesh_job_id": "fixture-mesh",
             "simulation_job_id": "fixture-parent", "mesh_geometry_verified": True}
    instance.state["batches"].append(batch)
    return batch


@pytest.mark.parametrize("stage,cores", [("search", 3), ("dense", 3), ("fine", 4), ("clearance", 4)])
@pytest.mark.parametrize("budget", [4, 7, 64, 256])
def test_each_real_batch_fits_the_requested_core_budget(tmp_path, monkeypatch, stage, cores, budget):
    instance = worker(tmp_path, max_parallel_cores=budget, candidate_count=8)
    points = make_points(instance.report["candidates"], instance.request)
    calls = []

    def build(project, req, subset, **kwargs):
        calls.append((copy.deepcopy(subset), kwargs))
        return object(), object(), {"mesh_id": f"mesh-{len(calls)}", "simulation_id": f"sim-{len(calls)}"}

    def finish(batch, *_):
        batch["status"] = "completed"

    monkeypatch.setattr(runner, "create_batch", build)
    monkeypatch.setattr(instance, "run_batch", finish)
    instance.run_points(points, stage)
    assert [point for subset, _ in calls for point in subset] == points
    assert all(len(subset) * cores <= budget for subset, _ in calls)
    assert all(kwargs["stage"] == ("coarse" if cores == 3 else "fine") for _, kwargs in calls)
    assert all(batch["cores_per_child"] == cores for batch in instance.state["batches"])


def test_budget_too_small_cannot_schedule_any_child():
    with pytest.raises(ValueError, match="cannot run one"):
        runner.chunks([{"fixture": True}], 3, 4)


@pytest.mark.parametrize("field", ["candidate_id", "input_index", "wavelength_nm", "n_liquid",
                                    "period_nm", "fill_factor", "ridge_height_nm", "film_thickness_nm"])
def test_cloud_point_metadata_must_match_saved_submission(tmp_path, monkeypatch, cloud_jobs, field):
    instance = worker(tmp_path, candidate_count=1)
    batch = search_batch(instance)
    simulation = FixtureSimulation(batch["points"], cloud_jobs)
    simulation.outputs[0][field] += 0.1
    instance.collect(batch, simulation, terminal=True)
    assert not instance.state["results"][0]["valid"]
    assert "Submitted/output metadata mismatch: " + field in instance.state["results"][0]["error"]
    assert instance.report["candidates"][0]["score"] is None
    assert instance.report["best_design"] is None


@pytest.mark.parametrize("failure", ["partial_child", "failed_child", "missing_output"])
def test_partial_failed_or_missing_cloud_spectrum_cannot_score(tmp_path, cloud_jobs, failure):
    instance = worker(tmp_path, candidate_count=1)
    batch = search_batch(instance)
    statuses = {0: cloud_jobs.PARTIAL_SUCCESS} if failure == "partial_child" else (
        {0: cloud_jobs.ERROR} if failure == "failed_child" else {})
    simulation = FixtureSimulation(batch["points"], cloud_jobs, child_statuses=statuses,
                                   missing=(0,) if failure == "missing_output" else ())
    instance.collect(batch, simulation, terminal=True)
    assert len(instance.state["results"]) == len(batch["points"])
    assert not instance.report["candidates"][0]["valid"]
    assert instance.report["candidates"][0]["score"] is None
    assert not instance.report["candidates"][0]["verified"]
    assert instance.report["best_design"] is None
    assert instance.report["status"] != "completed"
    if failure == "partial_child":
        # Plausible numeric outputs from a partial child remain invalid evidence.
        assert instance.state["results"][0]["outputs"]
        assert not instance.state["results"][0]["valid"]


def test_completed_cloud_collection_is_idempotent_and_has_durable_progress(tmp_path, cloud_jobs):
    instance = worker(tmp_path, candidate_count=1)
    batch = search_batch(instance)
    simulation = FixtureSimulation(batch["points"], cloud_jobs)
    instance.collect(batch, simulation, terminal=True)
    first = copy.deepcopy(instance.state["results"])
    instance.collect(batch, simulation, terminal=True)
    assert instance.state["results"] == first
    assert instance.report["progress"]["completed_solve_count"] == 6
    assert instance.report["progress"]["failed_solve_count"] == 0
    assert instance.report["progress"]["completed_candidates"] == 1
    assert instance.report["progress"]["valid_candidates"] == 1
    assert instance.report["candidates"][0]["score"] == pytest.approx(0.2)
    assert instance.report["best_design"]["validated"] is False
    saved = json.loads((tmp_path / "report.json").read_text())
    assert saved["progress"] == instance.report["progress"]
    assert "points" not in saved["batches"][0]
    assert (tmp_path / "batches" / "search_1" / "point_0.json").exists()


def test_successful_child_with_delayed_values_is_collected_after_database_update(tmp_path, cloud_jobs):
    instance = worker(tmp_path, candidate_count=1)
    batch = search_batch(instance)
    simulation = FixtureSimulation(batch["points"], cloud_jobs)
    ready = simulation.outputs[0]
    simulation.outputs[0] = {}
    instance.collect(batch, simulation, terminal=False)
    assert {row["sweep_index"] for row in instance.state["results"]} == {1, 2, 3, 4, 5}
    assert instance.report["progress"]["completed_solve_count"] == 5
    assert instance.report["progress"]["failed_solve_count"] == 0
    assert instance.report["candidates"][0]["score"] is None
    assert not (tmp_path / "batches" / "search_1" / "point_0.json").exists()
    simulation.outputs[0] = ready
    instance.collect(batch, simulation, terminal=False)
    assert len(instance.state["results"]) == 6
    assert all(row["valid"] for row in instance.state["results"])
    assert instance.report["candidates"][0]["score"] == pytest.approx(0.2)
    assert instance.report["best_design"]["validated"] is False
    assert (tmp_path / "batches" / "search_1" / "point_0.json").exists()


def test_terminal_reharvest_replaces_invalid_snapshot_and_retains_earlier_evidence(tmp_path, cloud_jobs):
    instance = worker(tmp_path, candidate_count=1)
    batch = search_batch(instance)
    simulation = FixtureSimulation(batch["points"], cloud_jobs)
    ready = copy.deepcopy(simulation.outputs[0])
    simulation.outputs[0]["wavelength_nm"] += 10
    instance.collect(batch, simulation, terminal=True)
    previous = copy.deepcopy(instance.state["results"][0])
    assert previous["valid"] is False
    assert instance.report["candidates"][0]["score"] is None
    simulation.outputs[0] = ready
    instance.collect(batch, simulation, terminal=True)
    assert len(instance.state["results"]) == 6
    assert len({row["sweep_index"] for row in instance.state["results"]}) == 6
    assert all(row["valid"] for row in instance.state["results"])
    assert instance.report["candidates"][0]["score"] == pytest.approx(0.2)
    path = tmp_path / "batches" / "search_1" / "point_0_earlier_collection.json"
    assert json.loads(path.read_text()) == previous


def test_completed_batch_resume_reharvests_invalid_values_without_restarting_jobs(tmp_path, cloud_jobs):
    instance = worker(tmp_path, candidate_count=1)
    batch = search_batch(instance)
    simulation = FixtureSimulation(batch["points"], cloud_jobs)
    ready = simulation.outputs[0]
    simulation.outputs[0] = {}
    instance.collect(batch, simulation, terminal=True)
    batch["status"] = "completed"
    simulation.outputs[0] = ready
    # No mesh lifecycle operations are available on this resumed fixture.
    instance.run_batch(batch, instance=object(), simulation=simulation)
    assert simulation.start_count == 0
    assert batch["status"] == "completed"
    assert all(row["valid"] for row in instance.state["results"])
    assert instance.report["candidates"][0]["score"] == pytest.approx(0.2)


def test_sparse_database_rows_use_sdk_position_and_preserve_submitted_index(tmp_path, cloud_jobs):
    instance = worker(tmp_path, candidate_count=1)
    batch = search_batch(instance)
    simulation = FixtureSimulation(batch["points"], cloud_jobs)
    all_rows = list(simulation.rows)
    # Database arrival order differs from submission order; indices have gaps.
    simulation.rows = [all_rows[5], all_rows[2]]
    instance.collect(batch, simulation, terminal=False)
    observed = {row["sweep_index"]: row for row in instance.state["results"]}
    assert set(observed) == {2, 5}
    for index, row in observed.items():
        assert row["valid"], row["error"]
        assert row["outputs"]["wavelength_nm"] == batch["points"][index]["wavelength_nm"]
        assert row["outputs"]["input_index"] == batch["points"][index]["input_index"]
        assert row["cloud_job_id"] == f"fixture-child-{index}"
    assert instance.report["candidates"][0]["score"] is None
    simulation.rows = all_rows
    instance.collect(batch, simulation, terminal=True)
    assert len(instance.state["results"]) == 6
    assert all(row["valid"] for row in instance.state["results"])
    assert instance.report["candidates"][0]["score"] == pytest.approx(0.2)


@pytest.mark.parametrize("missing_error", ["404", "file", "uninitialized"])
def test_pending_output_database_does_not_commit_missing_points(tmp_path, monkeypatch, missing_error):
    instance = worker(tmp_path, candidate_count=1)
    batch = search_batch(instance)
    before = copy.deepcopy(instance.report)

    def pending(**_):
        if missing_error == "404":
            raise runner.ApiException(status=404, reason="No output database yet")
        if missing_error == "file":
            raise FileNotFoundError("Local output database pending")
        raise ValueError("Database not initialized")

    simulation = SimpleNamespace(get_output_data=pending)
    instance.collect(batch, simulation, terminal=False)
    assert instance.state["results"] == []
    assert instance.report == before
    assert not (tmp_path / "batches").exists()


@pytest.mark.parametrize("status", [403, 429, 500])
def test_nonpending_api_failures_are_propagated(tmp_path, status):
    instance = worker(tmp_path, candidate_count=1)
    batch = search_batch(instance)

    def failed(**_):
        raise runner.ApiException(status=status, reason="Fixture API failure")

    with pytest.raises(runner.ApiException) as failure:
        instance.collect(batch, SimpleNamespace(get_output_data=failed), terminal=False)
    assert failure.value.status == status
    assert instance.state["results"] == []


def test_collect_keeps_dense_finalist_selected_while_verifying(tmp_path, cloud_jobs):
    instance = worker(tmp_path)
    batch = search_batch(instance)
    simulation = FixtureSimulation(batch["points"], cloud_jobs)
    # Coarse candidate 0 is better, but candidate 1 won the dense follow-up.
    for i, point in enumerate(batch["points"]):
        simulation.outputs[i] = optical_outputs(point, 0.2 + (0.3 if point["candidate_id"] == 0 else 0.1) * point["input_index"])
    chosen = instance.report["candidates"][1]
    finalist = {"candidate_id": chosen["id"], "geometry": chosen["geometry"],
                "score": 0.45, "wavelength_nm": 1005, "R_A": 0.2, "R_B": 0.65,
                "validated": False}
    instance.report.update(status="verifying", best_design=copy.deepcopy(finalist))
    instance.collect(batch, simulation, terminal=True)
    assert instance.report["candidates"][0]["score"] > instance.report["candidates"][1]["score"]
    assert instance.report["best_design"] == finalist


def test_resume_does_not_submit_completed_or_failed_batches_or_inflate_plan(tmp_path, monkeypatch):
    instance = worker(tmp_path, candidate_count=1)
    points = make_points(instance.report["candidates"], instance.request)
    for index, status in enumerate(("completed", "failed")):
        instance.state["batches"].append({"name": f"dense {index + 1}", "stage": "dense",
                                         "points": points[index * 3:(index + 1) * 3], "status": status,
                                         "mesh_geometry_verified": True})

    def forbidden(*args, **kwargs):
        pytest.fail("Resume relaunched a terminal batch")

    monkeypatch.setattr(instance, "batch_objects", forbidden)
    monkeypatch.setattr(instance, "append_batch", forbidden)
    for _ in range(2):
        instance.run_points(points, "dense")
        assert instance.report["progress"]["planned_solve_count"] == 12
    assert instance.report["progress"]["batches_completed"] == 2
    assert instance.report["progress"]["batches_total"] == 2


def test_resume_existing_simulation_and_mesh_never_restarts_them(tmp_path, monkeypatch, cloud_jobs):
    instance = worker(tmp_path, candidate_count=1, max_parallel_cores=64)
    batch = search_batch(instance)
    simulation = FixtureSimulation(batch["points"], cloud_jobs)
    cloud_jobs.statuses["fixture-mesh"] = cloud_jobs.SUCCESS

    def forbidden():
        pytest.fail("An existing successful mesh was restarted")

    mesh = SimpleNamespace(_job=cloud_jobs("fixture-project", "fixture-mesh"),
                           refresh=lambda: None, get_sweep_count=lambda: len(batch["points"]), start=forbidden)
    monkeypatch.setattr(instance, "capacity", lambda _: pytest.fail("Existing jobs requested new capacity"))
    instance.run_batch(batch, mesh, simulation)
    assert simulation.start_count == 0
    assert batch["status"] == "completed"
    assert instance.report["progress"]["effective_parallel_cores"] <= instance.request["max_parallel_cores"]


@pytest.mark.parametrize("parent_status", ["PARTIAL_SUCCESS", "ERROR", "ABORTED"])
def test_failed_parent_cannot_return_as_a_successful_stage_even_with_numeric_rows(tmp_path, monkeypatch, cloud_jobs, parent_status):
    instance = worker(tmp_path, candidate_count=1, max_parallel_cores=64)
    batch = search_batch(instance)
    simulation = FixtureSimulation(batch["points"], cloud_jobs, parent_status=getattr(cloud_jobs, parent_status))
    cloud_jobs.statuses["fixture-mesh"] = cloud_jobs.SUCCESS
    mesh = SimpleNamespace(_job=cloud_jobs("fixture-project", "fixture-mesh"),
                           refresh=lambda: None, get_sweep_count=lambda: len(batch["points"]))
    with pytest.raises(RuntimeError, match="simulation failed"):
        instance.run_batch(batch, mesh, simulation)
    assert batch["status"] == "failed"
    assert len(instance.state["results"]) == len(batch["points"])
    assert instance.report["status"] != "completed"
    assert not (instance.report["best_design"] or {}).get("validated", False)
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["batches"][0]["status"] == "failed"
    assert saved["batches"][0]["simulation_job_id"] == "fixture-parent"


def test_mismatched_mesh_guard_stops_before_any_simulation_access(tmp_path, monkeypatch, cloud_jobs):
    instance = worker(tmp_path, candidate_count=1)
    batch = search_batch(instance)
    batch["mesh_geometry_verified"] = False
    cloud_jobs.statuses["fixture-mesh"] = cloud_jobs.SUCCESS
    mesh = SimpleNamespace(_job=cloud_jobs("fixture-project", "fixture-mesh"),
                           refresh=lambda: None, get_sweep_count=lambda: 1)

    def reject_mesh(*_):
        raise RuntimeError("Downloaded mesh dimensions differ from the submitted geometry")

    monkeypatch.setattr(instance, "audit_mesh", reject_mesh)
    simulation = SimpleNamespace(_get_job=lambda: pytest.fail("A mismatched mesh reached a simulation"))
    with pytest.raises(RuntimeError, match="mesh dimensions differ"):
        instance.run_batch(batch, mesh, simulation)
    assert instance.state["results"] == []
    assert instance.report["best_design"] is None


def test_capacity_uses_child_threshold_and_leaves_cloud_scheduler_to_queue_batch(tmp_path, monkeypatch):
    instance = worker(tmp_path, max_parallel_cores=256)
    quota = SimpleNamespace(max_concurrent_cores=256, total_running_cores=196, total_reserved_cores=0)
    monkeypatch.setattr(runner.allsolve, "get_quota", lambda: quota)
    monkeypatch.setattr(runner.time, "sleep", lambda _: pytest.fail("Available child capacity was ignored"))
    instance.capacity(255)


def test_dense_summary_distinguishes_partial_pairs_failed_refinement_and_coarse_score(tmp_path):
    instance = worker(tmp_path, candidate_count=3)
    candidates = instance.report["candidates"]
    candidates[0].update(status="completed", score=0.6, valid=True)
    candidates[1].update(status="completed", score=0.7, valid=True)
    original = copy.deepcopy(candidates)
    points = make_points(candidates[:2], instance.request, wavelengths=[990, 1000, 1010])
    rows = []
    for point in points:
        difference = 0.35 if point["wavelength_nm"] == 1000 else 0.1
        row = result(point, stage="dense", reflectance=0.2 + difference * point["input_index"])
        if point["candidate_id"] == 0:
            invalid = point["wavelength_nm"] == 1010 and point["input_index"] == 1
        else:
            # Two individually valid points at different wavelengths cannot pair.
            invalid = (point["wavelength_nm"], point["input_index"]) not in {(990, 0), (1000, 1)}
        if invalid:
            row.update(valid=False, error="Incident normalization failed; Fixed readout gate failed")
        rows.append(row)
    summaries = runner.add_dense_verification(candidates, rows, points)
    passed, failed = summaries[0], summaries[1]
    assert (passed["status"], passed["valid_points"], passed["total_points"]) == ("passed", 5, 6)
    assert (passed["valid_pairs"], passed["total_pairs"]) == (2, 3)
    assert passed["best_valid_score"] == pytest.approx(0.35)
    assert passed["best_valid_wavelength_nm"] == 1000
    assert (failed["status"], failed["valid_points"], failed["total_points"]) == ("failed", 2, 6)
    assert failed["valid_pairs"] == 0 and failed["total_pairs"] == 3
    assert failed["best_valid_score"] is None and failed["best_valid_wavelength_nm"] is None
    assert failed["errors"] == ["Fixed readout gate failed", "Incident normalization failed"]
    for before, after in zip(original, candidates):
        assert {key: value for key, value in after.items() if key != "dense_verification"} == before
    assert "dense_verification" not in candidates[2]


def test_duplicate_dense_point_cannot_create_a_valid_paired_summary(tmp_path):
    instance = worker(tmp_path, candidate_count=1)
    points = make_points(instance.report["candidates"], instance.request, wavelengths=[1000])
    rows = [result(point, "dense") for point in points]
    rows.append(copy.deepcopy(rows[0]))
    summary = runner.dense_refinement_summaries(rows, points)[0]
    assert summary["status"] == "failed"
    assert summary["valid_points"] == 1 and summary["valid_pairs"] == 0
    assert summary["best_valid_score"] is None
    assert "duplicate" in summary["errors"][0]


def test_completed_report_enrichment_backs_up_exact_original_and_preserves_all_evidence(tmp_path, monkeypatch):
    instance = worker(tmp_path, candidate_count=1)
    points = make_points(instance.report["candidates"], instance.request, wavelengths=[1000])
    rows = [result(point, "dense", reflectance=0.2 + 0.3 * point["input_index"]) for point in points]
    instance.state.update(phase="completed", results=rows,
                          batches=[{"stage": "dense", "points": points, "name": "dense 1", "status": "completed"}])
    instance.report.update(status="completed", best_design={"candidate_id": 0, "validated": True,
                                                           "R_A": 0.20123456789, "R_B": 0.50123456789})
    runner.atomic_json(tmp_path / "report.json", instance.report)
    runner.atomic_json(tmp_path / "state.json", instance.state)
    (tmp_path / "source_readout.py").write_text("# Saved real source evidence\n")
    original = (tmp_path / "report.json").read_bytes()
    saved_state, saved_source = (tmp_path / "state.json").read_bytes(), (tmp_path / "source_readout.py").read_bytes()
    monkeypatch.setattr(runner.allsolve, "Client", lambda **_: pytest.fail("Report enrichment attempted a cloud connection"))
    first = runner.enrich_completed_report(tmp_path)
    enriched = runner.read_json(tmp_path / "report.json")
    assert Path(first["backup_path"]).read_bytes() == original
    assert enriched["best_design"] == instance.report["best_design"]
    assert enriched["candidates"][0]["dense_verification"]["best_valid_score"] == pytest.approx(0.3)
    without_summary = copy.deepcopy(enriched)
    del without_summary["candidates"][0]["dense_verification"]
    assert without_summary == instance.report
    after = (tmp_path / "report.json").read_bytes()
    assert runner.enrich_completed_report(tmp_path) == first
    assert (tmp_path / "report.json").read_bytes() == after
    assert Path(first["backup_path"]).read_bytes() == original
    assert (tmp_path / "state.json").read_bytes() == saved_state
    assert (tmp_path / "source_readout.py").read_bytes() == saved_source


def test_report_enrichment_refuses_unfinished_job_without_writing_backup(tmp_path):
    instance = worker(tmp_path, candidate_count=1)
    runner.atomic_json(tmp_path / "report.json", instance.report)
    runner.atomic_json(tmp_path / "state.json", instance.state)
    before = (tmp_path / "report.json").read_bytes()
    with pytest.raises(ValueError, match="completed real cloud report"):
        runner.enrich_completed_report(tmp_path)
    assert (tmp_path / "report.json").read_bytes() == before
    assert not (tmp_path / "report.before_dense_verification.json").exists()


@pytest.mark.parametrize("changed", ["source", "request"])
def test_source_and_request_hash_changes_reject_resume_before_sdk_access(tmp_path, monkeypatch, changed):
    req = request(candidate_count=1)
    report = runner.initial_report(req)
    source_digest = hashlib.sha256((runner.HERE / "source_readout.py").read_text(encoding="utf-8").encode()).hexdigest()
    state = {"source_sha256": source_digest,
             "request_sha256": hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest(),
             "batches": [], "results": [], "phase": "search", "project_id": "fixture-project"}
    if changed == "source":
        state["source_sha256"] = "0" * 64
    else:
        req["seed"] += 1
    for name, value in (("request", req), ("report", report), ("state", state)):
        runner.atomic_json(tmp_path / (name + ".json"), value)
    monkeypatch.setattr(runner.allsolve, "Client", lambda **_: pytest.fail("Mismatch reached the SDK"))
    with pytest.raises(RuntimeError, match="source changed|saved request changed"):
        runner.Worker(tmp_path)


def test_completed_report_resume_performs_no_solver_launch(tmp_path, monkeypatch):
    req = request(candidate_count=1)
    report = runner.initial_report(req)
    report.update(status="completed", stage="Verified best sampled design")
    source_digest = hashlib.sha256((runner.HERE / "source_readout.py").read_text(encoding="utf-8").encode()).hexdigest()
    state = {"source_sha256": source_digest,
             "request_sha256": hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest(),
             "batches": [], "results": [], "phase": "completed", "project_id": "fixture-project"}
    for name, value in (("request", req), ("report", report), ("state", state)):
        runner.atomic_json(tmp_path / (name + ".json"), value)
    monkeypatch.setattr(runner.allsolve, "Client", lambda **_: SimpleNamespace(get_project=lambda _: object()))
    instance = runner.Worker(tmp_path)
    monkeypatch.setattr(instance, "run_points", lambda *_: pytest.fail("Completed optimization launched work"))
    instance.run()
    assert instance.report["status"] == "completed"
    assert instance.state["phase"] == "completed"


def test_resume_uses_frozen_job_source_when_package_source_has_changed(tmp_path, monkeypatch):
    req = request(candidate_count=1)
    frozen = "# Original frozen cloud source\n"
    package = tmp_path / "updated_package"
    package.mkdir()
    (package / "source_readout.py").write_text("# New package source for future jobs\n", encoding="utf-8")
    (tmp_path / "source_readout.py").write_text(frozen, encoding="utf-8")
    state = {"source_sha256": hashlib.sha256(frozen.encode()).hexdigest(),
             "request_sha256": hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest(),
             "batches": [], "results": [], "phase": "search", "project_id": "fixture-project"}
    runner.atomic_json(tmp_path / "state.json", state)
    runner.atomic_json(tmp_path / "request.json", req)
    runner.atomic_json(tmp_path / "report.json", runner.initial_report(req))
    monkeypatch.setattr(runner, "HERE", package)
    monkeypatch.setattr(runner.allsolve, "Client", lambda **_: SimpleNamespace(get_project=lambda _: object()))
    instance = runner.Worker(tmp_path)
    assert instance.source_path == tmp_path / "source_readout.py"
    assert instance.source_path.read_text(encoding="utf-8") == frozen
    assert instance.state["source_sha256"] == state["source_sha256"]


@pytest.mark.parametrize("failed_finalist", [False, True, "mesh"])
def test_full_orchestration_completion_requires_verified_finalist_and_persists_progress(tmp_path, monkeypatch, cloud_jobs, failed_finalist):
    instance = worker(tmp_path, max_parallel_cores=64)
    calls = []

    def build(project, req, points, **kwargs):
        calls.append(kwargs)
        return object(), object(), {"mesh_id": f"mesh-{len(calls)}", "simulation_id": f"sim-{len(calls)}",
                                   "mesh_geometry_verified": failed_finalist != "mesh"}

    def complete(batch, *_):
        statuses = {0: cloud_jobs.PARTIAL_SUCCESS} if failed_finalist is True and batch["stage"] == "fine" else {}
        simulation = FixtureSimulation(batch["points"], cloud_jobs, child_statuses=statuses)
        for i, point in enumerate(batch["points"]):
            if batch["stage"] == "search":
                difference = 0.2 if point["candidate_id"] == 0 else 0.1
            else:
                difference = 0.2 if point["candidate_id"] == 0 else 0.4
            simulation.outputs[i] = optical_outputs(point, 0.2 + difference * point["input_index"])
        instance.collect(batch, simulation, terminal=True)
        batch["status"] = "completed"
        instance.publish()

    monkeypatch.setattr(runner, "create_batch", build)
    monkeypatch.setattr(instance, "run_batch", complete)
    monkeypatch.setattr(runner, "reflectance_transmittance",
                        lambda **kwargs: {"R0": 0.2 if kwargs["n_liquid"] == 1.33 else 0.6})
    if failed_finalist:
        with pytest.raises(RuntimeError, match="finalist failed|finalist did not meet"):
            instance.run()
        assert instance.report["status"] != "completed"
        assert instance.report["best_design"]["validated"] is False
        assert not any(candidate["verified"] for candidate in instance.report["candidates"])
        return
    instance.run()
    saved = json.loads((tmp_path / "report.json").read_text())
    assert saved["status"] == "completed"
    assert saved["best_design"]["validated"] is True
    assert saved["best_design"]["candidate_id"] == 1
    assert saved["best_design"]["score"] == pytest.approx(0.4)
    assert saved["best_design"]["verification"]["checks"]["readout_checks"] is True
    assert saved["best_design"]["verification"]["checks"]["mesh_dimensions"] is True
    assert all(candidate["dense_verification"]["status"] == "passed" for candidate in saved["candidates"])
    assert all(candidate["dense_verification"]["valid_pairs"] == 21 for candidate in saved["candidates"])
    assert {spectrum["stage"] for spectrum in saved["spectra"]} == {"search", "dense", "fine", "clearance"}
    assert saved["progress"]["planned_solve_count"] == 100  # 12 search + 84 dense + 2 fine + 2 clearance
    assert saved["progress"]["completed_solve_count"] == 100
    assert saved["progress"]["failed_solve_count"] == 0
    assert saved["progress"]["effective_parallel_cores"] == 0
    assert saved["progress"]["batches_completed"] == saved["progress"]["batches_total"]
    assert json.loads((tmp_path / "state.json").read_text())["phase"] == "completed"
    before = len(calls)
    instance.run()
    assert len(calls) == before
    assert instance.report["progress"]["planned_solve_count"] == 100


class FixtureProject:
    """Local project boundary; real SDK settings/refinement/runtime/script objects."""
    id = "fixture-project"

    def __init__(self):
        self.mesh_settings = None
        self.simulation_kwargs = None
        self.runtime = None

    def create_variable_overrides(self, **kwargs):
        self.sweep_kwargs = kwargs
        return SimpleNamespace(id="fixture-sweep")

    def get_regions(self):
        return [SimpleNamespace(name=name, id=name, entity_type=runner.allsolve.Region.VOLUME)
                for name in ("ridge", "film")]

    def create_mesh(self, settings):
        self.mesh_settings = settings
        return SimpleNamespace(id="fixture-mesh", get_override=lambda _: SimpleNamespace(id="fixture-instance"))

    def get_default_physics_set(self):
        return SimpleNamespace(id="fixture-physics")

    def create_simulation_harmonic(self, **kwargs):
        self.simulation_kwargs = kwargs
        project = self

        class Simulation:
            id = "fixture-simulation"

            def set_runtime(self, runtime):
                project.runtime = runtime

            def save(self):
                pass

            def set_scripts(self, scripts):
                project.scripts = scripts

        return Simulation()


@pytest.mark.parametrize("stage,cores,max_minutes", [("coarse", 3, 15), ("fine", 4, 30)])
def test_batch_runtime_caps_and_lockstep_mesh_simulation_use_real_sdk_constructors(stage, cores, max_minutes):
    req = request(candidate_count=1)
    points = make_points(runner.initial_report(req)["candidates"], req)
    project = FixtureProject()
    _, _, metadata = physics.create_batch(project, req, points, stage=stage)
    assert project.mesh_settings.max_run_time_minutes <= max_minutes
    assert project.simulation_kwargs["max_run_time_minutes"] <= max_minutes
    expected = (runner.allsolve.CPU.CORES_3_10GB_FAST_START if cores == 3 else runner.allsolve.CPU.CORES_4_64GB)
    assert project.runtime.node_type == expected
    assert metadata["mesh_cores"] == metadata["simulation_cores"] == cores
    assert project.mesh_settings.variable_overrides[0] is project.simulation_kwargs["variable_overrides"]
    assert project.sweep_kwargs["sweep_type"] == runner.allsolve.SweepType.SPECIFIC_VALUES
    columns = dict(project.sweep_kwargs["overrides"])
    assert all(len(values) == len(points) for values in columns.values())
    assert columns["candidate_id"] == [p["candidate_id"] for p in points]
    assert columns["input_index"] == [p["input_index"] for p in points]
    assert columns["wavelength"] == pytest.approx([p["wavelength_nm"] * 1e-9 for p in points])
    assert columns["n_liquid"] == [p["n_liquid"] for p in points]
    assert all(value == 0 for value in columns["write_fields"])
    assert project.scripts[0].content == (physics.HERE / "source_readout.py").read_text(encoding="utf-8")
