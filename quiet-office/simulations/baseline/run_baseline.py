"""Run the QuietOffice model once on Allsolve: untreated office plus one screen.

This is the "start simple, verify, build up" step. It uses the same project builder as the
backend, runs a two-point sweep at one frequency and prints the speech level at each desk.
Run it before trusting the full optimization.

Usage (from the repository root):

    .venv/Scripts/python.exe quiet-office/simulations/baseline/run_baseline.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.allsolve.optimization_runner import OptimizationRunner  # noqa: E402
from app.models import OptimizationParams  # noqa: E402


def main() -> None:
    params = OptimizationParams(n_screens=1, frequencies_hz=[250.0])
    runner = OptimizationRunner()
    runner.initialize()

    # Private pieces of the runner are used directly here to run exactly one small round.
    from app.allsolve.project_builder import build_office_project

    runner._office_project = build_office_project(runner._client, params)
    print("Project:", runner._client.get_url(runner._office_project.project))

    layouts = [[], [params.office.slots[0].id]]
    results = runner._run_round(params, layouts, "baseline check", lambda m, p: print(f"{p:5.1f}% {m}"), 0, 100)

    for result in results:
        name = "untreated" if not result.slot_ids else f"screen in slot {result.slot_ids}"
        levels = " ".join(f"{level:5.1f}" for level in result.desk_levels_db)
        print(f"{name:>24}: score {result.score:6.1f} | desks dB: {levels}")


if __name__ == "__main__":
    main()
