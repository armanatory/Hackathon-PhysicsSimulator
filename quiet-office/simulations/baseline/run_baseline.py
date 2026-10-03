"""Run the QuietOffice model once on Allsolve: the untreated office plus one screen.

This is the "start simple, verify, build up" step. It goes through exactly the same code as
the backend (project, sweep, mesh, simulation, scoring) with the smallest possible job, and
prints the run log: every request sent to Allsolve and every answer. Run it before trusting
the full optimization.

Usage (from the repository root):

    .venv/Scripts/python.exe quiet-office/simulations/baseline/run_baseline.py [2d|3d]
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.allsolve.optimization_runner import OptimizationRunner  # noqa: E402
from app.models import OptimizationParams, default_office  # noqa: E402


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "2d"
    office = default_office()
    office.slots = office.slots[:1]  # one candidate position: two layouts in total
    params = OptimizationParams(office=office, n_screens=1, frequencies_hz=[250.0], model=model, parallel_jobs=1)

    runner = OptimizationRunner()
    printed = 0

    def show_new_entries(*_args) -> None:
        nonlocal printed
        for entry in runner.log.since(printed):
            data = f"  {json.dumps(entry['data'])[:400]}" if entry["data"] else ""
            print(f"{entry['elapsed_s']:7.1f}s  {entry['kind']:8}  {entry['step']:<12}  {entry['message']}{data}", flush=True)
            printed += 1

    try:
        result = runner.run_sync(params, on_progress=show_new_entries)
    finally:
        show_new_entries()

    print()
    for layout in result["layouts"]:
        name = "untreated" if not layout["slot_ids"] else f"screen in position {layout['slot_ids']}"
        levels = " ".join(f"{level:5.1f}" for level in layout["desk_levels_db"])
        print(f"{name:>24}: score {layout['score']:6.1f} | desks dB: {levels}")
    evidence = result["evidence"]
    print(f"\nProject: {evidence['project_url']}")
    print(f"Jobs: {[(job['kind'], job['id'], job['status']) for job in evidence['jobs']]}")


if __name__ == "__main__":
    main()
