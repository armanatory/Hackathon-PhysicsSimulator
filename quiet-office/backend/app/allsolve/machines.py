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
"""

import atexit
import logging
import math
import threading
import time
from typing import Any, Optional, Tuple

from ..config import PROJECT_ROOT, get_settings

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


def run_seconds(layouts: int, solves_per_layout: int, machines: int, warm: bool, fixed_mesh: bool = True) -> float:
    """Expected wall time of one fast search of `layouts` layouts (the untreated office included).

    With `fixed_mesh` there is one mesh, made while the machines boot. Without it every layout
    is meshed on the reserved machines first.
    """
    booted = 0.0 if warm else boot_seconds(machines) + BOOT_TO_START_S
    if fixed_mesh:
        start, mesh = max(SETUP_S + FIXED_MESH_S, booted), 0.0
    else:
        start, mesh = max(SETUP_S, booted), math.ceil(layouts / machines) * MESH_WAVE_S
    waves = math.ceil(layouts * solves_per_layout / machines)
    return start + mesh + FIRST_SOLVE_WAVE_S + (waves - 1) * NEXT_SOLVE_WAVE_S + READ_RESULTS_S


def plan_fast_search(budget_s: float, solves_per_layout: int, warm_machines: int = 0, fixed_mesh: bool = True) -> Tuple[int, int, float]:
    """The most layouts that fit the budget: (layouts, machines to run them on, expected seconds).

    The count includes the untreated office. With a warm pool the machine count is given.
    Without one, more machines solve more at a time but take longer to boot, so every size is
    tried. When not even two layouts fit, which is the case for a cold start inside 30 s, the
    plan is one wave on a few machines and the expected time says how far over it will be.
    """
    warm = bool(warm_machines)
    best: Optional[Tuple[int, int, float]] = None
    for machines in [warm_machines] if warm else range(5, MAX_PARALLEL_STEPS + 1, 5):
        layouts = 1
        while run_seconds(layouts + 1, solves_per_layout, machines, warm, fixed_mesh) <= budget_s:
            layouts += 1
        if layouts >= 2 and (best is None or layouts > best[0]):
            best = (layouts, machines, run_seconds(layouts, solves_per_layout, machines, warm, fixed_mesh))
    if best is None:
        machines = warm_machines or COLD_MACHINES
        layouts = max(2, machines // solves_per_layout)
        best = (layouts, machines, run_seconds(layouts, solves_per_layout, machines, warm, fixed_mesh))
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
