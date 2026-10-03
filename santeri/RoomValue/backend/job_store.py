"""Atomic local job records, including recovery after an API process restart."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import UUID


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self._records: dict[str, dict] = {}
        self._lock = RLock()

    @staticmethod
    def _valid_id(job_id: str) -> bool:
        try:
            return str(UUID(job_id)) == job_id
        except (ValueError, TypeError, AttributeError):
            return False

    def load(self, *, interrupt_unfinished: bool = True) -> None:
        """Completed results survive restarts; workers are never silently recreated."""
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._records = {}
            for path in self.directory.glob("*.json"):
                if not self._valid_id(path.stem):
                    continue
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(record, dict) or record.get("job_id") != path.stem:
                        continue
                except (OSError, ValueError):
                    continue
                self._records[path.stem] = record
                if interrupt_unfinished and record.get("status") in {"queued", "running"}:
                    self.update(
                        path.stem,
                        status="interrupted",
                        error="The local API restarted. Resume this job to reuse completed cloud simulations.",
                    )

    def _write(self, record: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{record['job_id']}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        temporary.replace(path)

    def create(self, job_id: str, kind: str, request: dict) -> dict:
        if not self._valid_id(job_id):
            raise ValueError("Job ID must be a canonical UUID")
        with self._lock:
            timestamp = now_utc()
            record = {
                "job_id": job_id,
                "kind": kind,
                "status": "queued",
                "request": deepcopy(request),
                "progress": {"stage": "queued"},
                "attempt": 1,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            self._write(record)
            self._records[job_id] = record
            return deepcopy(record)

    def update(self, job_id: str, **changes: object) -> dict:
        with self._lock:
            record = deepcopy(self._records[job_id])
            record.update(deepcopy(changes), updated_at=now_utc())
            self._write(record)
            self._records[job_id] = record
            return deepcopy(record)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            return deepcopy(self._records.get(job_id))

    def latest_completed(self, kind: str) -> dict | None:
        with self._lock:
            records = [
                record for record in self._records.values()
                if record.get("kind") == kind and record.get("status") == "completed"
            ]
            return deepcopy(max(records, key=lambda record: record["updated_at"])) if records else None
