"""Verified local-worker maintenance tests; no processes or cloud jobs are stopped."""
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

CASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CASE))
sys.path.insert(0, str(CASE / "backend"))
from app.discriminator import DiscriminatorManager
from app.discriminator_models import DiscriminatorRequest
from simulations.liquid_discriminator import resume_local_worker as maintenance


def local_process(pid, parent_pid, interpreter, runner, folder):
    return maintenance.LocalProcess(pid, parent_pid, str(interpreter),
                                    (str(interpreter), str(runner), "run", "--job-dir", str(folder)))


def test_exact_worker_selection_handles_venv_wrapper_child_and_ignores_other_job(tmp_path):
    executable = tmp_path / "case with spaces" / ".venv" / "Scripts" / "python.exe"
    runner = tmp_path / "case with spaces" / "runner.py"
    folder = tmp_path / "jobs" / ("a" * 32)
    processes = [local_process(10, 1, executable, runner, folder),
                 local_process(11, 10, executable, runner, folder),
                 local_process(12, 1, executable, runner, tmp_path / "other_job")]
    selected = maintenance.select_worker_processes(processes, saved_pid=10, runner_path=runner,
        folder=folder, interpreters={maintenance._path_key(executable)})
    assert [process.pid for process in selected] == [11, 10]


@pytest.mark.parametrize("unsafe", ["different_runner", "different_folder", "different_executable", "independent_duplicate"])
def test_unsafe_process_matches_cannot_be_selected(tmp_path, unsafe):
    executable = tmp_path / "python.exe"
    runner, folder = tmp_path / "runner.py", tmp_path / "job"
    process = local_process(10, 1, executable, runner, folder)
    processes = [process]
    if unsafe == "different_runner":
        processes = [local_process(10, 1, executable, tmp_path / "other_runner.py", folder)]
    elif unsafe == "different_folder":
        processes = [local_process(10, 1, executable, runner, tmp_path / "other_job")]
    elif unsafe == "different_executable":
        processes = [local_process(10, 1, tmp_path / "unknown_python.exe", runner, folder)]
    else:
        processes.append(local_process(11, 1, executable, runner, folder))
    with pytest.raises(maintenance.MaintenanceError):
        maintenance.select_worker_processes(processes, saved_pid=10, runner_path=runner,
            folder=folder, interpreters={maintenance._path_key(executable)})


@pytest.mark.skipif(os.name != "nt", reason="The parser uses Windows' own command-line API")
def test_windows_command_line_parser_preserves_absolute_paths_with_spaces(tmp_path):
    args = [str(tmp_path / "case with spaces" / "python.exe"),
            str(tmp_path / "case with spaces" / "runner.py"), "run", "--job-dir",
            str(tmp_path / "case with spaces" / "jobs" / ("a" * 32))]
    assert maintenance._windows_arguments(subprocess.list2cmdline(args)) == tuple(args)


@pytest.fixture
def saved_worker(tmp_path, monkeypatch):
    case = tmp_path / "c"
    runner = case / "simulations" / "liquid_discriminator" / "runner.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("# Local test runner; never executed\n", encoding="utf-8")
    interpreter = case / ".venv" / "Scripts" / "python.exe"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b"Fixture only")
    manager = DiscriminatorManager(case / "jobs", runner)
    job_id = "a" * 32
    folder = manager.job_root / job_id
    folder.mkdir(parents=True)
    source = "# Frozen fixture source\n"
    (folder / "source_readout.py").write_text(source, encoding="utf-8")
    request = DiscriminatorRequest().model_dump()
    request = DiscriminatorRequest.model_validate(request).model_dump()
    metadata = {"id": job_id, "pid": 10, "process_identity": "old-start", "status": "running",
                "created_at": "fixture", "updated_at": "fixture", "request": request}
    state = {"project_id": "fixture-project", "phase": "search", "batches": [], "results": [],
             "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
             "request_sha256": hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()}
    report = {"label": "allsolve_liquid_discriminator", "synthetic": False, "status": "running"}
    for name, value in (("job", metadata), ("request", request), ("state", state), ("report", report)):
        maintenance.discriminator._atomic_json(folder / (name + ".json"), value)
    (folder / "worker.log").write_text("Prior private log\n", encoding="utf-8")
    identities = {10: "old-start", 11: "child-start", 99: "new-start"}
    monkeypatch.setattr(maintenance.discriminator, "_process_identity", identities.get)
    records = [local_process(10, 1, interpreter, runner, folder),
               local_process(11, 10, Path(sys._base_executable), runner, folder)]
    calls = {"stopped": [], "launches": []}
    monkeypatch.setattr(maintenance, "_windows_processes", lambda: [record for record in records if record.pid in identities])

    def stop(pid, identity):
        assert identities[pid] == identity
        calls["stopped"].append(pid)
        del identities[pid]
        return True

    def launch(args, **kwargs):
        calls["launches"].append((args, kwargs))
        kwargs["stdout"].write(b"Resumed private log\n")
        return SimpleNamespace(pid=99)

    monkeypatch.setattr(maintenance, "_terminate_verified_process", stop)
    monkeypatch.setattr(maintenance.subprocess, "Popen", launch)
    return SimpleNamespace(manager=manager, job_id=job_id, folder=folder, runner=runner,
                           interpreter=interpreter, metadata=metadata, state=state,
                           identities=identities, records=records, calls=calls)


