"""Search for the best screen layout by running Allsolve sweeps, several at a time."""

import io
import itertools
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Sequence

from ..config import PROJECT_ROOT, get_settings
from ..models.office import LayoutResult, OptimizationParams
from ..scoring import SPEECH_LEVEL_AT_1M_DB, combine_bands, combine_sources, level_db, raw_score
from .project_builder import (
    OfficeProject,
    add_probe_outputs,
    build_office_project,
    receiver_output_name,
    reference_output_name,
    screen_variables,
    source_variables,
)
from .project_builder_3d import build_office_project_3d
from .run_log import ERROR, INFO, RECEIVED, SENT, SOLVER, RunLog

logger = logging.getLogger(__name__)

try:
    import allsolve

    ALLSOLVE_AVAILABLE = True
except ImportError as e:
    ALLSOLVE_AVAILABLE = False
    allsolve = None
    logger.warning(f"Allsolve SDK not available: {e}")

Layout = List[int]  # slot ids, one per screen
# For one layout: output name -> pressure[source][frequency]
Pressures = Dict[str, List[List[float]]]
ProgressCallback = Callable[[str, float], None]
LayoutCallback = Callable[[LayoutResult, int, int], None]


class OptimizationAborted(Exception):
    """Raised inside a worker thread when the user aborts."""


def planned_layout_count(params: OptimizationParams) -> int:
    """How many layouts the chosen strategy will simulate, including the untreated office."""
    n_slots, n = len(params.office.slots), params.n_screens
    if params.strategy == "exhaustive":
        return 1 + len(list(itertools.combinations(range(n_slots), n)))
    return 1 + sum(n_slots - k for k in range(n))


def split_evenly(items: Sequence, parts: int) -> List[List]:
    """Split into up to `parts` consecutive chunks of nearly equal size. No empty chunks."""
    parts = max(1, min(parts, len(items)))
    size, extra = divmod(len(items), parts)
    chunks, start = [], 0
    for i in range(parts):
        end = start + size + (1 if i < extra else 0)
        chunks.append(list(items[start:end]))
        start = end
    return chunks


