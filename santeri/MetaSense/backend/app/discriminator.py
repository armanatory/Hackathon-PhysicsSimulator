"""Durable single-search orchestration; cloud work runs in a detached worker."""

import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import allsolve_config_from_environment, allsolve_sdk_installed
from .discriminator_models import DiscriminatorRequest


CASE_ROOT = Path(__file__).resolve().parents[2]
JOB_ROOT = CASE_ROOT / "casesdata" / "liquid_discriminator" / "jobs"
RUNNER_PATH = CASE_ROOT / "simulations" / "liquid_discriminator" / "runner.py"
ACTIVE_STATUSES = {"queued", "running", "verifying"}
TERMINAL_STATUSES = {"completed", "failed"}
MAX_JSON_BYTES = 16 * 1024 * 1024


class OptimizationUnavailable(RuntimeError):
    pass


class OptimizationAlreadyActive(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict | None:
    try:
        with path.open("rb") as stream:
            content = stream.read(MAX_JSON_BYTES + 1)
        if len(content) > MAX_JSON_BYTES:
            return None
        result = json.loads(content)
        # Reject both non-standard NaN constants and overflowing JSON floats.
        json.dumps(result, allow_nan=False)
        return result if isinstance(result, dict) else None
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None


def _process_identity(pid: int) -> str | None:
    """Return a live process start signature; never signal a Windows process."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            exit_code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259:
                return None
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
                return None
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        remainder = stat.rsplit(")", 1)[1].split()
        return None if remainder[0] == "Z" else remainder[19]
    except (OSError, IndexError):
        return None


def _redact(value):
    """Keep the worker's logs private and remove credential fields/values from reports."""
    secrets = [os.environ.get(key, "") for key in ("ALLSOLVE_ACCESS_KEY", "ALLSOLVE_SECRET_KEY")]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact(item)
            for key, item in value.items()
            if key.lower() not in {"access_key", "secret_key", "allsolve_access_key", "allsolve_secret_key", "authorization", "password"}
        }
    return value


