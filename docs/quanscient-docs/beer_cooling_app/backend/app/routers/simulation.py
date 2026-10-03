"""Simulation API endpoints."""

import asyncio
import uuid
import logging
from typing import Dict, Optional
from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)

from ..models import (
    SimulationParams,
    SimulationResponse,
    SimulationStatus,
    SimulationResults,
    TemperaturePoint,
)
from ..allsolve.simulation_runner import SimulationRunner

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/api/simulation", tags=["simulation"])

# In-memory storage for simulation state (use Redis/DB in production)
_simulations: Dict[str, dict] = {}
_websocket_connections: Dict[str, WebSocket] = {}


@router.post("/start", response_model=SimulationResponse)
async def start_simulation(
    params: SimulationParams,
    background_tasks: BackgroundTasks,
) -> SimulationResponse:
    """
    Start a new beer cooling simulation.

    This endpoint initiates a simulation with the given parameters and returns
    immediately with a simulation ID. Use the status endpoint or WebSocket
    to monitor progress.
    """
    simulation_id = str(uuid.uuid4())

    logger.info("=" * 60)
    logger.info("🍺 NEW SIMULATION REQUEST (REAL ALLSOLVE MODE)")
    logger.info("=" * 60)
    logger.info(f"   Simulation ID: {simulation_id}")
    logger.info(f"   Container: {params.container_shape}")
    logger.info(f"   Cooling: {params.cooling_method}")
    logger.info(f"   Initial temp: {params.initial_temp_celsius}°C")

    # Initialize simulation state
    _simulations[simulation_id] = {
        "id": simulation_id,
        "params": params,
        "status": "pending",
        "progress": 0.0,
        "results": None,
        "error": None,
        "runner": None,  # Will hold the SimulationRunner for abort
    }

    # Run simulation in background
    background_tasks.add_task(run_simulation_task, simulation_id, params)

    return SimulationResponse(
        simulation_id=simulation_id,
        project_id="",  # Will be set when project is created
        status="pending",
        message="Simulation queued for execution",
    )


async def run_simulation_task(simulation_id: str, params: SimulationParams) -> None:
    """Background task to run the simulation in a thread pool."""
    runner = SimulationRunner()

    # Store runner for abort functionality
    if simulation_id in _simulations:
        _simulations[simulation_id]["runner"] = runner

    def on_progress_sync(status: str, progress: float) -> None:
        """Synchronous progress callback (called from thread)."""
        logger.info(f"📈 Progress: {progress:.1f}% - {status}")
        if simulation_id in _simulations:
            _simulations[simulation_id]["status"] = "running"
            _simulations[simulation_id]["progress"] = progress
            _simulations[simulation_id]["message"] = status

    def run_blocking_simulation() -> dict:
        """Run the blocking simulation in a thread."""
        return runner.run_simulation_sync(params, on_progress_sync)

    try:
        _simulations[simulation_id]["status"] = "running"

        # Run blocking simulation in thread pool to not block event loop
        results = await asyncio.to_thread(run_blocking_simulation)

        _simulations[simulation_id]["status"] = "completed"
        _simulations[simulation_id]["progress"] = 100.0
        _simulations[simulation_id]["results"] = results

        # Notify WebSocket
        if simulation_id in _websocket_connections:
            try:
                await _websocket_connections[simulation_id].send_json(
                    {
                        "type": "completed",
                        "results": results,
                    }
                )
            except Exception:
                pass

    except Exception as e:
        _simulations[simulation_id]["status"] = "failed"
        _simulations[simulation_id]["error"] = str(e)

        if simulation_id in _websocket_connections:
            try:
                await _websocket_connections[simulation_id].send_json(
                    {
                        "type": "error",
                        "error": str(e),
                    }
                )
            except Exception:
                pass

    finally:
        runner.cleanup()


@router.get("/{simulation_id}/status", response_model=SimulationStatus)
async def get_simulation_status(simulation_id: str) -> SimulationStatus:
    """Get the current status of a simulation."""
    if simulation_id not in _simulations:
        raise HTTPException(status_code=404, detail="Simulation not found")

    sim = _simulations[simulation_id]
    logger.info(
        f"📊 Status poll: status={sim['status']}, progress={sim['progress']:.1f}%, msg={sim.get('message', '')[:40]}"
    )
    results = sim.get("results", {})

    # Get latest temperature if available
    current_temp = None
    current_time = None
    if results and "temperature_history" in results:
        history = results["temperature_history"]
        if history:
            current_temp = history[-1].get("temperature_celsius")
            current_time = history[-1].get("time_seconds")

    return SimulationStatus(
        simulation_id=simulation_id,
        status=sim["status"],
        progress=sim["progress"],
        current_time_seconds=current_time,
        current_temperature_celsius=current_temp,
        message=sim.get("message") or sim.get("error"),
    )


