"""Cloud machines held ready for the fast search, and how many layouts fit a time budget.

How Allsolve runs a sweep (measured on this account, 2D office, 3 Oct):

- every sweep step is its own cloud job on its own machine. All steps start together, at
  most 100 at a time for the organisation
- the wait is the machines, not the maths. A job first shows "Reserving resources..." while
  the machines boot: about 14 s for 8 of them, 23 s for 67, 35 s for 100. The solve itself
  takes 4 to 7 s
- mesh and simulation are separate jobs, so a plain run pays that wait twice
- starting several sweeps at once from threads does not help: the wait depends on how many
  machines the account asks for in total (67 layouts took 84 s as one sweep, 130 s as eight)

A resource reservation boots the machines once and keeps them. Mesh and simulation then start
on them without waiting, and a machine takes the next sweep step as soon as it finishes one.
Booting is still the slow part, so the pool can also be warmed before a run: then a search
only pays for meshing and solving.

The fast search also uses the one-mesh model (see project_builder.py), which needs no mesh per
layout. Measured with it: 7 layouts from a cold start in 27 s, and 200 layouts (400 solves) on
100 warm machines in 31 s. It agreed with the cut-out model to 0.1 dB on every desk and zone.

With one mesh a machine does not stop after one solve (see batch_script.py): each sweep step
solves its share of the layouts one after another. Measured on the demo office (143 000
unknowns): 1.65 s per solve, of which 1.4 s is the factorisation, and the same pressures to
the last digit. A 4-core machine was only 1.3 times faster, so many small machines stay best.
Measured on 100 warm machines, two bands: 300 layouts (600 solves) in 28.9 s. A search on a
room that was searched before uses its project and mesh again: 500 layouts in 22.6 s.

Every band has its own mesh, sized for its own wavelength, and its own simulation. The 250 Hz
mesh of the demo office has 2.8 times fewer unknowns than the 500 Hz one and solves in 0.55 s
against 1.65 s. Its 250 Hz quiet-zone level differed by at most 0.06 dB from the fine mesh.
The machines are shared between the bands so that they finish together (share_machines).
"""

import atexit
import logging
import math
import threading
import time
from typing import Any, List, Optional, Sequence, Tuple

from ..config import PROJECT_ROOT, get_settings
from ..models.office import SPEED_OF_SOUND
from .project_builder import ELEMENTS_PER_WAVELENGTH

logger = logging.getLogger(__name__)

try:
    import allsolve
except ImportError:  # the API can still start and report that the SDK is missing
    allsolve = None

MAX_PARALLEL_STEPS = 100  # Allsolve's default cap on sweep steps running at once
CORES_PER_MACHINE = 1  # reservations use the 1 core / 16 GB node
WARM_MACHINES = 100
WARM_IDLE_LIMIT_S = 300.0  # an unused warm pool is given back after this long

# Timings behind the estimate, seconds
SETUP_S = 6.0  # create the project and the sweep
BOOT_BASE_S = 11.0
BOOT_PER_MACHINE_S = 0.23
BOOT_TO_START_S = 3.0  # signing in and asking for the machines, then sending the sweep
MESH_WAVE_S = 6.5
FIXED_MESH_S = 5.5  # the one mesh of the one-mesh model; it needs no reserved machine
FIRST_SOLVE_WAVE_S = 8.5
NEXT_SOLVE_WAVE_S = 3.5
READ_RESULTS_S = 1.5
# One-mesh model, where a machine solves several layouts in one sweep step
JOB_OVERHEAD_S = 7.0  # start the steps, load the mesh on each machine, upload the results
REUSED_JOB_OVERHEAD_S = 5.5  # measured 3.9 to 4.6 s when an earlier simulation already used the mesh
REUSE_SETUP_S = 1.0  # project and mesh are kept from an earlier run: only a sweep and a simulation are made
MAX_FAST_LAYOUTS = 3001  # OptimizationParams.candidate_layouts allows 3000, plus the untreated office
# The demo office (160 m2, 12 screen positions) on a mesh for 500 Hz: 18 043 corners, 143 366
# unknowns, 1.65 s per solve. On a mesh for 250 Hz: 6 523 corners, 51 706 unknowns, 0.55 s.
MEASURED_UNKNOWNS = 143_366
MEASURED_SOLVE_S = 1.65
SOLVE_GROWTH = 1.08  # solve time against unknowns, between the two meshes
MESH_DENSITY = 1.09  # mesh corners against a perfect grid of triangles of the asked size
CORNERS_PER_SLOT = 224  # extra corners around each screen position
COLD_MACHINES = 15  # used when nothing fits the budget: few machines boot fastest