class DiscriminatorManager:
    def __init__(self, job_root: Path = JOB_ROOT, runner_path: Path = RUNNER_PATH) -> None:
        self.job_root = job_root
        self.runner_path = runner_path
        self._thread_lock = threading.RLock()

    @contextmanager
    def _registry_lock(self):
        # The OS lock releases automatically if the API exits or restarts.
        with self._thread_lock:
            self.job_root.mkdir(parents=True, exist_ok=True)
            with (self.job_root / ".registry.lock").open("a+b") as lock_file:
                lock_file.seek(0, os.SEEK_END)
                if lock_file.tell() == 0:
                    lock_file.write(b"\0")
                    lock_file.flush()
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    deadline = time.monotonic() + 5
                    while True:
                        try:
                            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                            break
                        except OSError:
                            if time.monotonic() >= deadline:
                                raise OptimizationUnavailable("Optimization registry is busy")
                            time.sleep(0.05)
                    try:
                        yield
                    finally:
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _job_dir(self, job_id: str) -> Path | None:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            return None
        path = self.job_root / job_id
        try:
            path.resolve().relative_to(self.job_root.resolve())
        except ValueError:
            return None
        return path

    def _refresh(self, folder: Path, metadata: dict) -> dict:
        report = _read_json(folder / "report.json")
        valid_report = bool(report and report.get("label") == "allsolve_liquid_discriminator" and report.get("synthetic") is False)
        if metadata.get("status") == "completed" and not (valid_report and report.get("status") == "completed"):
            metadata.update(status="failed", updated_at=_now(), error="The completed optimization report is missing or invalid")
            _atomic_json(folder / "job.json", metadata)
        if metadata.get("status") not in ACTIVE_STATUSES:
            return metadata
        if valid_report:
            status = report.get("status")
            if isinstance(status, str) and status in ACTIVE_STATUSES | TERMINAL_STATUSES:
                if status != metadata.get("status"):
                    metadata.update(status=status, updated_at=_now())
                    _atomic_json(folder / "job.json", metadata)
                if status in TERMINAL_STATUSES:
                    return metadata
        pid = metadata.get("pid")
        identity = _process_identity(pid) if pid else None
        if not identity or identity != metadata.get("process_identity"):
            metadata.update(status="failed", updated_at=_now(), error="Optimization worker stopped before writing a terminal report")
            _atomic_json(folder / "job.json", metadata)
        return metadata

    def _public_job(self, folder: Path, metadata: dict, reused: bool = False) -> dict:
        report = _read_json(folder / "report.json")
        if report and (report.get("label") != "allsolve_liquid_discriminator" or report.get("synthetic") is not False):
            report = None
        return _redact({
            "id": metadata["id"],
            "status": metadata["status"],
            "label": "allsolve_liquid_discriminator",
            "synthetic": False,
            "created_at": metadata["created_at"],
            "updated_at": (report or {}).get("updated_at", metadata["updated_at"]),
            "request": metadata["request"],
            "report": report,
            "error": metadata.get("error"),
            "reused": reused,
        })

    def _records(self) -> list[tuple[Path, dict]]:
        if not self.job_root.exists():
            return []
        records = []
        for path in self.job_root.iterdir():
            if path.is_dir() and self._job_dir(path.name) is not None:
                metadata = _read_json(path / "job.json")
                if metadata and metadata.get("id") == path.name:
                    records.append((path, self._refresh(path, metadata)))
        return sorted(records, key=lambda item: item[1].get("created_at", ""), reverse=True)

    def configuration(self) -> dict:
        config = allsolve_config_from_environment()
        try:
            config.validate()
            configured = True
        except ValueError:
            configured = False
        return {
            "available": configured and allsolve_sdk_installed() and self.runner_path.is_file(),
            "allsolve_configured": configured,
            "synthetic": False,
            "label": "allsolve_liquid_discriminator",
            "default_request": DiscriminatorRequest().model_dump(mode="json"),
            "limits": {
                "candidate_count": {"min": 1, "max": 128},
                "wavelength_samples": {"min": 3, "max": 41},
                "wavelength_nm": {"min": 800, "max": 1600},
                "liquid_index": {"min": 1, "max": 1.8},
                "max_parallel_cores": {"min": 4, "max": 256},
                "film_thickness_nm": {"min": 50, "max": 250},
                "minimum_feature_nm": {"min": 20, "max": 100},
                "period_nm": {"min": 100, "max": 1000},
                "fill_factor": {"min": 0.05, "max": 0.95},
                "ridge_height_nm": {"min": 20, "max": 800},
            },
            "model": {
                "geometry": "Rectangular Si3N4 ridges on a Si3N4 film and fused-silica substrate",
                "polarization": "TE, E_y; normal incidence from liquid toward glass",
                "period_y_nm": 100,
                "clearance_nm": 1000,
                "materials": ["Si3N4: Luke 2015 dispersion", "Fused silica: Malitson 1965 dispersion"],
                "loss_model": "Lossless dielectric material assumptions",
                "liquids": "Explicit constant real refractive indices; labels do not assign concentration or binding",
                "objective": "max_lambda |R_A(lambda) - R_B(lambda)| at the same wavelength",
                "strategy": "Latin hypercube best-of-N search; not a global-optimum guarantee",
                "validation": "Finalist dense spectra and finer mesh checks; liquid discrimination is bulk refractometry",
                "cutoff_margin": 0.9,
                "team_quota": "Requested core cap is also subject to available team cloud quota",
            },
        }

    def create(self, request: DiscriminatorRequest) -> dict:
        config = allsolve_config_from_environment()
        try:
            config.validate()
        except ValueError as error:
            raise OptimizationUnavailable(str(error)) from error
        if not allsolve_sdk_installed() or not self.runner_path.is_file():
            raise OptimizationUnavailable("The real Allsolve optimization runner is unavailable")
        payload = request.model_dump(mode="json")
        request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self._registry_lock():
            for folder, metadata in self._records():
                if metadata.get("status") in ACTIVE_STATUSES:
                    if metadata.get("request_hash") == request_hash:
                        return self._public_job(folder, metadata, reused=True)
                    raise OptimizationAlreadyActive(f"Optimization job {metadata['id']} is already active")
            job_id = uuid4().hex
            folder = self.job_root / job_id
            folder.mkdir()
            created = _now()
            metadata = {"id": job_id, "status": "queued", "created_at": created, "updated_at": created,
                        "request_hash": request_hash, "request": payload, "pid": None, "process_identity": None}
            _atomic_json(folder / "request.json", payload)
            _atomic_json(folder / "job.json", metadata)
            try:
                log_descriptor = os.open(folder / "worker.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(log_descriptor, "ab") as log:
                    process = subprocess.Popen(
                        [sys.executable, str(self.runner_path), "run", "--job-dir", str(folder.resolve())],
                        cwd=str(CASE_ROOT), env=os.environ.copy(), stdin=subprocess.DEVNULL,
                        stdout=log, stderr=subprocess.STDOUT, shell=False, close_fds=True,
                        creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0,
                        start_new_session=os.name != "nt",
                    )
                metadata.update(pid=process.pid, process_identity=_process_identity(process.pid))
                _atomic_json(folder / "job.json", metadata)
            except (OSError, ValueError):
                metadata.update(status="failed", updated_at=_now(), error="Optimization worker could not start")
                _atomic_json(folder / "job.json", metadata)
                return self._public_job(folder, metadata)
            threading.Thread(target=self._watch, args=(folder, process), daemon=True).start()
            return self._public_job(folder, self._refresh(folder, metadata))

    def _watch(self, folder: Path, process) -> None:
        process.wait()
        with self._registry_lock():
            metadata = _read_json(folder / "job.json")
            if metadata:
                self._refresh(folder, metadata)

    def get(self, job_id: str) -> dict | None:
        folder = self._job_dir(job_id)
        if folder is None or not (folder / "job.json").exists():
            return None
        with self._registry_lock():
            metadata = _read_json(folder / "job.json")
            if not metadata or metadata.get("id") != job_id:
                return None
            return self._public_job(folder, self._refresh(folder, metadata))

    def latest(self) -> dict | None:
        if not self.job_root.exists():
            return None
        with self._registry_lock():
            records = self._records()
            return self._public_job(*records[0]) if records else None


discriminator_manager = DiscriminatorManager()
