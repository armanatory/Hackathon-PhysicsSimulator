"""
Allquiet API

A FastAPI application that searches for the best placement of a few acoustic screens
in an open-plan office, using Allsolve harmonic acoustic simulations through the SDK.
"""

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .allsolve import ALLSOLVE_AVAILABLE
from .config import get_settings
from .routers import optimization_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

settings = get_settings()

logger.info("=" * 60)
logger.info("QUIETOFFICE BACKEND STARTING")
logger.info("=" * 60)
logger.info(f"   Allsolve host: {settings.qs_host}")
logger.info(f"   Allsolve SDK installed: {'yes' if ALLSOLVE_AVAILABLE else 'no'}")
logger.info(f"   API key configured: {'yes' if settings.has_credentials else 'no'}")

app = FastAPI(
    title="Allquiet API",
    description="""
    Put acoustic treatment where physics says it matters.

    Given an office layout, a conversation and a few acoustic screens, this API runs
    Allsolve acoustic simulations for many screen layouts and returns the one that
    lowers the speech level at the desks the most.

    ## Physics model

    2D harmonic acoustic waves (Helmholtz equation) in the air of the room:

    **∇²p + (ω/c)² p = 0**

    - the talker is a small pulsating disk (normal acceleration)
    - screens are sound-hard obstacles
    - outer walls are absorbing boundaries
    """,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(optimization_router)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
        "endpoints": {
            "default_office": "GET /api/office/default",
            "capabilities": "GET /api/capabilities",
            "start_optimization": "POST /api/optimization/start",
            "get_status": "GET /api/optimization/{id}/status",
            "get_results": "GET /api/optimization/{id}/results",
            "get_log": "GET /api/optimization/{id}/log",
            "explain": "POST /api/explain",
            "abort": "POST /api/optimization/{id}/abort",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
