"""Search for the best screen layout by running Allsolve sweeps, several at a time."""

import io
import itertools
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..config import get_settings
from ..models.office import SPEED_OF_SOUND, LayoutResult, OptimizationParams
from ..scoring import SPEECH_LEVEL_AT_1M_DB, combine_bands, combine_sources, level_db, raw_score
from .project_builder import (
    ELEMENTS_PER_WAVELENGTH,
    OfficeProject,
    add_probe_outputs,
    build_office_project,
    receiver_output_name,
    reference_output_name,
    screen_variables,
    source_variables,
)
from .batch_script import BATCH_DONE_LINE, BATCH_VARIABLE,PRESSURES_OUTPUT, SECONDS_OUTPUT, batch_script
from .machines import (
    CORES_PER_MACHINE,
    MAX_PARALLEL_STEPS,
    plan_fast_search,
    pool,
    share_machines,
    shared_client,
    solve_seconds,
    unknowns_2d,
)
from .project_builder_3d import build_office_project_3d
from .run_log import ERROR, INFO, RECEIVED, SENT, SOLVER, RunLog

logger = logging.getLogger(__name__)

try:
    import allsolve
    from allsolve.resource_reservation import keep_reservation_alive

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


# One-mesh projects kept from earlier fast searches, with their finished meshes. A search on
# the same room, sources and screen positions starts solving at once: only the listening
# points and the layouts differ, and neither is in a mesh.
_kept_projects: Dict[str, tuple] = {}  # office_key -> (OfficeProject, {band in Hz: mesh})
_kept_lock = threading.Lock()


def office_key(params: OptimizationParams) -> str:
    """Everything the one-mesh project and its meshes are built from, bar the band of each mesh."""
    office = params.office
    return repr(
        (
            [(p.x, p.y) for p in office.outline],
            [(s.x, s.y) for s in office.sources],
            [(s.id, s.x, s.y, s.orientation) for s in office.slots],
            params.screen_length_m,
            params.screen_thickness_m,
        )
    )


def kept_project(params: OptimizationParams) -> Optional[tuple]:
    with _kept_lock:
        return _kept_projects.get(office_key(params))


def band_seconds(params: OptimizationParams) -> List[float]:
    """Expected solving time of one layout in each band, on that band's own mesh."""
    office = params.office
    min_x, min_y, max_x, max_y = office.bounds
    area = (max_x - min_x) * (max_y - min_y)
    return [len(office.sources) * solve_seconds(unknowns_2d(area, band)) for band in params.frequencies_hz]


def planned_layout_count(params: OptimizationParams) -> int:
    """How many layouts the chosen strategy will simulate, including the untreated office."""
    n_slots, n = len(params.office.slots), params.n_screens
    if params.strategy == "fast":
        return len(fast_layouts(params, pool.status()["machines"])[0])
    if params.strategy == "exhaustive":
        return 1 + len(list(itertools.combinations(range(n_slots), n)))
    return 1 + sum(n_slots - k for k in range(n))