_client_lock = threading.Lock()
_client: Any = None


def shared_client() -> Any:
    """One SDK client for the whole backend, so a reservation's lease is renewed in one place.

    Use it in a thread through `with shared_client().in_thread():`.
    """
    global _client
    with _client_lock:
        if _client is None:
            settings = get_settings()
            _client = allsolve.Client(
                api_key=settings.qs_access_key,
                api_secret=settings.qs_secret_key,
                host=settings.qs_host,
                cache_base_dir=str(PROJECT_ROOT / "backend"),
                dotenv_file=None,
            )
        return _client


def boot_seconds(machines: int) -> float:
    return BOOT_BASE_S + BOOT_PER_MACHINE_S * machines


def unknowns_2d(area_m2: float, frequency_hz: float, slots: int = 12) -> int:
    """Rough number of pressure unknowns in one 2D solve on a mesh sized for `frequency_hz`.

    Second-order triangles, two harmonics: eight unknowns per mesh corner. The mesh is finer
    around every screen position whatever the frequency, which adds corners per position.
    """
    mesh_size = SPEED_OF_SOUND / (frequency_hz * ELEMENTS_PER_WAVELENGTH)
    corners = MESH_DENSITY * area_m2 / (0.866 * mesh_size**2) + CORNERS_PER_SLOT * slots
    return int(8 * corners)


def solve_seconds(unknowns: int = MEASURED_UNKNOWNS) -> float:
    """Expected time of one solve inside a running job, scaled from the two measured meshes."""
    return MEASURED_SOLVE_S * (unknowns / MEASURED_UNKNOWNS) ** SOLVE_GROWTH


def share_machines(machines: int, layouts: int, band_s: Sequence[float]) -> List[int]:
    """How many machines each band's simulation gets, so that all bands finish together.

    Every band has its own mesh and so its own simulation. `band_s` is the solving time of one
    layout in each band. Each band gets one machine; the rest go one by one to the band that
    would finish last. With fewer machines than bands the steps queue on the machines there are.
    """
    shares = [1] * len(band_s)

    def seconds(i: int) -> float:
        return math.ceil(layouts / shares[i]) * band_s[i]

    for _ in range(machines - len(band_s)):
        slowest = max(range(len(band_s)), key=seconds)
        if shares[slowest] >= layouts:
            break  # a machine per layout already: more would stand idle
        shares[slowest] += 1
    return shares


def run_seconds(
    layouts: int,
    solves_per_layout: int,
    machines: int,
    warm: bool,
    fixed_mesh: bool = True,
    band_s: Optional[Sequence[float]] = None,
    reused: bool = False,
) -> float:
    """Expected wall time of one fast search of `layouts` layouts (the untreated office included).

    With `fixed_mesh` each band has one mesh, made while the machines boot, and every machine
    solves its share of the layouts in one job. `band_s` is the solving time of one layout in
    each band; `reused` means project and meshes are already there.
    Without it every layout is meshed on the reserved machines first, and each solve is a job.
    """
    booted = 0.0 if warm else boot_seconds(machines) + BOOT_TO_START_S
    if fixed_mesh:
        band_s = band_s or [solves_per_layout * solve_seconds()]
        start = max(REUSE_SETUP_S if reused else SETUP_S + FIXED_MESH_S, booted)
        shares = share_machines(machines, layouts, band_s)
        solving = max(math.ceil(layouts / share) * seconds for share, seconds in zip(shares, band_s))
        if sum(shares) > machines:
            solving *= sum(shares) / machines  # the steps take turns
        overhead = REUSED_JOB_OVERHEAD_S if reused else JOB_OVERHEAD_S
        return start + overhead + solving + READ_RESULTS_S
    start, mesh = max(SETUP_S, booted), math.ceil(layouts / machines) * MESH_WAVE_S
    waves = math.ceil(layouts * solves_per_layout / machines)
    return start + mesh + FIRST_SOLVE_WAVE_S + (waves - 1) * NEXT_SOLVE_WAVE_S + READ_RESULTS_S