@router.post("/{simulation_id}/abort")
async def abort_simulation(simulation_id: str) -> dict:
    """Abort a running simulation."""
    if simulation_id not in _simulations:
        raise HTTPException(status_code=404, detail="Simulation not found")

    sim = _simulations[simulation_id]

    if sim["status"] not in ("pending", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot abort simulation with status: {sim['status']}",
        )

    runner = sim.get("runner")
    if runner:
        aborted = runner.abort()
        sim["status"] = "aborted"
        sim["error"] = "Simulation aborted by user"

        # Notify WebSocket
        if simulation_id in _websocket_connections:
            try:
                await _websocket_connections[simulation_id].send_json(
                    {
                        "type": "aborted",
                        "message": "Simulation aborted by user",
                    }
                )
            except Exception:
                pass

        logger.info(f"🛑 Simulation {simulation_id} aborted")
        return {"status": "aborted", "message": "Simulation aborted successfully"}
    else:
        raise HTTPException(status_code=400, detail="No runner available to abort")


@router.get("/{simulation_id}/results", response_model=SimulationResults)
async def get_simulation_results(simulation_id: str) -> SimulationResults:
    """Get the results of a completed simulation."""
    if simulation_id not in _simulations:
        raise HTTPException(status_code=404, detail="Simulation not found")

    sim = _simulations[simulation_id]

    if sim["status"] == "failed":
        raise HTTPException(
            status_code=500, detail=sim.get("error", "Simulation failed")
        )

    if sim["status"] != "completed":
        raise HTTPException(status_code=400, detail="Simulation not yet completed")

    results = sim["results"]

    return SimulationResults(
        simulation_id=simulation_id,
        status="completed",
        temperature_history=[
            TemperaturePoint(**point) for point in results["temperature_history"]
        ],
        time_to_target_seconds=results.get("time_to_target_seconds"),
        final_temperature_celsius=results["final_temperature_celsius"],
        total_simulation_time_seconds=results["total_simulation_time_seconds"],
        parameters=SimulationParams(**results["parameters"]),
    )


@router.websocket("/{simulation_id}/ws")
async def simulation_websocket(websocket: WebSocket, simulation_id: str):
    """WebSocket endpoint for real-time simulation updates."""
    await websocket.accept()

    if simulation_id not in _simulations:
        await websocket.send_json({"type": "error", "error": "Simulation not found"})
        await websocket.close()
        return

    _websocket_connections[simulation_id] = websocket

    try:
        # Send current state
        sim = _simulations[simulation_id]
        await websocket.send_json(
            {
                "type": "status",
                "status": sim["status"],
                "progress": sim["progress"],
            }
        )

        # Keep connection alive and wait for completion
        while True:
            try:
                # Wait for messages from client (ping/pong or close)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send keepalive
                await websocket.send_json({"type": "ping"})
            except WebSocketDisconnect:
                break

    finally:
        if simulation_id in _websocket_connections:
            del _websocket_connections[simulation_id]


@router.post("/{simulation_id}/demo")
async def run_demo_simulation(
    simulation_id: str,
    params: Optional[SimulationParams] = None,
) -> SimulationResults:
    """
    Run a demo simulation with pre-computed results.

    This endpoint returns approximate results using Newton's law of cooling
    without requiring the Allsolve SDK. Useful for testing the frontend.
    """
    import math

    logger.info("=" * 60)
    logger.info("⚠️ DEMO MODE - NOT USING QUANSCIENT ALLSOLVE!")
    logger.info("=" * 60)
    logger.info("   This is using Newton's law of cooling approximation.")
    logger.info("   No cloud simulation is being performed.")

    if params is None:
        params = SimulationParams()

    cooling_specs = params.get_cooling_specs()
    container_specs = params.get_container_specs()

    T_initial = params.initial_temp_celsius
    T_ambient = cooling_specs["coolant_temp_celsius"]

    # Calculate time constant
    radius = container_specs["radius"]
    height = container_specs["height"]
    volume = math.pi * radius**2 * height
    surface_area = 2 * math.pi * radius * height + 2 * math.pi * radius**2

    h_eff = cooling_specs["h_submerged"] * params.immersion_level + cooling_specs[
        "h_exposed"
    ] * (1 - params.immersion_level)

    rho_cp = 1000 * 4184
    tau = (rho_cp * volume) / (h_eff * surface_area)

    # Generate temperature curve
    temperature_history = []
    time_to_target = None
    dt = 10  # 10 second intervals

    for t in range(0, params.simulation_duration_minutes * 60 + 1, dt):
        T = T_ambient + (T_initial - T_ambient) * math.exp(-t / tau)
        temperature_history.append(
            TemperaturePoint(time_seconds=float(t), temperature_celsius=T)
        )

        if time_to_target is None and T <= params.target_temp_celsius:
            time_to_target = float(t)

    return SimulationResults(
        simulation_id=simulation_id or str(uuid.uuid4()),
        status="completed",
        temperature_history=temperature_history,
        time_to_target_seconds=time_to_target,
        final_temperature_celsius=temperature_history[-1].temperature_celsius,
        total_simulation_time_seconds=params.simulation_duration_minutes * 60,
        parameters=params,
    )
