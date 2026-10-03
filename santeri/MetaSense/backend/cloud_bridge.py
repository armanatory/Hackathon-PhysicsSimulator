"""Authenticated loopback-only bridge for the public MetaSense Worker.

The upstream is fixed. Only current real-optimization routes and read-only
validation can cross this boundary; browser cookies and secrets stay outside.
"""
from __future__ import annotations

import hmac
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response


UPSTREAM = "http://127.0.0.1:8001"
SECRET_FILE = Path(__file__).resolve().parents[1] / ".runtime" / "cloudflare" / "origin-secret.txt"
MAX_BODY_BYTES = 32 * 1024
_GET_PATHS = {
    "/api/health", "/api/optimization/config", "/api/optimization/jobs/latest",
    "/api/validation/slab",
}
_POST_PATHS = {"/api/optimization/jobs"}
_JOB_PATH = re.compile(r"/api/optimization/jobs/[0-9a-f]{32}\Z")


def _origin_secret() -> str | None:
    # Only the file path may come from environment; never a secret value in argv.
    path = Path(os.environ.get("METASENSE_ORIGIN_SECRET_FILE", str(SECRET_FILE)))
    try:
        secret = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError, ValueError):
        return None
    return secret if 32 <= len(secret) <= 512 and secret.isascii() and secret.isprintable() else None


def _allowed_methods(path: str) -> set[str]:
    if path in _GET_PATHS or _JOB_PATH.fullmatch(path):
        return {"GET"}
    if path in _POST_PATHS:
        return {"POST"}
    return set()


def _upstream_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=UPSTREAM, timeout=httpx.Timeout(connect=3, read=30, write=10, pool=5),
        follow_redirects=False, trust_env=False,
    )


@asynccontextmanager
async def lifespan(application: FastAPI):
    async with _upstream_client() as client:
        application.state.upstream = client
        yield


app = FastAPI(title="MetaSense origin bridge", docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=lifespan)


@app.middleware("http")
async def authenticate_origin(request: Request, call_next):
    expected = _origin_secret()
    if expected is None:
        return JSONResponse(status_code=503, content={"detail": "Origin bridge secret is not configured"})
    supplied = request.headers.getlist("X-MetaSense-Origin-Secret")
    if (len(supplied) != 1
            or not hmac.compare_digest(supplied[0].encode("utf-8"), expected.encode("utf-8"))):
        return JSONResponse(status_code=403, content={"detail": "Origin authentication failed"})
    return await call_next(request)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"])
async def forward(request: Request, path: str) -> Response:
    canonical_path = "/" + path
    methods = _allowed_methods(canonical_path)
    if not methods:
        return JSONResponse(status_code=404, content={"detail": "Route not found"})
    if request.method not in methods:
        return JSONResponse(status_code=405, content={"detail": "Method not allowed"},
                            headers={"Allow": ", ".join(sorted(methods))})
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
            return JSONResponse(status_code=413, content={"detail": "Request body exceeds 32 KiB"})
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content={"detail": "Request body exceeds 32 KiB"})
        chunks.append(chunk)
    body = b"".join(chunks)
    if request.method == "GET" and body:
        return JSONResponse(status_code=400, content={"detail": "GET request bodies are not supported"})
    headers = {"Accept": "application/json"}
    if request.method == "POST":
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return JSONResponse(status_code=415, content={"detail": "Optimization requests require JSON"})
        headers["Content-Type"] = "application/json"
    try:
        outgoing = request.app.state.upstream.build_request(
            request.method, canonical_path, headers=headers,
            content=body if request.method == "POST" else None,
        )
        # Suppress browser credentials, the origin secret, and cookies/defaults
        # learned by the upstream client. Host/length are rebuilt by httpx.
        for header in list(outgoing.headers):
            if header not in {"accept", "content-type", "host", "content-length"}:
                del outgoing.headers[header]
        upstream = await request.app.state.upstream.send(outgoing, follow_redirects=False)
    except httpx.HTTPError:
        return JSONResponse(status_code=503, content={"detail": "MetaSense API offline"})
    content_type = upstream.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return JSONResponse(status_code=502, content={"detail": "MetaSense API returned an unsupported response"})
    response_headers = {}
    retry_after = upstream.headers.get("retry-after", "")
    if re.fullmatch(r"[0-9]{1,6}", retry_after):
        response_headers["Retry-After"] = retry_after
    return Response(upstream.content, status_code=upstream.status_code,
                    media_type="application/json", headers=response_headers)