def fast_layouts(params: OptimizationParams, warm_machines: int) -> tuple:
    """What the fast search will simulate: (layouts, machines to run them on, expected seconds).

    The untreated office comes first, then as many candidates as fit the time budget.
    """
    solves_per_layout = len(params.office.sources) * len(params.frequencies_hz)
    kept = kept_project(params) if params.fixed_mesh else None
    reused = kept is not None and all(band in kept[1] for band in params.frequencies_hz)
    limit, machines, seconds = plan_fast_search(
        params.time_budget_s, solves_per_layout, warm_machines, params.fixed_mesh, band_seconds(params) if params.fixed_mesh else None, reused
    )
    slot_ids = {slot.id for slot in params.office.slots}
    candidates, seen = [], set()
    for layout in params.candidate_layouts:
        key = tuple(sorted(layout))
        if len(layout) == params.n_screens and len(set(layout)) == len(layout) and set(layout) <= slot_ids and key not in seen:
            seen.add(key)
            candidates.append(list(layout))
    if not candidates:
        # No ranking given: spread the budget evenly over every combination.
        every = [list(c) for c in itertools.combinations(sorted(slot_ids), params.n_screens)]
        step = max(1.0, len(every) / max(1, limit - 1))
        candidates = [every[int(i * step)] for i in range(min(len(every), limit - 1))]
    layouts = [[]] + candidates[: limit - 1]
    # In the one-mesh model a machine solves whole layouts; otherwise one solve each.
    useful = len(layouts) if params.fixed_mesh else len(layouts) * solves_per_layout
    return layouts, min(machines, max(1, useful)), seconds


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
        self.project_name: Optional[str] = None  # as it is listed in Allsolve
        self.project_id: Optional[str] = None
        self.log = RunLog()
        self.jobs: List[dict] = []  # every mesh and simulation job started on Allsolve
        self._references: List[List[float]] = []  # pressure 1 m from each source, per band
        self._baseline_raw: Optional[float] = None
        self._pressures: Dict[tuple, Pressures] = {}  # raw solver output per layout
        self._reservation = None  # machines held for the fast search
        self._own_reservation = False  # booted for this run, so given back when it ends
        self._machines_thread: Optional[threading.Thread] = None
        self._machines_error: Optional[Exception] = None
        self._machines = 1  # how many machines the fast search runs on
        self._meshes: Dict[float, Any] = {}  # band in Hz -> its mesh in the one-mesh project

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
        self._client = shared_client()
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
        started = time.monotonic()
        try:
            with self._client.in_thread():
                return self._search(params, progress, record, results, started)
        except OptimizationAborted:
            self.log.add(ERROR, "abort", "Run stopped by the user")
            raise
        except Exception as e:
            self.log.add(ERROR, "failed", f"{type(e).__name__}: {e}")
            raise
        finally:
            self._release_own_machines()
            with self._jobs_lock:
                self._running_jobs.clear()

    def _search(
        self,
        params: OptimizationParams,
        progress: ProgressCallback,
        record: Callable[[Sequence[LayoutResult]], None],
        results: List[LayoutResult],
        started: float,
    ) -> dict:
        """The search itself. The SDK client is bound to this thread."""
        # The fast search asks for its machines first, so they boot while the project is built.
        fast = self._prepare_machines(params) if params.strategy == "fast" else None
        kept = kept_project(params) if fast is not None and params.fixed_mesh else None
        if kept is not None:
            try:
                next(iter(kept[1].values())).refresh()  # the project may have been deleted in the Allsolve browser
            except Exception:
                with _kept_lock:
                    _kept_projects.pop(office_key(params), None)
                kept = None
        if kept is not None:
            self._office_project, self._meshes = kept
        elif params.model == "3d":
            progress("Creating the 3D office project in Allsolve...", 3)
            self._office_project = build_office_project_3d(self._client, params, self.log)
        else:
            progress("Creating the 2D office project in Allsolve...", 3)
            self._office_project = build_office_project(self._client, params, self.log, fixed_mesh=fast is not None and params.fixed_mesh)
        self.project_id = self._office_project.project.id
        self.project_url = self._client.get_url(self._office_project.project)
        self.project_name = self._office_project.project.name
        if kept is not None:
            self.log.add(
                INFO,
                "project",
                f"Room, sources and screen positions are the same as in an earlier search, so its project '{self.project_name}' and its meshes are used again: {self.project_url}",
                {"url": self.project_url, "project_id": self.project_id},
            )
        else:
            self.log.add(RECEIVED, "project", f"Project '{self.project_name}' is open at {self.project_url}", {"url": self.project_url, "name": self.project_name})

        slot_ids = [slot.id for slot in params.office.slots]
        if fast is not None:
            record(self._run_fast(params, fast, progress))
        elif params.strategy == "exhaustive":
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
                batch = self._run_round(params, layouts, f"panel {k + 1} of {params.n_screens}", progress, start, start + span)
                record(batch)
                placed = [r for r in batch if len(r.slot_ids) == k + 1]
                chosen = min(placed, key=lambda r: r.score).slot_ids

        baseline = next(r for r in results if not r.slot_ids)
        candidates = [r for r in results if len(r.slot_ids) == params.n_screens]
        best = min(candidates, key=lambda r: r.score)
        self.log.add(
            INFO,
            "result",
            f"Best of {len(results)} simulated layouts: screens in positions {best.slot_ids}, score {best.score:.1f} "
            f"(untreated = 100). The search took {time.monotonic() - started:.0f} s",
            {"seconds": round(time.monotonic() - started, 1), "layouts": len(results)},
        )
        progress("Complete", 100)
        return {
            "baseline": baseline.model_dump(),
            "best": best.model_dump(),
            "layouts": [r.model_dump() for r in results],
            "project_url": self.project_url,
            "project_name": self.project_name,
            "parameters": params.model_dump(),
            "evidence": self.evidence(params, baseline, best),
        }

    # ------------------------------------------------------------ fast search

    def _prepare_machines(self, params: OptimizationParams) -> List[Layout]:
        """Decide what the fast search simulates and get machines for it.

        A warm pool is used as it is. Otherwise machines start booting now, in the background.
        """
        if params.model != "2d":
            raise RuntimeError("The fast search runs on the 2D model only: one 3D layout takes minutes to mesh.")
        reservation, warm = pool.ready_reservation()
        layouts, machines, seconds = fast_layouts(params, warm)
        solves = len(layouts) * len(params.office.sources) * len(params.frequencies_hz)
        fit = f"{len(layouts)} layouts, {solves} solves, expected to take about {seconds:.0f} s (budget {params.time_budget_s:.0f} s)"
        if reservation is not None:
            self._reservation, self._machines = reservation, warm
            self.log.add(
                INFO,
                "machines",
                f"Using {warm} machines that are already running: {fit}",
            )
            return layouts
        quota = allsolve.get_quota()
        free = (quota.max_concurrent_cores - quota.total_running_cores - quota.total_reserved_cores) // CORES_PER_MACHINE
        machines = self._machines = max(1, min(machines, free, MAX_PARALLEL_STEPS))
        self.log.add(
            SENT,
            "machines",
            f"Asked Allsolve for {machines} machines. None were running, so they boot while the project is built: {fit}",
            {"machines": machines, "free_cores": free},
        )

        def boot() -> None:
            began = time.monotonic()
            try:
                with self._client.in_thread():
                    self._reservation = allsolve.ResourceReservation.create(num_replicas=machines, max_idle_seconds=120)
                    self._own_reservation = True
                    self._reservation.wait_until_ready(poll_interval_s=0.5, timeout_s=180)
                self.log.add(RECEIVED, "machines", f"{machines} machines are running after {time.monotonic() - began:.0f} s")
            except Exception as e:
                self._machines_error = e

        self._machines_thread = threading.Thread(target=boot, name="allsolve-machines", daemon=True)
        self._machines_thread.start()
        return layouts

    def _run_fast(self, params: OptimizationParams, layouts: List[Layout], progress: ProgressCallback) -> List[LayoutResult]:
        """Simulate every chosen layout at once, as one sweep on the reserved machines."""

        def machines():
            if self._machines_thread is not None:
                progress("Waiting for the Allsolve machines to boot...", 20)
                while self._machines_thread.is_alive():
                    self._machines_thread.join(timeout=0.5)
                    self._check_abort()
                if self._machines_error is not None:
                    raise RuntimeError(f"Could not get machines from Allsolve: {self._machines_error}")
            n_solves = len(layouts) * len(params.office.sources) * len(params.frequencies_hz)
            progress(f"Solving {len(layouts)} layouts on {min(self._machines, len(layouts))} machines: {n_solves} solves...", 40)
            return self._reservation

        if self._office_project.fixed_mesh:
            # One small mesh for every layout: it is made while the machines are still booting.
            pressures = self._solve_batched(params, layouts, machines)
        else:
            reservation = machines()
            with keep_reservation_alive(reservation):
                pressures = self._solve_chunk(params, layouts, "fast search", reservation)
        progress(f"Scoring {len(layouts)} layouts...", 95)
        for layout, p in zip(layouts, pressures):
            self._pressures[tuple(layout)] = p
        scored = self._score(params, layouts, pressures)
        self.log.add(
            INFO,
            "score",
            f"Scored {len(layouts)} layouts from the solver's pressures",
            {"scores": [{"positions": r.slot_ids, "score": round(r.score, 1)} for r in scored]},
        )
        return scored

    def _release_own_machines(self) -> None:
        """Give back machines that were booted for this run. A warm pool is left running."""
        thread = self._machines_thread
        if thread is None:
            self._reservation = None
            return

        def release() -> None:
            thread.join(timeout=200)  # a reservation that is still booting has to be given back too
            reservation, self._reservation = self._reservation, None
            if reservation is None or not self._own_reservation:
                return
            try:
                with self._client.in_thread():
                    reservation.stop_auto_renew()
                    reservation.release()
            except Exception as e:
                logger.warning(f"Failed to release reservation: {e}")

        threading.Thread(target=release, name="allsolve-release", daemon=True).start()

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
            f"Meshing and solving {len(layouts)} layouts ({label}): {n_solves} solves"
            + (f", split over {len(chunks)} jobs running at the same time..." if len(chunks) > 1 else ", all at the same time..."),
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

    def _solve_chunk(
        self,
        params: OptimizationParams,
        layouts: List[Layout],
        label: str,
        reservation=None,
    ) -> List[Pressures]:
        """Mesh and solve some layouts as one sweep, and read the pressure at every probe.

        Allsolve gives every sweep step its own machine and runs them at the same time. With a
        `reservation` the jobs start on machines that are already running.
        """
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
        self.log.add(
            SENT,
            "mesh",
            f"Asked Allsolve to mesh {len(layouts)} geometries ({label})",
            {"mesh_id": mesh.id, "max_element_size_m": round(office_project.mesh_size_m, 4)},
        )

        def create_simulation():
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
            return simulation

        # The simulation only needs the mesh's id, so it is set up while the mesh is running.
        simulation = self._wait(mesh_instance, f"Meshing ({label})", "mesh", mesh.id, reservation, meanwhile=create_simulation, steps=len(layouts))
        self.log.add(
            SENT,
            "simulation",
            f"Started harmonic acoustic simulation ({label}): {n_points} solves, {len(office.receivers()) + n_sources} pressure probes each",
            {"simulation_id": simulation.id, "solver": str(office_project.solver_mode or "direct"), "probes": len(office.receivers()) + n_sources},
        )
        with keep_reservation_alive(reservation):
            self._wait(simulation, f"Simulation ({label})", "simulation", simulation.id, reservation, steps=n_points)

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

    def _solve_batched(self, params: OptimizationParams, layouts: List[Layout], machines: Callable) -> List[Pressures]:
        """Solve every layout, each band on its own mesh, each machine taking a share of the layouts.

        A band's mesh is sized for its own wavelength, so the low bands solve much faster. Each
        band is one simulation, and the machines are shared between them so that they finish
        together. A sweep has one step per machine and only tells the machine which share of
        the layouts is its own; the solver script (batch_script.py) solves that share one
        layout after another and returns all its probe pressures as one list. `machines` is
        called for the reservation when the simulations are ready to start.
        """
        self._check_abort()
        office_project = self._office_project
        project = office_project.project
        office = params.office
        bands = params.frequencies_hz
        n_sources = len(office.sources)
        names = [receiver_output_name(i) for i in range(len(office.receivers()))]
        names += [reference_output_name(s) for s in range(n_sources)]
        shares = share_machines(self._machines, len(layouts), band_seconds(params))
        per_machine = [-(-len(layouts) // share) for share in shares]
        steps = [-(-len(layouts) // count) for count in per_machine]
        n_solves = len(layouts) * n_sources * len(bands)
        tag = f"{time.time():.0f}"  # a kept project is searched more than once
        self.log.add(
            SENT,
            "sweep",
            f"Sent the fast search: {len(layouts)} layouts x {n_sources} sources x {len(bands)} bands = {n_solves} solves. "
            + "; ".join(f"{band:.0f} Hz on {steps[i]} machines, {per_machine[i]} layouts each" for i, band in enumerate(bands)),
            {"layouts": layouts, "frequencies_hz": bands, "machines": steps, "layouts_per_machine": per_machine},
        )

        def prepare(index: int):
            """The mesh of one band, unless it is kept from an earlier search, and its simulation."""
            band = bands[index]
            sweep = project.create_variable_overrides(
                name=f"batches_{band:.0f}Hz_{tag}", overrides=[(BATCH_VARIABLE, list(range(steps[index])))]
            )

            def create_simulation():
                simulation = project.create_simulation_harmonic(
                    name=f"Harmonic fast search {band:.0f} Hz {tag}",
                    description=f"{len(layouts)} layouts x {n_sources} sources at {band:.0f} Hz, {per_machine[index]} layouts per machine",
                    max_run_time_minutes=office_project.max_run_time_minutes,
                    solver_mode=allsolve.SolverMode.DIRECT,
                    fundamental_frequency="freq",
                    mesh=self._meshes[band],
                    variable_overrides=sweep,
                    physics_set=office_project.physics_set,
                )
                # The generated single solve is switched off: the script solves this machine's layouts.
                simulation.disabled_script_sections = [allsolve.DisableableSection.SOLVE]
                simulation.save()
                simulation.set_scripts(
                    [
                        allsolve.Script(
                            name="solve_layouts.py",
                            section_name=allsolve.CustomSection.AFTER_FORMULATIONS_CREATED,
                            content=batch_script(params, layouts, per_machine[index], [band]),
                        )
                    ]
                )
                return simulation

            if band in self._meshes:
                return create_simulation()
            mesh_size = SPEED_OF_SOUND / (band * ELEMENTS_PER_WAVELENGTH)
            mesh = self._meshes[band] = project.create_mesh(
                allsolve.MeshSettings(
                    name=f"Mesh {band:.0f} Hz",
                    mesh_size_max=mesh_size,
                    mesh_size_min=mesh_size / 4,
                    max_run_time_minutes=20,
                )
            )
            self.log.add(
                SENT,
                "mesh",
                f"Asked Allsolve for the {band:.0f} Hz mesh, which serves all {len(layouts)} layouts",
                {"mesh_id": mesh.id, "max_element_size_m": round(mesh_size, 4)},
            )
            # The simulation only needs the mesh's id, so it is set up while the mesh is running.
            return self._wait(mesh, f"Meshing ({band:.0f} Hz)", "mesh", mesh.id, meanwhile=create_simulation)

        simulations = self._in_parallel(prepare, len(bands))
        if get_settings().keep_projects:
            with _kept_lock:
                _kept_projects[office_key(params)] = (office_project, self._meshes)

        reservation = machines()
        self.log.add(
            SENT,
            "simulation",
            f"Started {len(bands)} harmonic acoustic simulations, one per band: {n_solves} solves on {sum(steps)} machines, {len(names)} pressure probes each",
            {"simulation_ids": [simulation.id for simulation in simulations], "solver": "direct", "probes": len(names)},
        )
        per_layout = n_sources * len(names)

        def solve(index: int) -> tuple:
            """Run one band and read its pressures: ([layout][source][probe], seconds of each solve)."""
            band, simulation = bands[index], simulations[index]
            self._wait(simulation, f"Simulation ({band:.0f} Hz)", "simulation", simulation.id, reservation, steps=steps[index])
            data = simulation.get_output_data(refresh=True)
            step = data.get_step_index(data.NO_STEP)
            pressures, seconds = [], []
            for batch in range(steps[index]):
                values = data.get_values_at(batch, step, PRESSURES_OUTPUT)
                expected = len(layouts[batch * per_machine[index] : (batch + 1) * per_machine[index]]) * per_layout
                if values is None or len(values) != expected:
                    raise RuntimeError(
                        f"Machine {batch} of the {band:.0f} Hz simulation returned {0 if values is None else len(values)} pressures, expected {expected}"
                    )
                seconds += data.get_values_at(batch, step, SECONDS_OUTPUT) or []
                for start in range(0, expected, per_layout):
                    # Within a layout the order is (source, probe), as the script solved them.
                    pressures.append([[abs(float(v)) for v in values[start + s * len(names) :][: len(names)]] for s in range(n_sources)])
            return pressures, seconds

        with keep_reservation_alive(reservation):
            solved = self._in_parallel(solve, len(bands))

        result: List[Pressures] = [
            {
                name: [[solved[f][0][layout][s][i] for f in range(len(bands))] for s in range(n_sources)]
                for i, name in enumerate(names)
            }
            for layout in range(len(layouts))
        ]
        timing = ", ".join(
            f"{band:.0f} Hz {sum(solved[i][1]) / max(1, len(solved[i][1])):.2f} s" for i, band in enumerate(bands)
        )
        self.log.add(
            RECEIVED,
            "pressures",
            f"Read {len(result) * per_layout * len(bands)} pressure values from Allsolve. One solve took: {timing}. "
            f"{sum(sum(seconds) for _, seconds in solved):.0f} s of computing in all",
            {
                "simulation_ids": [simulation.id for simulation in simulations],
                "sample_layout": layouts[0],
                "sample_pressures_pa": {name: [[float(f"{v:.4g}") for v in row] for row in result[0][name]] for name in names[:4]},
            },
        )
        return result

    def _in_parallel(self, work: Callable[[int], Any], count: int) -> list:
        """Run work(0) to work(count - 1) at the same time, each in a thread with its own SDK session."""
        if count == 1:
            return [work(0)]

        def threaded(index: int):
            with self._client.in_thread():
                return work(index)

        with ThreadPoolExecutor(max_workers=count, thread_name_prefix="allsolve") as executor:
            futures = [executor.submit(threaded, i) for i in range(count)]
            try:
                return [future.result() for future in futures]
            except BaseException:
                # One job failed or the user aborted: stop the others before leaving.
                self._abort.set()
                self._abort_running_jobs()
                raise

    def _wait(self, job, what: str, kind: str, job_id: str, reservation=None, meanwhile: Optional[Callable] = None, steps: int = 1):
        """Start a cloud job and block until it is done, honouring abort.

        `meanwhile` is called once the job has started; its result is returned. `steps` is how
        many sweep steps the job has: Allsolve runs each on its own machine, all at once.
        """
        prepared = None
        # server_status, progress and steps_done are what Allsolve reports while the job runs.
        record = {"kind": kind, "id": job_id, "what": what, "status": "running", "steps": steps, "server_status": None, "progress": None, "steps_done": None}
        with self._jobs_lock:
            self._running_jobs.add(job)
            self.jobs.append(record)
        try:
            if reservation is not None:
                job.start(resource_reservation=reservation)
            else:
                job.start()
            if meanwhile is not None:
                prepared = meanwhile()
            # On reserved machines a job takes seconds, so look more often.
            while job.is_running(refresh_delay_s=1 if reservation is not None else 3):
                self._observe(job, record)
                self._solver_lines(job, what, record)
                self._check_abort()
            self._observe(job, record)
            self._solver_lines(job, what, record)
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
            return prepared
        except Exception:
            if record["status"] == "running":
                record["status"] = "stopped"
            raise
        finally:
            with self._jobs_lock:
                self._running_jobs.discard(job)

    def _observe(self, job, record: dict) -> None:
        """Copy what Allsolve reports about a job into its record: status, progress, meshed sweep steps.

        The SDK has no call for the progress of a job or for the status of one sweep step of a
        simulation, so the progress is read from the job as the SDK last fetched it. A value
        Allsolve does not give stays None.
        """

        def plain(value):
            return getattr(value, "value", value)

        try:
            record["server_status"] = str(plain(job.get_status()))
            raw = getattr(getattr(job, "_simulation", None), "simulation_job", None)
            instance = getattr(job, "_raw_instance", None)
            if raw is None:
                raw = getattr(instance, "meshing_job", None)
            progress = getattr(raw, "progress", None)
            if progress is not None:
                record["progress"] = float(progress)
            files = getattr(instance, "files", None)
            if files and record["steps"] > 1:
                record["steps_done"] = sum(1 for f in files if plain(getattr(f, "job_status", None)) == allsolve.Job.SUCCESS)
        except Exception:
            pass  # a status display must never stop a run

    def _solver_lines(self, job, what: str, record: Optional[dict] = None) -> None:
        """Copy new lines of the cloud job's own log into the run log.

        A machine of the fast search prints one line when it has solved its share (see
        batch_script.py); those lines are counted in `record` as sweep steps that are done.
        """
        try:
            buffer = io.StringIO()
            job.print_new_loglines(buffer)
        except Exception:
            return
        for line in buffer.getvalue().splitlines():
            if line.strip():
                self.log.add(SOLVER, what, line.rstrip()[:300])
                if record is not None and BATCH_DONE_LINE in line:
                    record["steps_done"] = (record["steps_done"] or 0) + 1

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
        objective = office.objective_indices()  # the quiet zones, or the desks when there are none

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
            raw = raw_score([levels[i] for i in objective])
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
