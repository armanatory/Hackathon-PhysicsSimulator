"""Restart one verified local Windows worker while preserving its cloud evidence.

This maintenance command neither aborts nor restarts any Allsolve cloud job.
The durable runner resumes saved cloud IDs and submits only its remaining work.
Run with the case's virtual-environment Python; credentials stay in the inherited
environment or the runner's existing private root .env fallback.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

CASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CASE / "backend"))
from app import discriminator
from app.discriminator_models import DiscriminatorRequest


class MaintenanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class LocalProcess:
    pid: int
    parent_pid: int
    executable: str
    arguments: tuple[str, ...]


def _path_key(path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def _windows_arguments(command_line: str) -> tuple[str, ...]:
    """Use Windows' own parser, preserving paths with spaces and escaped quotes."""
    from ctypes import wintypes

    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    pointer = shell.CommandLineToArgvW(command_line, ctypes.byref(count))
    if not pointer:
        raise MaintenanceError("Cannot parse a local process command line")
    try:
        return tuple(pointer[index] for index in range(count.value))
    finally:
        kernel.LocalFree(ctypes.cast(pointer, wintypes.HLOCAL))


def _windows_processes() -> list[LocalProcess]:
    # Fixed read-only script, with no shell interpolation or credentials in args.
    script = (
        "$ErrorActionPreference='Stop'; "
        "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' OR Name = 'pythonw.exe'\" "
        "| Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine "
        "| ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", check=False, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise MaintenanceError("Cannot inspect local Windows workers")
    try:
        rows = json.loads(result.stdout) if result.stdout.strip() else []
    except ValueError as exc:
        raise MaintenanceError("Invalid local process inventory") from exc
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise MaintenanceError("Invalid local process inventory")
    processes = []
    for row in rows:
        if not isinstance(row, dict):
            raise MaintenanceError("Invalid local process record")
        executable, command_line = row.get("ExecutablePath"), row.get("CommandLine")
        if not executable or not command_line:
            continue  # An inaccessible process cannot qualify as our exact worker.
        if not isinstance(row.get("ProcessId"), int) or not isinstance(row.get("ParentProcessId"), int):
            raise MaintenanceError("Invalid local process identifier")
        processes.append(LocalProcess(row["ProcessId"], row["ParentProcessId"], executable,
                                      _windows_arguments(command_line)))
    return processes


def _targets_job(process: LocalProcess, runner_path: Path, folder: Path) -> bool:
    args = process.arguments
    return (len(args) == 5 and args[2:4] == ("run", "--job-dir")
            and Path(args[1]).is_absolute() and Path(args[4]).is_absolute()
            and _path_key(args[1]) == _path_key(runner_path)
            and _path_key(args[4]) == _path_key(folder))


def select_worker_processes(processes: list[LocalProcess], *, saved_pid: int,
                            runner_path: Path, folder: Path, interpreters: set[str]) -> list[LocalProcess]:
    """Require the saved anchor and exact arguments; reject independent duplicates."""
    matching = [process for process in processes if _targets_job(process, runner_path, folder)]
    by_pid = {process.pid: process for process in matching}
    if saved_pid not in by_pid:
        raise MaintenanceError("The saved PID is not the exact case runner and job folder")
    for process in matching:
        if (_path_key(process.executable) not in interpreters
                or not process.arguments or _path_key(process.arguments[0]) not in interpreters):
            raise MaintenanceError("A matching worker uses an unverified Python executable")
    selected = {saved_pid}
    while True:
        expanded = selected | {process.pid for process in matching if process.parent_pid in selected}
        if expanded == selected:
            break
        selected = expanded
    if selected != set(by_pid):
        raise MaintenanceError("An independent worker already targets this job; refusing a duplicate resume")
    # Children first: the venv wrapper may exit naturally after its Python child.
    def depth(process):
        value, parent = 0, process.parent_pid
        while parent in by_pid and parent != process.pid:
            value += 1
            if value > len(by_pid):
                raise MaintenanceError("Invalid local worker process ancestry")
            parent = by_pid[parent].parent_pid
        return value
    return sorted(matching, key=depth, reverse=True)


def _terminate_verified_process(pid: int, identity: str) -> bool:
    """Bind verification and termination to one native handle, preventing PID reuse."""
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x0001 | 0x100000, False, pid)
    if not handle:
        if discriminator._process_identity(pid) is None:
            return False
        raise MaintenanceError("Cannot open the verified local worker for maintenance")
    try:
        exit_code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise MaintenanceError("Cannot inspect the verified local worker")
        if exit_code.value != 259:
            return False
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            raise MaintenanceError("Cannot verify the local worker creation time")
        actual = str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        if actual != identity:
            raise MaintenanceError("Local PID identity changed; no process was terminated")
        if not kernel.TerminateProcess(handle, 1):
            raise MaintenanceError("Cannot stop the verified local worker")
        if kernel.WaitForSingleObject(handle, 10000) != 0:
            raise MaintenanceError("The verified local worker did not stop")
        return True
    finally:
        kernel.CloseHandle(handle)


