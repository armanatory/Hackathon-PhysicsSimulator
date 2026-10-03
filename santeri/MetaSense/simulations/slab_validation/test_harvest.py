"""Fake SDK jobs verify harvest gates without cloud calls or synthetic claims."""

import copy
import json

import allsolve
import pytest

from .harvest import harvest


R_QUARTER = 25 / 169
T_QUARTER = 144 / 169


def case_outputs(index, *, R=None, T=None, incident_ratio=1.0, backward_fraction=0.0,
                 cross_fraction=0.0):
    # The independent fixture's quarter-wave fractions are exact rational values.
    if R is None:
        R = 0.0 if index == 1.0 else R_QUARTER
    if T is None:
        T = 1.0 if index == 1.0 else T_QUARTER
    specified = 0.001
    pin = specified * incident_ratio
    values = {
        "slab_index": index, "specified_incident_power_W": specified,
        "entrance_forward_power_W": pin, "entrance_backward_power_W": pin * R,
        "exit_forward_power_W": pin * T, "exit_backward_power_W": pin * backward_fraction,
        "reflectance": R, "transmittance": T, "energy_residual": 1.0 - R - T,
        "incident_normalization_ratio": incident_ratio, "exit_backward_fraction": backward_fraction,
        "entrance_crosspolarized_power_W": pin * cross_fraction,
        "exit_crosspolarized_power_W": pin * cross_fraction,
        "entrance_net_flux_W": pin * (1 - R), "exit_net_flux_W": pin * (T - backward_fraction),
        "entrance_poynting_flux_W": pin * (1 - R), "exit_poynting_flux_W": pin * (T - backward_fraction),
        "entrance_Ex_cos": 1.0, "entrance_Ex_sin": 0.0,
        "entrance_Hy_cos": 0.002, "entrance_Hy_sin": 0.0,
        "exit_Ex_cos": 0.0, "exit_Ex_sin": 0.8,
        "exit_Hy_cos": 0.0, "exit_Hy_sin": 0.002,
    }
    return {"nostep": {name: [value] for name, value in values.items()}}


class FakeOutputData:
    def to_csv(self):
        return "slab_index,reflectance,transmittance\n1,0,1\n1.5,0.147928994,0.852071006\n"


class FakeSimulation:
    def __init__(self, simulation_id, *, status=allsolve.Job.SUCCESS, outputs=None):
        self.id = simulation_id
        self.status = status
        self.outputs = outputs if outputs is not None else [case_outputs(1.0), case_outputs(1.5)]
        self.calls = []

    def get_status(self):
        self.calls.append(("get_status",))
        return self.status

    def get_output_values(self, sweep_index, refresh=False):
        self.calls.append(("get_output_values", sweep_index, refresh))
        output = self.outputs[sweep_index]
        if isinstance(output, Exception):
            raise output
        return copy.deepcopy(output)

    def get_output_data(self, refresh=True):
        self.calls.append(("get_output_data", refresh))
        return FakeOutputData()


class FakeProject:
    def __init__(self, simulations):
        self.simulations = simulations

    def get_simulations(self):
        return self.simulations


@pytest.fixture
def state():
    return {
        "project_id": "project-fixture", "project_url": "https://example.invalid/project-fixture",
        "stage": "configured", "sdk_version": "fixture",
        "inputs": {"wavelength_m": 1000e-9, "slab_thickness_m": 1000e-9 / 6,
                   "period_m": 500e-9, "indices": [1.0, 1.5], "exterior_index": 1.0,
                   "E0_V_per_m": 1, "polarization": "x", "propagation": "+z"},
        "runs": [
            {"name": "coarse", "simulation_id": "coarse-id", "mesh_id": "coarse-mesh",
             "mesh_job_id": "coarse-mesh-job", "simulation_job_id": "coarse-sim-job",
             "source_sha256": "a" * 64, "resolution_per_vacuum_wavelength": 12},
            {"name": "fine", "simulation_id": "fine-id", "mesh_id": "fine-mesh",
             "mesh_job_id": "fine-mesh-job", "simulation_job_id": "fine-sim-job",
             "source_sha256": "a" * 64, "resolution_per_vacuum_wavelength": 18},
        ],
        "failed_attempts": [{"simulation_job_id": "old-failed-job", "reason": "original source failed"}],
    }


def project(coarse=None, fine=None):
    return FakeProject([coarse or FakeSimulation("coarse-id"), fine or FakeSimulation("fine-id")])


