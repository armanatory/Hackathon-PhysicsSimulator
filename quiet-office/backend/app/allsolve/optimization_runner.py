"""Search for the best screen layout by running Allsolve sweeps."""

import itertools
import logging
import threading
from typing import Callable, List, Optional, Sequence

from ..config import PROJECT_ROOT, get_settings
from ..models.office import LayoutResult, OptimizationParams
from ..scoring import combine_bands, level_db, raw_score
from .project_builder import (
    REFERENCE_OUTPUT,
    OfficeProject,
    add_probe_outputs,
    build_office_project,
    desk_output_name,
    screen_variables,
)

logger = logging.getLogger(__name__)

try:
    import allsolve

    ALLSOLVE_AVAILABLE = True
except ImportError as e:
    ALLSOLVE_AVAILABLE = False
    allsolve = None
    logger.warning(f"Allsolve SDK not available: {e}")

Layout = List[int]  # slot ids, one per screen
ProgressCallback = Callable[[str, float], None]
LayoutCallback = Callable[[LayoutResult, int, int], None]


class OptimizationAborted(Exception):
    """Raised inside the worker thread when the user aborts."""


def planned_layout_count(params: OptimizationParams) -> int:
    """How many layouts the chosen strategy will simulate, including the untreated office."""
    n_slots, n = len(params.office.slots), params.n_screens
    if params.strategy == "exhaustive":
        return 1 + len(list(itertools.combinations(range(n_slots), n)))
    return 1 + sum(n_slots - k for k in range(n))