def _verify_saved_evidence(folder: Path) -> None:
    state = discriminator._read_json(folder / "state.json")
    saved_request = discriminator._read_json(folder / "request.json")
    source_path = folder / "source_readout.py"
    if not state or not saved_request or not source_path.is_file() or not state.get("project_id"):
        raise MaintenanceError("Durable project/request/source evidence is incomplete")
    try:
        request = DiscriminatorRequest.model_validate(saved_request).model_dump()
        request_digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        source_digest = hashlib.sha256(source_path.read_text(encoding="utf-8").encode()).hexdigest()
    except (ValueError, OSError) as exc:
        raise MaintenanceError("Durable request/source evidence is invalid") from exc
    if request_digest != state.get("request_sha256") or source_digest != state.get("source_sha256"):
        raise MaintenanceError("Saved request/source hashes changed; refusing to restart the worker")
    report = discriminator._read_json(folder / "report.json")
    if state.get("phase") == "completed" or (report and report.get("status") in discriminator.TERMINAL_STATUSES):
        raise MaintenanceError("A terminal optimization must retain its completed evidence")


def resume_local_worker(job_id: str, reason: str, *, manager=None) -> dict:
    if os.name != "nt":
        raise MaintenanceError("This maintenance command verifies Windows workers only")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500 or not reason.isprintable():
        raise MaintenanceError("A short printable maintenance reason is required")
    manager = manager or discriminator.discriminator_manager
    with manager._registry_lock():
        folder = manager._job_dir(job_id)
        if folder is None or not folder.is_dir():
            raise MaintenanceError("Unknown optimization job")
        folder = folder.resolve()
        metadata = discriminator._read_json(folder / "job.json")
        if not metadata or metadata.get("id") != job_id or metadata.get("status") not in discriminator.ACTIVE_STATUSES:
            raise MaintenanceError("Only the specified active optimization can be resumed")
        saved_pid, saved_identity = metadata.get("pid"), metadata.get("process_identity")
        if not isinstance(saved_pid, int) or isinstance(saved_pid, bool) or saved_pid <= 0 or not isinstance(saved_identity, str):
            raise MaintenanceError("The saved local worker identity is invalid")
        if discriminator._process_identity(saved_pid) != saved_identity:
            raise MaintenanceError("The saved PID no longer has its recorded creation identity")
        _verify_saved_evidence(folder)
        runner_path = manager.runner_path.resolve()
        case_root = runner_path.parents[2]
        interpreter = case_root / ".venv" / "Scripts" / "python.exe"
        if not runner_path.is_file() or not interpreter.is_file():
            raise MaintenanceError("The case runner or virtual-environment Python is missing")
        interpreters = {_path_key(interpreter), _path_key(sys._base_executable)}
        processes = select_worker_processes(_windows_processes(), saved_pid=saved_pid,
            runner_path=runner_path, folder=folder, interpreters=interpreters)
        identities = {process.pid: discriminator._process_identity(process.pid) for process in processes}
        if any(not identity for identity in identities.values()) or identities[saved_pid] != saved_identity:
            raise MaintenanceError("A local worker identity changed during verification")
        maintenance_path = folder / "maintenance" / (uuid4().hex + ".json")
        maintenance_path.parent.mkdir(exist_ok=True)
        record = {"kind": "local_worker_resume", "status": "prepared", "reason": reason.strip(),
                  "created_at": discriminator._now(), "previous_metadata": metadata,
                  "job_folder": str(folder), "runner_path": str(runner_path),
                  "no_cloud_restart": True,
                  "local_processes": [{"pid": process.pid, "parent_pid": process.parent_pid,
                                       "process_identity": identities[process.pid], "executable": process.executable}
                                      for process in processes]}
        discriminator._atomic_json(maintenance_path, record)
        stopped = []
        try:
            for process in processes:
                if _terminate_verified_process(process.pid, identities[process.pid]):
                    stopped.append(process.pid)
            if any(_targets_job(process, runner_path, folder) for process in _windows_processes()):
                raise MaintenanceError("A matching local worker remains; refusing a parallel resume")
            _verify_saved_evidence(folder)
            log_descriptor = os.open(folder / "worker.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(log_descriptor, "ab") as log:
                process = subprocess.Popen(
                    [str(interpreter), str(runner_path), "run", "--job-dir", str(folder)],
                    cwd=str(case_root), env=os.environ.copy(), stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, shell=False, close_fds=True,
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            identity = discriminator._process_identity(process.pid)
            if not identity:
                raise MaintenanceError("The resumed local worker did not remain alive")
            updated = dict(metadata, pid=process.pid, process_identity=identity, status="running",
                           error=None, updated_at=discriminator._now())
            discriminator._atomic_json(folder / "job.json", updated)
            record.update(status="completed", stopped_local_pids=stopped, new_pid=process.pid,
                          new_process_identity=identity, updated_at=discriminator._now())
            discriminator._atomic_json(maintenance_path, record)
            return {"job_id": job_id, "status": "running", "pid": process.pid,
                    "stopped_local_pids": stopped, "no_cloud_restart": True,
                    "maintenance_record": str(maintenance_path)}
        except Exception:
            record.update(status="failed", stopped_local_pids=stopped, updated_at=discriminator._now())
            discriminator._atomic_json(maintenance_path, record)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        result = resume_local_worker(args.job_id, args.reason)
    except (MaintenanceError, OSError, subprocess.SubprocessError) as exc:
        # Generic maintenance errors never include credentials or raw SDK logs.
        print(f"Local worker resume refused: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