@pytest.mark.skipif(os.name != "nt", reason="Maintenance verifies Windows workers only")
def test_resume_only_restarts_verified_local_processes_and_records_previous_metadata(saved_worker, monkeypatch):
    fixture = saved_worker
    monkeypatch.setenv("ALLSOLVE_SECRET_KEY", "private-fixture-secret")
    result = maintenance.resume_local_worker(fixture.job_id, "Load collector and mesh guards", manager=fixture.manager)
    assert fixture.calls["stopped"] == [11, 10]
    assert result["no_cloud_restart"] is True
    assert result["pid"] == 99
    assert len(fixture.calls["launches"]) == 1
    args, kwargs = fixture.calls["launches"][0]
    assert args == [str(fixture.interpreter), str(fixture.runner), "run", "--job-dir", str(fixture.folder)]
    assert kwargs["env"]["ALLSOLVE_SECRET_KEY"] == "private-fixture-secret"
    assert kwargs["shell"] is False
    saved = json.loads((fixture.folder / "job.json").read_text())
    assert saved["pid"] == 99 and saved["process_identity"] == "new-start"
    assert saved["status"] == "running" and saved["error"] is None
    record = json.loads(Path(result["maintenance_record"]).read_text())
    assert record["previous_metadata"] == fixture.metadata
    assert record["status"] == "completed" and record["no_cloud_restart"] is True
    assert "private-fixture-secret" not in json.dumps(record)
    assert "private-fixture-secret" not in json.dumps(result)
    assert (fixture.folder / "worker.log").read_text() == "Prior private log\nResumed private log\n"
    assert json.loads((fixture.folder / "state.json").read_text()) == fixture.state


@pytest.mark.skipif(os.name != "nt", reason="Maintenance verifies Windows workers only")
@pytest.mark.parametrize("unsafe", ["pid_reused", "source_changed", "request_changed", "completed", "duplicate"])
def test_resume_refuses_unsafe_evidence_before_stopping_any_process(saved_worker, unsafe):
    fixture = saved_worker
    if unsafe == "pid_reused":
        fixture.identities[10] = "different-process-start"
    elif unsafe == "source_changed":
        (fixture.folder / "source_readout.py").write_text("Changed fixture\n")
    elif unsafe == "request_changed":
        request = copy.deepcopy(fixture.metadata["request"])
        request["seed"] += 1
        maintenance.discriminator._atomic_json(fixture.folder / "request.json", request)
    elif unsafe == "completed":
        maintenance.discriminator._atomic_json(fixture.folder / "report.json", {"status": "completed"})
    else:
        fixture.identities[12] = "independent-start"
        fixture.records.append(local_process(12, 1, fixture.interpreter, fixture.runner, fixture.folder))
    with pytest.raises(maintenance.MaintenanceError):
        maintenance.resume_local_worker(fixture.job_id, "Load tested runner fixes", manager=fixture.manager)
    assert fixture.calls["stopped"] == []
    assert fixture.calls["launches"] == []
    assert json.loads((fixture.folder / "job.json").read_text()) == fixture.metadata