class OptimizationRunner:
    """Owns one Allsolve project and runs the layout search on it.

    run_sync() is meant to run in one worker thread. Each round of layouts is split into
    several sweeps that are meshed and solved at the same time, each in its own thread.
    abort() may be called from any thread.
    """

    def __init__(self) -> None:
        self._client = None
        self._office_project: Optional[OfficeProject] = None
        self._running_jobs: set = set()  # meshes and simulations currently on the cloud
        self._jobs_lock = threading.Lock()
        self._abort = threading.Event()
        self.project_url: Optional[str] = None
        self.project_id: Optional[str] = None
        self.log = RunLog()
        self.jobs: List[dict] = []  # every mesh and simulation job started on Allsolve
        self._references: List[List[float]] = []  # pressure 1 m from each source, per band
        self._baseline_raw: Optional[float] = None
        self._pressures: Dict[tuple, Pressures] = {}  # raw solver output per layout

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
        self.log.add(SENT, "connect", f"Signed in to Allsolve at {settings.qs_host} with SDK {getattr(allsolve, '__version__', '?')}")

    # -------------------------------------------------------------------- run

    def run_sync(
        self,
        params: OptimizationParams,
        on_progress: Optional[ProgressCallback] = None,
        on_layout: Optional[LayoutCallback] = None,
    ) -> dict:
        """Run the whole search. Blocking: call it from a worker thread."""

        def progress(message: str, percent: float) -> None:
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
            progress(f"Creating the {params.model.upper()} office project in Allsolve...", 3)
            build = build_office_project_3d if params.model == "3d" else build_office_project
            self._office_project = build(self._client, params, self.log)
            self.project_id = self._office_project.project.id
            self.project_url = self._client.get_url(self._office_project.project)
            self.log.add(RECEIVED, "project", f"Project is open at {self.project_url}", {"url": self.project_url})

            slot_ids = [slot.id for slot in params.office.slots]
            if params.strategy == "exhaustive":
                layouts = [[]] + [list(c) for c in itertools.combinations(slot_ids, params.n_screens)]
                record(self._run_round(params, layouts, "all layouts", progress, 10, 95))
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
            self.log.add(
                INFO,
                "result",
                f"Best of {len(results)} simulated layouts: screens in positions {best.slot_ids}, score {best.score:.1f} (untreated = 100)",
            )
            progress("Complete", 100)
            return {
                "baseline": baseline.model_dump(),
                "best": best.model_dump(),
                "layouts": [r.model_dump() for r in results],
                "project_url": self.project_url,
                "parameters": params.model_dump(),
                "evidence": self.evidence(params, baseline, best),
            }
        except OptimizationAborted:
            self.log.add(ERROR, "abort", "Run stopped by the user")
            raise
        except Exception as e:
            self.log.add(ERROR, "failed", f"{type(e).__name__}: {e}")
            raise
        finally:
            with self._jobs_lock:
                self._running_jobs.clear()

    def _run_round(
        self,
        params: OptimizationParams,
        layouts: List[Layout],
        label: str,
        progress: ProgressCallback,
        percent_from: float,
        percent_to: float,
    ) -> List[LayoutResult]:
        """Simulate one batch of layouts, split over several Allsolve jobs running in parallel."""
        self._check_abort()
        chunks = split_evenly(layouts, params.parallel_jobs)
        span = percent_to - percent_from
        n_solves = len(layouts) * len(params.office.sources) * len(params.frequencies_hz)
        progress(
            f"Meshing and solving {len(layouts)} layouts ({label}): {n_solves} solves in {len(chunks)} parallel jobs...",
            percent_from + 0.05 * span,
        )

        def work(index: int) -> List[Pressures]:
            # Each thread needs its own SDK session.
            with self._client.in_thread():
                return self._solve_chunk(params, chunks[index], f"{label} part {index + 1}")

        pressures: List[Optional[List[Pressures]]] = [None] * len(chunks)
        if len(chunks) == 1:
            pressures[0] = self._solve_chunk(params, chunks[0], label)
        else:
            with ThreadPoolExecutor(max_workers=len(chunks), thread_name_prefix="allsolve") as pool:
                futures = {pool.submit(work, i): i for i in range(len(chunks))}
                done = 0
                try:
                    for future in as_completed(futures):
                        pressures[futures[future]] = future.result()
                        done += 1
                        progress(f"{done} of {len(chunks)} parallel jobs finished ({label})", percent_from + (0.05 + 0.85 * done / len(chunks)) * span)
                except BaseException:
                    # One job failed or the user aborted: stop the others before leaving.
                    self._abort.set()
                    self._abort_running_jobs()
                    raise

        progress(f"Scoring {len(layouts)} layouts ({label})...", percent_from + 0.95 * span)
        flat = [p for chunk in pressures for p in chunk]
        for layout, p in zip(layouts, flat):
            self._pressures[tuple(layout)] = p
        scored = self._score(params, layouts, flat)
        self.log.add(
            INFO,
            "score",
            f"Scored {len(layouts)} layouts from the solver's pressures ({label})",
            {"scores": [{"positions": r.slot_ids, "score": round(r.score, 1)} for r in scored]},
        )
        return scored

    def _solve_chunk(self, params: OptimizationParams, layouts: List[Layout], label: str) -> List[Pressures]:
        """Mesh and solve some layouts as one sweep, and read the pressure at every probe."""
        self._check_abort()
        office_project = self._office_project
        project = office_project.project
        office = params.office
        frequencies = params.frequencies_hz
        n_sources = len(office.sources)
        slots = {slot.id: slot for slot in office.slots}

        # One sweep point per (layout, source, frequency), in lockstep lists. Only one source
        # sounds at a time, so sources stay independent and can be added as energy afterwards.
        columns: dict = {"freq": []}
        for s in range(n_sources):
            columns[source_variables(s)[2]] = []
        for i in range(params.n_screens):
            for name in screen_variables(i):
                columns[name] = []
        for layout in layouts:
            for active in range(n_sources):
                for frequency in frequencies:
                    columns["freq"].append(frequency)
                    for s in range(n_sources):
                        columns[source_variables(s)[2]].append(1 if s == active else 0)
                    for i in range(params.n_screens):
                        on, x, y, w, h = screen_variables(i)
                        present = i < len(layout)
                        slot = slots[layout[i]] if present else office.slots[0]
                        vertical = slot.orientation == "v"
                        columns[on].append(1 if present else 0)
                        columns[x].append(slot.x)
                        columns[y].append(slot.y)
                        columns[w].append(params.screen_thickness_m if vertical else params.screen_length_m)
                        columns[h].append(params.screen_length_m if vertical else params.screen_thickness_m)

        tag = label.replace(" ", "_")
        sweep = project.create_variable_overrides(name=f"sweep_{tag}", overrides=list(columns.items()))
        n_points = len(columns["freq"])
        self.log.add(
            SENT,
            "sweep",
            f"Sent sweep '{label}': {len(layouts)} layouts x {n_sources} sources x {len(frequencies)} bands = {n_points} solves",
            {"layouts": layouts, "frequencies_hz": frequencies, "variables": sorted(columns), "first_point": {k: v[0] for k, v in columns.items()}},
        )

        mesh = project.create_mesh(
            allsolve.MeshSettings(
                name=f"Mesh {label}",
                mesh_size_max=office_project.mesh_size_m,
                mesh_size_min=office_project.mesh_size_m / 4,
                max_run_time_minutes=max(20, office_project.max_run_time_minutes // 2),
                variable_overrides=[sweep],
                **({"node_type": office_project.node_type.value} if office_project.node_type else {}),
            )
        )
        mesh_instance = mesh.get_override(sweep)
        self.log.add(SENT, "mesh", f"Asked Allsolve to mesh {len(layouts)} geometries ({label})", {"mesh_id": mesh.id, "max_element_size_m": round(office_project.mesh_size_m, 4)})
        self._wait(mesh_instance, f"Meshing ({label})", "mesh", mesh.id)

        simulation = project.create_simulation_harmonic(
            name=f"Harmonic {label}",
            description=f"{len(layouts)} layouts x {n_sources} sources x bands {frequencies} Hz",
            max_run_time_minutes=office_project.max_run_time_minutes,
            solver_mode=office_project.solver_mode or allsolve.SolverMode.DIRECT,
            fundamental_frequency="freq",
            mesh=mesh,
            variable_overrides=sweep,
            physics_set=office_project.physics_set,
        )
        add_probe_outputs(simulation, params, office_project.probe_height_m, office_project.reference_height_m)
        if office_project.node_type:
            simulation.set_runtime(
                allsolve.Runtime(node_type=office_project.node_type, node_count=office_project.node_count)
            )
            simulation.save()
        self.log.add(
            SENT,
            "simulation",
            f"Started harmonic acoustic simulation ({label}): {n_points} solves, {len(office.receivers()) + n_sources} pressure probes each",
            {"simulation_id": simulation.id, "solver": str(office_project.solver_mode or "direct"), "probes": len(office.receivers()) + n_sources},
        )
        self._wait(simulation, f"Simulation ({label})", "simulation", simulation.id)

        # Sweep order is (layout, source, frequency), exactly as the columns were built.
        data = simulation.get_output_data(refresh=True)
        step = data.get_step_index(data.NO_STEP)
        n_freq = len(frequencies)
        names = [receiver_output_name(i) for i in range(len(office.receivers()))]
        names += [reference_output_name(s) for s in range(n_sources)]

        def read(layout_index: int, source: int, freq: int, name: str) -> float:
            sweep_index = (layout_index * n_sources + source) * n_freq + freq
            value = data.get_value_at(sweep_index, step, name)
            if value is None:
                raise RuntimeError(f"Output '{name}' is missing for sweep step {sweep_index} ({label})")
            return abs(float(value))

        result = [
            {name: [[read(li, s, f, name) for f in range(n_freq)] for s in range(n_sources)] for name in names}
            for li in range(len(layouts))
        ]
        first = result[0]
        self.log.add(
            RECEIVED,
            "pressures",
            f"Read {len(layouts) * n_sources * n_freq * len(names)} pressure values from Allsolve ({label})",
            {
                "simulation_id": simulation.id,
                "sample_layout": layouts[0],
                "sample_pressures_pa": {name: [[float(f"{v:.4g}") for v in row] for row in first[name]] for name in names[:4]},
            },
        )
        return result

    def _wait(self, job, what: str, kind: str, job_id: str) -> None:
        """Start a cloud job and block until it is done, honouring abort."""
        record = {"kind": kind, "id": job_id, "what": what, "status": "running"}
        with self._jobs_lock:
            self._running_jobs.add(job)
            self.jobs.append(record)
        try:
            job.start()
            while job.is_running(refresh_delay_s=3):
                self._solver_lines(job, what)
                self._check_abort()
            self._solver_lines(job, what)
            self._check_abort()
            status = job.get_status()
            record["status"] = str(status)
            if status != allsolve.Job.SUCCESS:
                reason = ""
                try:
                    reason = job.get_status_reason() or ""
                except Exception:
                    pass
                raise RuntimeError(f"{what} failed: {status} {reason}".strip())
            self.log.add(RECEIVED, kind, f"{what} finished: {status}", {f"{kind}_id": job_id})
        except Exception:
            if record["status"] == "running":
                record["status"] = "stopped"
            raise
        finally:
            with self._jobs_lock:
                self._running_jobs.discard(job)

    def _solver_lines(self, job, what: str) -> None:
        """Copy new lines of the cloud job's own log into the run log."""
        try:
            buffer = io.StringIO()
            job.print_new_loglines(buffer)
        except Exception:
            return
        for line in buffer.getvalue().splitlines():
            if line.strip():
                self.log.add(SOLVER, what, line.rstrip()[:300])

    def evidence(self, params: OptimizationParams, baseline: LayoutResult, best: LayoutResult) -> dict:
        """What ties the result to Allsolve: the project, every job, and raw solver pressures."""
        office = params.office
        receivers = office.receivers()
        names = [receiver_output_name(i) for i in range(len(receivers))]

        def raw(layout: Layout) -> List[List[List[float]]]:
            pressures = self._pressures.get(tuple(layout), {})
            return [pressures.get(name, []) for name in names]

        return {
            "host": get_settings().qs_host,
            "project_id": self.project_id,
            "project_url": self.project_url,
            "model": params.model,
            "jobs": list(self.jobs),
            "solves": sum(1 for _ in self._pressures) * len(office.sources) * len(params.frequencies_hz),
            "frequencies_hz": params.frequencies_hz,
            "receivers": [{"x": p.x, "y": p.y} for p in receivers],
            "reference_pressures_pa": self._references,
            "baseline_pressures_pa": raw(baseline.slot_ids),
            "best_pressures_pa": raw(best.slot_ids),
        }

    def _score(self, params: OptimizationParams, layouts: List[Layout], pressures: List[Pressures]) -> List[LayoutResult]:
        """Convert probe pressures into calibrated levels, zone averages and scores."""
        office = params.office
        n_freq, n_sources = len(params.frequencies_hz), len(office.sources)
        n_receivers, n_desks = len(office.receivers()), len(office.desks)

        # The untreated office is always the first layout of the first round. Its pressure
        # 1 m from each source defines that source's stated level.
        if not self._references:
            if layouts[0]:
                raise RuntimeError("The first round must start with the untreated office")
            self._references = [
                [pressures[0][reference_output_name(s)][s][f] for f in range(n_freq)] for s in range(n_sources)
            ]

        scored = []
        for layout, p in zip(layouts, pressures):
            levels = []
            for r in range(n_receivers):
                at_receiver = p[receiver_output_name(r)]
                per_band = [
                    combine_sources(
                        [
                            level_db(at_receiver[s][f], self._references[s][f])
                            + office.sources[s].level_db
                            - SPEECH_LEVEL_AT_1M_DB
                            for s in range(n_sources)
                        ]
                    )
                    for f in range(n_freq)
                ]
                levels.append(combine_bands(per_band))
            raw = raw_score(levels)
            if not layout:
                self._baseline_raw = raw
            zone_levels = [combine_bands(levels[start:end]) for start, end in office.zone_ranges()]
            scored.append((layout, levels[:n_desks], zone_levels, raw))

        return [
            LayoutResult(slot_ids=layout, desk_levels_db=desks, zone_levels_db=zones, score=100.0 * raw / self._baseline_raw)
            for layout, desks, zones, raw in scored
        ]

    # ------------------------------------------------------------ abort/cleanup

    def _check_abort(self) -> None:
        if self._abort.is_set():
            raise OptimizationAborted("Optimization aborted by user")

    def _abort_running_jobs(self) -> bool:
        with self._jobs_lock:
            jobs = list(self._running_jobs)
        aborted = False
        for job in jobs:
            try:
                job.abort()
                aborted = True
            except Exception as e:
                logger.warning(f"Failed to abort a running job: {e}")
        return aborted

    def abort(self) -> bool:
        """Stop the search and every cloud job that is currently running. Thread-safe."""
        self._abort.set()
        return self._abort_running_jobs()

    def cleanup(self) -> None:
        """Delete the project unless settings ask to keep it for inspection."""
        if self._office_project is None or get_settings().keep_projects:
            return
        try:
            self._office_project.project.delete()
        except Exception as e:
            logger.warning(f"Failed to delete project: {e}")
        self._office_project = None
