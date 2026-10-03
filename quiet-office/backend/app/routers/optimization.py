"""Optimization API endpoints."""

import asyncio
import logging
import uuid
from typing import Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException

from ..allsolve import (
    ALLSOLVE_AVAILABLE,
    WARM_MACHINES,
    solve_seconds,
    unknowns_2d,
    OptimizationAborted,
    OptimizationRunner,
    plan_fast_search,
    planned_layout_count,
    pool,
)
from .. import explain as explainer
from ..config import get_settings
from ..models import (
    Capabilities,
    ExplainRequest,
    ExplainResponse,
    LayoutResult,
    Office,
    OptimizationParams,
    OptimizationResponse,
    OptimizationResults,
    OptimizationStatus,
    default_office,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["optimization"])

# In-memory storage for optimization state (use Redis/DB in production)
_optimizations: Dict[str, dict] = {}


@router.get("/office/default", response_model=Office)
async def get_default_office() -> Office:
    """The demo office layout: room, talker, desks and candidate screen positions."""
    return default_office()


@router.get("/capabilities", response_model=Capabilities)
async def get_capabilities() -> Capabilities:
    """Tell the frontend whether real Allsolve runs are possible on this backend."""
    settings = get_settings()
    return Capabilities(
        sdk_installed=ALLSOLVE_AVAILABLE,
        credentials_configured=settings.has_credentials,
        host=settings.qs_host,
        ai_configured=explainer.is_configured(),
    )


def _machines(sources: int, hz: str, budget_s: float, area_m2: float = 160.0) -> dict:
    """The warm machine pool, and what a fast search could do right now with and without it.

    `hz` is the bands, comma separated. Each band is solved on its own mesh, so the room's area
    and the band set how long a solve takes. `plan_repeat` is a search on warm machines of a
    room that was searched before, whose meshes are used again.
    """
    status = pool.status()
    try:
        bands = [float(value) for value in hz.split(",") if value.strip()] or [500.0]
    except ValueError:
        raise HTTPException(status_code=422, detail="hz must be numbers separated by commas")
    sources = max(1, sources)
    band_s = [sources * solve_seconds(unknowns_2d(area_m2, band)) for band in bands]

    def plan(machines: int, reused: bool = False) -> dict:
        layouts, used, seconds = plan_fast_search(budget_s, sources * len(bands), machines, True, band_s, reused)
        return {"layouts": layouts, "machines": used, "seconds": round(seconds)}

    return {
        **status,
        "warm_size": WARM_MACHINES,
        "solve_s": [round(seconds / sources, 2) for seconds in band_s],
        "plan_cold": plan(0),
        "plan_warm": plan(WARM_MACHINES),
        "plan_repeat": plan(WARM_MACHINES, True),
        "plan_now": plan(status["machines"]),
    }


@router.get("/machines")
async def get_machines(sources: int = 1, hz: str = "250,500", budget_s: float = 30.0, area_m2: float = 160.0) -> dict:
    """Whether cloud machines are being held ready, and how many layouts fit the time budget."""
    if not ALLSOLVE_AVAILABLE or not get_settings().has_credentials:
        raise HTTPException(status_code=503, detail="Allsolve is not available on the backend")
    return await asyncio.to_thread(_machines, sources, hz, budget_s, area_m2)


@router.post("/machines/warm")
async def warm_machines(sources: int = 1, hz: str = "250,500", budget_s: float = 30.0, area_m2: float = 160.0) -> dict:
    """Boot machines on Allsolve and hold them, so the next fast search does not wait for them.

    They cost credits while held. An unused pool is given back after five minutes.
    """
    if not ALLSOLVE_AVAILABLE or not get_settings().has_credentials:
        raise HTTPException(status_code=503, detail="Allsolve is not available on the backend")
    pool.warm(WARM_MACHINES)
    return await asyncio.to_thread(_machines, sources, hz, budget_s, area_m2)


@router.post("/machines/release")
async def release_machines(sources: int = 1, hz: str = "250,500", budget_s: float = 30.0, area_m2: float = 160.0) -> dict:
    """Give the held machines back to Allsolve."""
    await asyncio.to_thread(pool.release)
    return await asyncio.to_thread(_machines, sources, hz, budget_s, area_m2)


@router.post("/explain", response_model=ExplainResponse)
async def explain_result(request: ExplainRequest) -> ExplainResponse:
    """Explain an Allsolve run in plain language with an OpenAI model.

    Only a run that was really sent to Allsolve can be explained: pass its optimization_id so
    its log is part of the facts. The model only narrates what it is given; it computes nothing.
    """
    if not explainer.is_configured():
        raise HTTPException(status_code=503, detail="No OpenAI key configured. Add OPENAI_API_KEY to .env and restart the backend.")
    runner = _optimizations.get(request.optimization_id or "", {}).get("runner")
    entries = runner.log.since(0) if runner else None
    if not entries:
        raise HTTPException(status_code=409, detail="Nothing has been run on Allsolve yet, so there is no run to explain.")
    try:
        return ExplainResponse(**await asyncio.to_thread(explainer.explain, request.context, entries))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/optimization/start", response_model=OptimizationResponse)
