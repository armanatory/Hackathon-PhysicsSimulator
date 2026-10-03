"""Authenticated loopback bridge for the public RoomValue Worker.

Run with uvicorn on 127.0.0.1:8004. The bridge cannot select an upstream host,
forward browser credentials, or expose the legacy area/2D endpoints.
"""

from __future__ import annotations

import hmac
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response


UPSTREAM = "http://127.0.0.1:8002"
SECRET_FILE = Path(__file__).resolve().parents[1] / ".runtime" / "cloudflare" / "origin-secret.txt"
MAX_BODY_BYTES = 16 * 1024
_GET_PATHS = {
    "/api/health",
    "/api/room3d/catalog",
    "/api/room3d/minimize/latest",
    "/api/room3d/preview/room",
    "/api/room3d/preview/field",
}
_POST_PATHS = {"/api/room3d/minimize"}
_JOB_PATH = re.compile(r"/api/jobs/([^/]+)(/resume)?\Z")
_SAFE_CONTENT_TYPES = {"application/json", "image/png"}


def _origin_secret() -> str | None:
    configured = os.environ.get("ROOMVALUE_ORIGIN_SECRET")
    if configured is not None:
        return configured.strip() or None
    try:
        return SECRET_FILE.read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeError):
        return None


def _allowed_methods(path: str) -> set[str]:
    if path in _GET_PATHS:
        return {"GET"}
    if path in _POST_PATHS:
        return {"POST"}
    match = _JOB_PATH.fullmatch(path)
    if match is not None:
        job_id, resume = match.groups()
        try:
            if str(UUID(job_id)) != job_id:
                return set()
        except (ValueError, TypeError):
            return set()
        return {"POST" if resume else "GET"}
    return set()


def _upstream_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=UPSTREAM,
        timeout=httpx.Timeout(30.0),
        follow_redirects=False,
        trust_env=False,
    )


@asynccontextmanager
async def lifespan(application: FastAPI):
    async with _upstream_client() as client:
        application.state.upstream = client
        yield


app = FastAPI(
    title="RoomValue origin bridge",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def authenticate_origin(request: Request, call_next):
    expected = _origin_secret()
    if expected is None:
        return JSONResponse(status_code=503, content={"detail": "PC API bridge secret is not configured"})
    provided = request.headers.get("X-RoomValue-Origin-Secret", "")
    if not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        return JSONResponse(status_code=403, content={"detail": "Origin authentication failed"})
    return await call_next(request)


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"],
)
async def forward(request: Request, path: str) -> Response:
    canonical_path = "/" + path
    methods = _allowed_methods(canonical_path)
    if not methods:
        return JSONResponse(status_code=404, content={"detail": "Route not found"})
    if request.method not in methods:
        return JSONResponse(status_code=405, content={"detail": "Method not allowed"}, headers={"Allow": ", ".join(sorted(methods))})
    if request.url.query:
        return JSONResponse(status_code=400, content={"detail": "Query parameters are not supported"})
    length = request.headers.get("content-length")
    if length is not None:
        try:
            announced = int(length)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid request length"})
        if announced < 0:
            return JSONResponse(status_code=400, content={"detail": "Invalid request length"})
        if announced > MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content={"detail": "Request body exceeds 16 KiB"})
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content={"detail": "Request body exceeds 16 KiB"})
        chunks.append(chunk)
    body = b"".join(chunks)
    if request.method == "GET" and body:
        return JSONResponse(status_code=400, content={"detail": "GET request bodies are not supported"})
    headers = {"Accept": "application/json"}
    if request.method == "POST":
        headers["Content-Type"] = "application/json"
    try:
        client = request.app.state.upstream
        outgoing = client.build_request(
            request.method,
            canonical_path,
            headers=headers,
            content=body if request.method == "POST" else None,
        )
        # Also suppress cookies learned from an earlier upstream response and
        # HTTP client's defaults. Host and length are rebuilt by httpx.
        for header in list(outgoing.headers):
            if header not in {"accept", "content-type", "host", "content-length"}:
                del outgoing.headers[header]
        upstream = await client.send(outgoing, follow_redirects=False)
    except httpx.HTTPError:
        return JSONResponse(status_code=503, content={"detail": "PC API offline"})
    content_type = upstream.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in _SAFE_CONTENT_TYPES:
        return JSONResponse(status_code=502, content={"detail": "PC API returned an unsupported response"})
    response_headers = {}
    retry_after = upstream.headers.get("retry-after", "")
    if re.fullmatch(r"[0-9]{1,6}", retry_after):
        response_headers["Retry-After"] = retry_after
    return Response(
        upstream.content,
        status_code=upstream.status_code,
        media_type=content_type,
        headers=response_headers,
    )