class OptimizationRunner:
    """Owns one Allsolve project and runs the layout search on it.

    All methods except abort() are meant to run in one worker thread.
    """

    def __init__(self) -> None:
        self._client = None
        self._office_project: Optional[OfficeProject] = None
        self._running_job = None  # the mesh or simulation currently on the cloud
        self._abort = threading.Event()
        self.project_url: Optional[str] = None
        self._reference_pressures: List[float] = []
        self._baseline_raw: Optional[float] = None

    # ------------------------------------------------------------------ setup

    def initialize(self) -> None:
        """Create the Allsolve client from the configured credentials."""
        if not ALLSOLVE_AVAILABLE:
            raise RuntimeError("Allsolve SDK is not installed. Run: pip install -r backend/requirements.txt")
        settings = get_settings()
        if not settings.has_credentials:
            raise RuntimeError(
                "Allsolve API credentials not set. Copy .env.example to .env and fill in QS_ACCESS_KEY and QS_SECRET_KEY."
            )
        self._client = allsolve.Client(
            api_key=settings.qs_access_key,
            api_secret=settings.qs_secret_key,
            host=settings.qs_host,
            cache_base_dir=str(PROJECT_ROOT / "backend"),
            dotenv_file=None,
        )
        logger.info(f"Allsolve client ready ({settings.qs_host})")

    # -------------------------------------------------------------------- run

    def run_sync(
        self,
        params: OptimizationParams,
        on_progress: Optional[ProgressCallback] = None,
        on_layout: Optional[LayoutCallback] = None,
    ) -> dict:
        """Run the whole search. Blocking: call it from a worker thread."""

        def progress(message: str, percent: float) -> None:
            logger.info(f"{percent:5.1f}% {message}")
            if on_progress:
                on_progress(message, percent)

        total = planned_layout_count(params)
        results: List[LayoutResult] = []

        def record(batch: Sequence[LayoutResult]) -> None:
            for result in batch:
                results.append(result)
                if on_layout:
                    on_layout(result, len(results), total)

        self.initialize()
        try:
            progress("Creating the office project in Allsolve...", 3)
            self._office_project = build_office_project(self._client, params)
            self.project_url = self._client.get_url(self._office_project.project)
            logger.info(f"Project: {self.project_url}")

            slot_ids = [slot.id for slot in params.office.slots]
            if params.strategy == "exhaustive":
                rounds = [[[]] + [list(c) for c in itertools.combinations(slot_ids, params.n_screens)]]
            else:
                rounds = None  # greedy rounds depend on the previous round's winner

            if rounds is not None:
                record(self._run_round(params, rounds[0], "all layouts", progress, 10, 95))
            else:
                chosen: Layout = []
                span = 85.0 / params.n_screens
                for k in range(params.n_screens):
                    layouts = [chosen + [s] for s in slot_ids if s not in chosen]
                    if k == 0:
                        layouts = [[]] + layouts  # the untreated office rides along in round 1
                    start = 10 + k * span
                    batch = self._run_round(params, layouts, f"screen {k + 1} of {params.n_screens}", progress, start, start + span)
                    record(batch)
                    placed = [r for r in batch if len(r.slot_ids) == k + 1]
                    chosen = min(placed, key=lambda r: r.score).slot_ids

            baseline = next(r for r in results if not r.slot_ids)
            candidates = [r for r in results if len(r.slot_ids) == params.n_screens]
            best = min(candidates, key=lambda r: r.score)
            progress("Complete", 100)
            return {
                "baseline": baseline.model_dump(),
                "best": best.model_dump(),
                "layouts": [r.model_dump() for r in results],
                "project_url": self.project_url,
                "parameters": params.model_dump(),
            }
        finally:
            self._running_job = None

    def _run_round(
        self,
        params: OptimizationParams,
        layouts: List[Layout],
        label: str,
        progress: ProgressCallback,
        percent_from: float,
        percent_to: float,
    ) -> List[LayoutResult]:
        """Mesh and solve one batch of layouts as a single sweep, then score them."""
        self._check_abort()
        office_project = self._office_project
        project = office_project.project
        frequencies = params.frequencies_hz
        slots = {slot.id: slot for slot in params.office.slots}
        span = percent_to - percent_from

        # One sweep point per (layout, frequency), in lockstep lists.
        columns: dict = {"freq": []}
        for i in range(params.n_screens):
            for name in screen_variables(i):
                columns[name] = []
        for layout in layouts:
            for frequency in frequencies:
                columns["freq"].append(frequency)
                for i in range(params.n_screens):
                    on, x, y, w, h = screen_variables(i)
                    present = i < len(layout)
                    slot = slots[layout[i]] if present else params.office.slots[0]
                    vertical = slot.orientation == "v"
                    columns[on].append(1 if present else 0)
                    columns[x].append(slot.x)
                    columns[y].append(slot.y)
                    columns[w].append(params.screen_thickness_m if vertical else params.screen_length_m)
                    columns[h].append(params.screen_length_m if vertical else params.screen_thickness_m)

        tag = label.replace(" ", "_")
        sweep = project.create_variable_overrides(name=f"sweep_{tag}", overrides=list(columns.items()))

        progress(f"Meshing {len(layouts)} layouts ({label})...", percent_from + 0.05 * span)
        mesh = project.create_mesh(
            allsolve.MeshSettings(
                name=f"Mesh {label}",
                mesh_size_max=office_project.mesh_size_m,
                mesh_size_min=office_project.mesh_size_m / 4,
                max_run_time_minutes=20,
                variable_overrides=[sweep],
            )
        )
        mesh_instance = mesh.get_override(sweep)
        self._running_job = mesh_instance
        mesh_instance.start()
        while mesh_instance.is_running(refresh_delay_s=3):
            self._check_abort()
        if mesh_instance.get_status() != allsolve.Job.SUCCESS:
            raise RuntimeError(f"Meshing failed ({label}): {mesh_instance.get_status()}")

        progress(f"Solving {len(layouts)} layouts x {len(frequencies)} bands ({label})...", percent_from + 0.4 * span)
        simulation = project.create_simulation_harmonic(
            name=f"Harmonic {label}",
            description=f"Speech bands {frequencies} Hz for {len(layouts)} screen layouts",
            max_run_time_minutes=30,
            solver_mode=allsolve.SolverMode.DIRECT,
            fundamental_frequency="freq",
            mesh=mesh,
            variable_overrides=sweep,
            physics_set=office_project.physics_set,
        )
        add_probe_outputs(simulation, params)
        self._running_job = simulation
        simulation.start()
        while simulation.is_running(refresh_delay_s=3):
            self._check_abort()
        if simulation.get_status() != allsolve.Job.SUCCESS:
            raise RuntimeError(f"Simulation failed ({label}): {simulation.get_status()}")

        progress(f"Reading desk pressures ({label})...", percent_from + 0.95 * span)
        return self._score(simulation, params, layouts)

    def _score(self, simulation, params: OptimizationParams, layouts: List[Layout]) -> List[LayoutResult]:
        """Read every probe from the sweep and convert to calibrated levels and scores."""
        data = simulation.get_output_data(refresh=True)
        step = data.get_step_index(data.NO_STEP)
        n_freq, n_desks = len(params.frequencies_hz), len(params.office.desks)

        def pressure(layout_index: int, freq_index: int, name: str) -> float:
            value = data.get_value_at(layout_index * n_freq + freq_index, step, name)
            if value is None:
                raise RuntimeError(f"Output '{name}' is missing for sweep step {layout_index * n_freq + freq_index}")
            return abs(float(value))

        # The untreated office is always the first layout of the first round.
        if not self._reference_pressures:
            if layouts[0]:
                raise RuntimeError("The first round must start with the untreated office")
            self._reference_pressures = [pressure(0, f, REFERENCE_OUTPUT) for f in range(n_freq)]

        scored = []
        for li, layout in enumerate(layouts):
            desk_levels = [
                combine_bands(
                    [
                        level_db(pressure(li, f, desk_output_name(d)), self._reference_pressures[f])
                        for f in range(n_freq)
                    ]
                )
                for d in range(n_desks)
            ]
            raw = raw_score(desk_levels)
            if not layout:
                self._baseline_raw = raw
            scored.append((layout, desk_levels, raw))

        return [
            LayoutResult(slot_ids=layout, desk_levels_db=levels, score=100.0 * raw / self._baseline_raw)
            for layout, levels, raw in scored
        ]

    # ------------------------------------------------------------ abort/cleanup

    def _check_abort(self) -> None:
        if self._abort.is_set():
            raise OptimizationAborted("Optimization aborted by user")

    def abort(self) -> bool:
        """Stop the search and the cloud job that is currently running. Thread-safe."""
        self._abort.set()
        job = self._running_job
        if job is None:
            return False
        try:
            job.abort()
            return True
        except Exception as e:
            logger.warning(f"Failed to abort running job: {e}")
            return False

    def cleanup(self) -> None:
        """Delete the project unless settings ask to keep it for inspection."""
        if self._office_project is None or get_settings().keep_projects:
            return
        try:
            self._office_project.project.delete()
        except Exception as e:
            logger.warning(f"Failed to delete project: {e}")
        self._office_project = None
