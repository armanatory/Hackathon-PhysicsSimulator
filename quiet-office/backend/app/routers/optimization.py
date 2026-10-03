"""Optimization API endpoints."""

import asyncio
import logging
import uuid
from typing import Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException

from ..allsolve import ALLSOLVE_AVAILABLE, OptimizationAborted, OptimizationRunner, planned_layout_count
from ..config import get_settings
from ..models import (
    Capabilities,
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
    )


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
    )


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
