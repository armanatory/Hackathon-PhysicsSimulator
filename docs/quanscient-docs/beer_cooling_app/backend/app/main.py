"""
Beer Cooling Simulation API

A FastAPI application that provides endpoints for running thermal simulations
of beer cooling using the Allsolve SDK.
"""

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import simulation_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

settings = get_settings()

logger.info("=" * 60)
logger.info("🍺 BEER COOLING SIMULATOR BACKEND STARTING")
logger.info("=" * 60)
logger.info(f"   Allsolve Host: {settings.qs_host}")
logger.info(f"   API Key configured: {'✅ Yes' if settings.qs_access_key else '❌ No'}")
logger.info(f"   Debug mode: {settings.debug}")

app = FastAPI(
    title="Beer Cooling Simulator API",
    description="""
    🍺 Simulate how quickly your beer cools down in different environments!

    This API provides endpoints to:
    - Start thermal simulations of beer cooling
    - Monitor simulation progress in real-time
    - Retrieve temperature vs time results

    ## Physics Model

    The simulation solves the transient heat conduction equation:

    **ρ Cₚ ∂T/∂t = ∇ · (k ∇T)**

    With convective boundary conditions:

    **q = h (T_surface - T_coolant)**

    Where:
    - h = 600 W/(m²·K) for ice water immersion
    - h = 10 W/(m²·K) for air exposure
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(simulation_router)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "description": "Beer Cooling Simulation API",
        "docs": "/docs",
        "endpoints": {
            "start_simulation": "POST /api/simulation/start",
            "get_status": "GET /api/simulation/{id}/status",
            "get_results": "GET /api/simulation/{id}/results",
            "demo": "POST /api/simulation/{id}/demo",
            "websocket": "WS /api/simulation/{id}/ws",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