def plan_fast_search(
    budget_s: float,
    solves_per_layout: int,
    warm_machines: int = 0,
    fixed_mesh: bool = True,
    band_s: Optional[Sequence[float]] = None,
    reused: bool = False,
) -> Tuple[int, int, float]:
    """The most layouts that fit the budget: (layouts, machines to run them on, expected seconds).

    The count includes the untreated office. With a warm pool the machine count is given.
    Without one, more machines solve more at a time but take longer to boot, so every size is
    tried. When not even two layouts fit, which is the case for a cold start inside 30 s, the
    plan is one wave on a few machines and the expected time says how far over it will be.
    """
    warm = bool(warm_machines)

    def seconds(layouts: int, machines: int) -> float:
        return run_seconds(layouts, solves_per_layout, machines, warm, fixed_mesh, band_s, reused)

    best: Optional[Tuple[int, int, float]] = None
    for machines in [warm_machines] if warm else range(5, MAX_PARALLEL_STEPS + 1, 5):
        # The time rises in steps, so look for the largest count that fits, from the top.
        low, high = 1, MAX_FAST_LAYOUTS
        while low < high:
            middle = (low + high + 1) // 2
            low, high = (middle, high) if seconds(middle, machines) <= budget_s else (low, middle - 1)
        if low >= 2 and (best is None or low > best[0]):
            best = (low, machines, seconds(low, machines))
    if best is None:
        machines = warm_machines or COLD_MACHINES
        layouts = machines if fixed_mesh else max(2, machines // solves_per_layout)
        best = (layouts, machines, seconds(layouts, machines))
    return best


class MachinePool:
    """At most one warm reservation, shared by every run of this backend."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reservation: Any = None
        self._state = "off"  # off, starting, ready, failed
        self._machines = 0
        self._error: Optional[str] = None
        self._boot_s: Optional[float] = None
        self._checked_at = 0.0

    def warm(self, machines: int = WARM_MACHINES) -> None:
        """Start booting machines in the background. Does nothing if a pool is already there."""
        with self._lock:
            if self._state in ("starting", "ready"):
                return
            self._state, self._machines, self._error, self._boot_s = "starting", machines, None, None
        threading.Thread(target=self._boot, args=(machines,), name="allsolve-pool", daemon=True).start()

    def _boot(self, machines: int) -> None:
        started = time.monotonic()
        reservation = None
        try:
            with shared_client().in_thread():
                reservation = allsolve.ResourceReservation.create(num_replicas=machines, max_idle_seconds=WARM_IDLE_LIMIT_S)
                with self._lock:
                    self._reservation = reservation
                reservation.wait_until_ready(poll_interval_s=1.0, timeout_s=180)
            with self._lock:
                if self._state == "starting":
                    self._state, self._boot_s = "ready", time.monotonic() - started
                    self._checked_at = time.monotonic()
        except Exception as e:
            logger.warning(f"Could not reserve {machines} machines: {e}")
            with self._lock:
                self._state, self._error, self._reservation = "failed", str(e), None
            if reservation is not None:
                _release(reservation)

    def ready_reservation(self) -> Tuple[Any, int]:
        """The warm reservation and its size, or (None, 0). Waits for a pool that is still booting."""
        while True:
            with self._lock:
                state = self._state
            if state != "starting":
                break
            time.sleep(0.5)
        self._refresh(max_age_s=0.0)
        with self._lock:
            return (self._reservation, self._machines) if self._state == "ready" else (None, 0)

    def _refresh(self, max_age_s: float) -> None:
        """Notice when Allsolve has taken an idle reservation back."""
        with self._lock:
            reservation = self._reservation
            if self._state != "ready" or time.monotonic() - self._checked_at < max_age_s:
                return
            self._checked_at = time.monotonic()
        try:
            with shared_client().in_thread():
                reservation.refresh()
            alive = reservation.status is allsolve.ReservationStatus.RESERVED
        except Exception:
            alive = False
        if not alive:
            with self._lock:
                if self._reservation is reservation:
                    self._state, self._reservation = "off", None

    def release(self) -> None:
        with self._lock:
            reservation, self._reservation, self._state = self._reservation, None, "off"
        if reservation is not None:
            _release(reservation)

    def status(self) -> dict:
        self._refresh(max_age_s=10.0)
        with self._lock:
            return {
                "state": self._state,
                "machines": self._machines if self._state in ("starting", "ready") else 0,
                "boot_s": self._boot_s,
                "error": self._error,
                "idle_limit_s": WARM_IDLE_LIMIT_S,
            }


def _release(reservation: Any) -> None:
    try:
        with shared_client().in_thread():
            reservation.stop_auto_renew()
            reservation.release()
    except Exception as e:
        logger.warning(f"Failed to release reservation {reservation.id}: {e}")


pool = MachinePool()
atexit.register(pool.release)  # never leave machines running after the backend stops
