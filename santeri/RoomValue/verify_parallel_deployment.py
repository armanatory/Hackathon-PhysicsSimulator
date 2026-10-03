"""Record public Worker job progress without any Allsolve credentials."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://roomvalue.santerihukari.com"
HERE = Path(__file__).resolve().parent


def request(path, method="GET"):
    headers = {"User-Agent": "RoomValue deployment verification", "Origin": BASE}
    req = urllib.request.Request(BASE + path, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=35) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.resume:
        started = request(f"/api/jobs/{args.job_id}/resume", "POST")
        print(json.dumps({"resumed": started["job_id"]}), flush=True)
    report = {"url": BASE, "job_id": args.job_id, "observations": []}
    destination = HERE / "experiments" / "room3d_optimizer" / "parallel_website_validation.json"
    deadline = time.monotonic() + 3600
    previous = None
    while time.monotonic() < deadline:
        job = request(f"/api/jobs/{args.job_id}")
        progress = job.get("progress", {})
        summary = {"status": job["status"], **{key: progress[key] for key in (
            "stage", "message", "active_solves", "cloud_running_solves", "allocated_cores",
            "max_concurrent_cores", "account_running_cores", "account_reserved_cores",
            "completed_basis_solves", "total_basis_solves", "remaining_basis_solves",
            "cached_basis_fields", "queued_basis_solves", "prepared_basis_solves",
            "peak_parallel_solves", "evaluated", "total",
        ) if key in progress}}
        if summary != previous:
            print(json.dumps(summary), flush=True)
            report["observations"].append({"observed_at": datetime.now(timezone.utc).isoformat(),
                **summary, "running_simulation_ids": progress.get("running_simulation_ids", [])})
            destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            previous = summary
        if job["status"] in ("completed", "failed", "interrupted"):
            if job["status"] == "completed":
                report["result"] = job["result"]
                destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                best = job["result"]["optimal_layout"]
                print(json.dumps({"verified": True, "baseline_db": job["result"]["baseline"]["noise_db"],
                    "optimal_db": best["noise_db"], "slots": best["slot_ids"]}), flush=True)
            else:
                print(json.dumps({"error": job.get("error")}), flush=True)
            return
        time.sleep(5)
    raise TimeoutError("Public job did not complete within the verification window")


if __name__ == "__main__":
    main()
