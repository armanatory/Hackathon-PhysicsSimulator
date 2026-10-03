"""A step-by-step record of what one optimization sent to Allsolve and what came back."""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("quietoffice.run")

# Where a line of the record comes from.
SENT = "sent"  # something this backend asked Allsolve to do
RECEIVED = "received"  # something Allsolve answered
SOLVER = "solver"  # a line from the cloud job's own log
INFO = "info"  # done locally: planning, scoring
ERROR = "error"


class RunLog:
    """Thread-safe, append-only log of one run. Entries are plain dicts, ready for JSON."""

    def __init__(self) -> None:
        self._entries: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._started = time.monotonic()

    def add(self, kind: str, step: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        entry = {
            "index": 0,
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "elapsed_s": round(time.monotonic() - self._started, 1),
            "kind": kind,
            "step": step,
            "message": message,
            "data": data,
        }
        with self._lock:
            entry["index"] = len(self._entries)
            self._entries.append(entry)
        logger.log(logging.ERROR if kind == ERROR else logging.INFO, f"[{kind:8}] {step}: {message}")

    def since(self, index: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            return self._entries[max(index, 0):]

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