def test_valid_two_mesh_benchmark_preserves_metadata_and_public_outputs(state, tmp_path):
    simulation = FakeSimulation("coarse-id")
    report = harvest(project(coarse=simulation), state, tmp_path)
    assert report["validated"]
    assert report["status"] == "completed"
    assert report["label"] == "allsolve_slab_validation"
    assert report["purpose"] == "optical_slab_benchmark"
    assert report["synthetic"] is False
    assert report["state_provenance"] == state
    assert report["runs"][0]["metadata"] == state["runs"][0]
    assert report["analytical_reference"]["dielectric_slab"]["R"] == pytest.approx(R_QUARTER)
    assert report["analytical_reference"]["dielectric_slab"]["t"]["imag"] == pytest.approx(-12 / 13)
    assert report["convergence"]["dielectric_slab"]["delta_R"] == pytest.approx(0)
    assert json.loads((tmp_path / "report.json").read_text()) == report
    raw = json.loads((tmp_path / "coarse" / "raw_output_sweep_0.json").read_text())
    assert raw["public_output_values"] == case_outputs(1.0)
    assert (tmp_path / "fine" / "public_outputs.csv").read_text().startswith("slab_index,")
    assert simulation.calls == [("get_status",), ("get_output_values", 0, True),
                                ("get_output_values", 1, True), ("get_output_data", False)]


def test_reordered_sweeps_are_matched_by_reported_index(state, tmp_path):
    coarse = FakeSimulation("coarse-id", outputs=[case_outputs(1.5), case_outputs(1.0)])
    report = harvest(project(coarse=coarse), state, tmp_path)
    assert report["validated"]
    assert report["runs"][0]["cases"]["vacuum_control"]["sweep_index"] == 1
    assert report["runs"][0]["cases"]["dielectric_slab"]["sweep_index"] == 0


@pytest.mark.parametrize("status,expected", [(None, "queued"), (allsolve.Job.QUEUED, "queued"),
    (allsolve.Job.SUBMITTED, "queued"), (allsolve.Job.RUNNING, "running"),
    (allsolve.Job.STARTING, "running"), (allsolve.Job.PROCESSING_OUTPUT, "running"),
    (allsolve.Job.ERROR, "failed"), (allsolve.Job.ABORTED, "failed"),
    (allsolve.Job.PARTIAL_SUCCESS, "failed")])
def test_unfinished_or_failed_jobs_are_never_harvested_or_validated(state, tmp_path, status, expected):
    fine = FakeSimulation("fine-id", status=status)
    report = harvest(project(fine=fine), state, tmp_path)
    assert report["status"] == expected
    assert report["validated"] is False
    assert fine.calls == [("get_status",)]
    assert report["runs"][1]["cases"] == {}


def test_missing_fine_mesh_is_queued_and_does_not_validate_coarse_alone(state, tmp_path):
    state["runs"] = state["runs"][:1]
    report = harvest(project(), state, tmp_path)
    assert report["status"] == "queued"
    assert report["validated"] is False
    assert "Missing required run: fine" in report["errors"]


def test_missing_simulation_is_failed(state, tmp_path):
    report = harvest(FakeProject([FakeSimulation("coarse-id")]), state, tmp_path)
    assert report["status"] == "failed"
    assert report["validated"] is False
    assert any("Simulation not found" in error for error in report["errors"])


@pytest.mark.parametrize("second", [{}, RuntimeError("output unavailable"), case_outputs(2.0), case_outputs(1.0)])
def test_missing_failed_unexpected_or_duplicate_sweep_is_failed(state, tmp_path, second):
    coarse = FakeSimulation("coarse-id", outputs=[case_outputs(1.0), second])
    report = harvest(project(coarse=coarse), state, tmp_path)
    assert report["status"] == "failed"
    assert report["validated"] is False
    assert any("Missing benchmark case: dielectric_slab" in error for error in report["errors"])


def test_energy_balance_does_not_allow_wrong_reference_results(state, tmp_path):
    bad = case_outputs(1.5, R=R_QUARTER + 0.03, T=T_QUARTER - 0.03)
    report = harvest(project(coarse=FakeSimulation("coarse-id", outputs=[case_outputs(1.0), bad])), state, tmp_path)
    checks = report["runs"][0]["cases"]["dielectric_slab"]["checks"]
    assert checks["energy_balance"]
    assert not checks["reflectance_reference"]
    assert not checks["transmittance_reference"]
    assert report["status"] == "completed"
    assert not report["validated"]


