"""Read the optical slab benchmark artifact without starting simulations."""

import json
import math
from pathlib import Path


REPORT_PATH = (
    Path(__file__).resolve().parents[2]
    / "simulations"
    / "slab_validation"
    / "results"
    / "report.json"
)
MAX_REPORT_BYTES = 2 * 1024 * 1024
REPORT_LABEL = "allsolve_slab_validation"
REPORT_STATUSES = {"queued", "running", "completed", "failed"}


def _status(status: str, error: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "status": status,
        "validated": False,
        "purpose": "optical_slab_benchmark",
        "synthetic": False,
    }
    if error is not None:
        result["error"] = error
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def read_slab_validation_report() -> dict[str, object]:
    """Expose completed validation only when its artifact has cloud-run provenance."""
    try:
        with REPORT_PATH.open("rb") as report_file:
            content = report_file.read(MAX_REPORT_BYTES + 1)
    except FileNotFoundError:
        return _status("not_run")
    except OSError:
        return _status("unverified", "Slab validation report could not be read")

    if len(content) > MAX_REPORT_BYTES:
        return _status("unverified", "Slab validation report exceeds the size limit")
    try:
        report = json.loads(
            content.decode("utf-8"),
            parse_constant=_reject_nonfinite,
            parse_float=_finite_float,
        )
    except (UnicodeError, ValueError, RecursionError):
        return _status("unverified", "Slab validation report is not valid JSON")

    if (
        not isinstance(report, dict)
        or report.get("label") != REPORT_LABEL
        or not isinstance(report.get("status"), str)
        or report.get("status") not in REPORT_STATUSES
        or not isinstance(report.get("validated"), bool)
        or not isinstance(report.get("runs"), list)
        or any(not isinstance(run, dict) for run in report["runs"])
    ):
        return _status("unverified", "Slab validation report has an invalid format")

    return {
        **report,
        "purpose": "optical_slab_benchmark",
        "synthetic": False,
        "validated": (
            report["validated"] is True
            and report["status"] == "completed"
            and bool(report["runs"])
        ),
    }