async def start_optimization(
    params: OptimizationParams,
    background_tasks: BackgroundTasks,
) -> OptimizationResponse:
    """
    Start a screen-placement search on Allsolve.

    Returns immediately with an optimization ID. Poll the status endpoint for progress.
    """
    if not ALLSOLVE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Allsolve SDK is not installed on the backend")
    if not get_settings().has_credentials:
        raise HTTPException(status_code=503, detail="Allsolve API credentials are not configured (.env)")
    if params.n_screens > len(params.office.slots):
        raise HTTPException(status_code=422, detail="More screens than candidate positions")
    if params.strategy == "fast" and params.model != "2d":
        raise HTTPException(status_code=422, detail="The fast search runs on the 2D model only")

    optimization_id = str(uuid.uuid4())
    _optimizations[optimization_id] = {
        "id": optimization_id,
        "params": params,
        "status": "pending",
        "progress": 0.0,
        "message": "Queued",
        "layouts": [],
        "layouts_total": planned_layout_count(params),
        "results": None,
        "error": None,
        "runner": None,
    }
    logger.info(f"New optimization {optimization_id}: {params.n_screens} screens, {params.strategy}")
    background_tasks.add_task(run_optimization_task, optimization_id, params)
    return OptimizationResponse(optimization_id=optimization_id)


async def run_optimization_task(optimization_id: str, params: OptimizationParams) -> None:
    """Background task: run the blocking search in a thread pool."""
    state = _optimizations[optimization_id]
    runner = OptimizationRunner()
    state["runner"] = runner

    def on_progress(message: str, progress: float) -> None:
        state["progress"] = progress
        state["message"] = message

    def on_layout(result: LayoutResult, done: int, total: int) -> None:
        state["layouts"].append(result)
        state["layouts_total"] = total

    try:
        state["status"] = "running"
        results = await asyncio.to_thread(runner.run_sync, params, on_progress, on_layout)
        state["status"] = "completed"
        state["progress"] = 100.0
        state["results"] = results
    except OptimizationAborted:
        state["status"] = "aborted"
        state["error"] = "Optimization aborted by user"
    except Exception as e:
        logger.exception("Optimization failed")
        state["status"] = "failed"
        state["error"] = str(e)
    finally:
        runner.cleanup()


def _get(optimization_id: str) -> dict:
    if optimization_id not in _optimizations:
        raise HTTPException(status_code=404, detail="Optimization not found")
    return _optimizations[optimization_id]


@router.get("/optimization/{optimization_id}/status", response_model=OptimizationStatus)
async def get_optimization_status(optimization_id: str) -> OptimizationStatus:
    """Get the current status of an optimization."""
    state = _get(optimization_id)
    n_screens = state["params"].n_screens
    full = [r.score for r in state["layouts"] if len(r.slot_ids) == n_screens]
    runner = state.get("runner")
    return OptimizationStatus(
        optimization_id=optimization_id,
        status=state["status"],
        progress=state["progress"],
        message=state.get("error") or state.get("message"),
        layouts_done=len(state["layouts"]),
        layouts_total=state["layouts_total"],
        best_score=min(full) if full else None,
        project_url=runner.project_url if runner else None,
        project_name=runner.project_name if runner else None,
        log_size=len(runner.log) if runner else 0,
        jobs=[dict(job) for job in list(runner.jobs)] if runner else [],
    )


@router.get("/optimization/{optimization_id}/log")
async def get_optimization_log(optimization_id: str, since: int = 0) -> dict:
    """The run log: every request sent to Allsolve and every answer, from entry `since` on."""
    state = _get(optimization_id)
    runner = state.get("runner")
    return {"optimization_id": optimization_id, "entries": runner.log.since(since) if runner else []}


@router.get("/optimization/{optimization_id}/results", response_model=OptimizationResults)
async def get_optimization_results(optimization_id: str) -> OptimizationResults:
    """Get the results of a completed optimization."""
    state = _get(optimization_id)
    if state["status"] == "failed":
        raise HTTPException(status_code=500, detail=state.get("error") or "Optimization failed")
    if state["status"] != "completed":
        raise HTTPException(status_code=400, detail="Optimization not yet completed")
    return OptimizationResults(optimization_id=optimization_id, status="completed", **state["results"])


@router.post("/optimization/{optimization_id}/abort")
async def abort_optimization(optimization_id: str) -> dict:
    """Abort a running optimization and the cloud job it is waiting on."""
    state = _get(optimization_id)
    if state["status"] not in ("pending", "running"):
        raise HTTPException(status_code=400, detail=f"Cannot abort optimization with status: {state['status']}")
    runner = state.get("runner")
    if not runner:
        raise HTTPException(status_code=400, detail="No runner available to abort")
    await asyncio.to_thread(runner.abort)
    return {"status": "aborting", "message": "Abort requested"}