def test_each_reference_error_within_tolerance_can_still_fail_energy(state, tmp_path):
    bad = case_outputs(1.5, R=R_QUARTER + 0.008, T=T_QUARTER + 0.008)
    report = harvest(project(fine=FakeSimulation("fine-id", outputs=[case_outputs(1.0), bad])), state, tmp_path)
    checks = report["runs"][1]["cases"]["dielectric_slab"]["checks"]
    assert checks["reflectance_reference"] and checks["transmittance_reference"]
    assert not checks["energy_balance"]
    assert not report["validated"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_raw_results_are_preserved_and_rejected(state, tmp_path, value):
    bad = case_outputs(1.5)
    bad["nostep"]["energy_residual"] = [value]
    report = harvest(project(fine=FakeSimulation("fine-id", outputs=[case_outputs(1.0), bad])), state, tmp_path)
    assert not report["validated"]
    case = report["runs"][1]["cases"]["dielectric_slab"]
    assert not case["checks"]["all_required_outputs_finite"]
    raw = json.loads((tmp_path / "fine" / "raw_output_sweep_1.json").read_text())
    assert raw["public_output_values"]["nostep"]["energy_residual"] == [{"nonfinite": repr(value)}]
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("name,value,check", [
    ("entrance_forward_power_W", 0, "positive_incident_power"),
    ("entrance_backward_power_W", -1e-5, "nonnegative_powers"),
    ("incident_normalization_ratio", 0.5, "reported_scalar_consistency"),
    ("reflectance", 0.0, "reported_scalar_consistency"),
    ("entrance_poynting_flux_W", 0, "entrance_flux_consistency"),
])
def test_bad_power_and_scalar_consistency_are_rejected(state, tmp_path, name, value, check):
    bad = case_outputs(1.5)
    bad["nostep"][name] = [value]
    report = harvest(project(fine=FakeSimulation("fine-id", outputs=[case_outputs(1.0), bad])), state, tmp_path)
    assert not report["validated"]
    assert not report["runs"][1]["cases"]["dielectric_slab"]["checks"][check]


@pytest.mark.parametrize("argument,value,check", [
    ("incident_ratio", 1.03, "incident_normalization"),
    ("backward_fraction", 0.002, "exit_incoming_wave"),
    ("cross_fraction", 0.0002, "entrance_polarization"),
])
def test_source_boundary_and_polarization_checks(state, tmp_path, argument, value, check):
    bad = case_outputs(1.5, **{argument: value})
    report = harvest(project(coarse=FakeSimulation("coarse-id", outputs=[case_outputs(1.0), bad])), state, tmp_path)
    assert not report["validated"]
    assert not report["runs"][0]["cases"]["dielectric_slab"]["checks"][check]


def test_reference_checks_can_pass_while_mesh_convergence_fails(state, tmp_path):
    coarse_case = case_outputs(1.5, R=R_QUARTER - 0.004, T=T_QUARTER + 0.004)
    fine_case = case_outputs(1.5, R=R_QUARTER + 0.004, T=T_QUARTER - 0.004)
    report = harvest(project(
        coarse=FakeSimulation("coarse-id", outputs=[case_outputs(1.0), coarse_case]),
        fine=FakeSimulation("fine-id", outputs=[case_outputs(1.0), fine_case])), state, tmp_path)
    assert all(run["passed"] for run in report["runs"])
    assert report["convergence"]["dielectric_slab"]["delta_R"] == pytest.approx(0.008)
    assert not report["convergence"]["passed"]
    assert not report["validated"]


def test_convergence_cannot_compare_different_source_revisions(state, tmp_path):
    state["runs"][1]["source_sha256"] = "b" * 64
    report = harvest(project(), state, tmp_path)
    assert not report["convergence"]["same_source"]
    assert not report["validated"]


def test_invalid_benchmark_inputs_fail_without_network_reads(state, tmp_path):
    state["inputs"]["wavelength_m"] = float("nan")

    class NoNetwork:
        def get_simulations(self):
            raise AssertionError("No SDK reads are needed for invalid inputs")

    report = harvest(NoNetwork(), state, tmp_path)
    assert report["status"] == "failed"
    assert not report["validated"]
    assert any("Invalid benchmark inputs" in error for error in report["errors"])
    json.dumps(report, allow_nan=False)
