"""Exercise the bridge against an ASGI upstream; no external network traffic."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import cloud_bridge as bridge


class CloudBridgeTests(unittest.TestCase):
    def setUp(self):
        self.secret = "test-origin-secret-not-for-production"
        self.original_origin_secret = bridge._origin_secret
        self.calls = []
        self.response_status = 202
        self.response_headers = {
            "Set-Cookie": "learned=upstream-cookie; Path=/",
            "X-Private": "not-for-public-clients",
            "Retry-After": "10",
        }
        self.response_type = "application/json"
        self.upstream = FastAPI(docs_url=None, openapi_url=None)

        @self.upstream.api_route("/{path:path}", methods=["GET", "POST"])
        async def serve(request: Request, path: str):
            self.calls.append({"method": request.method, "path": "/" + path,
                               "headers": dict(request.headers), "body": await request.body()})
            if self.response_type == "application/json":
                return JSONResponse({"job_id": "upstream-job", "status": "queued"},
                                    status_code=self.response_status, headers=self.response_headers)
            return Response(b"example-content", status_code=self.response_status,
                            media_type=self.response_type, headers=self.response_headers)

        def client_factory():
            return httpx.AsyncClient(base_url=bridge.UPSTREAM,
                                     transport=httpx.ASGITransport(app=self.upstream),
                                     follow_redirects=False, timeout=30, trust_env=False)

        self.patches = [patch.object(bridge, "_upstream_client", side_effect=client_factory),
                        patch.object(bridge, "_origin_secret", return_value=self.secret)]
        for item in self.patches:
            item.start()
        self.client_context = TestClient(bridge.app)
        self.client = self.client_context.__enter__()
        self.headers = {"X-RoomValue-Origin-Secret": self.secret}

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        for item in reversed(self.patches):
            item.stop()

    def test_secret_must_be_configured_and_matches_constant_time(self):
        self.assertEqual(self.client.get("/api/health").status_code, 403)
        self.assertEqual(self.client.get("/api/health", headers={"X-RoomValue-Origin-Secret": "wrong"}).status_code, 403)
        with patch.object(bridge, "_origin_secret", return_value=None):
            self.assertEqual(self.client.get("/api/health", headers=self.headers).status_code, 503)
        self.assertEqual(self.calls, [])
        with patch.object(bridge.hmac, "compare_digest", wraps=bridge.hmac.compare_digest) as compare:
            self.assertEqual(self.client.get("/api/health", headers=self.headers).status_code, 202)
            compare.assert_called_once_with(self.secret.encode(), self.secret.encode())

    def test_secret_file_fallback_env_precedence_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "origin-secret.txt"
            path.write_text("file-secret\n", encoding="utf-8")
            original = self.original_origin_secret
            with patch.object(bridge, "SECRET_FILE", path), patch.dict(bridge.os.environ, {}, clear=True):
                self.assertEqual(original(), "file-secret")
                with patch.dict(bridge.os.environ, {"ROOMVALUE_ORIGIN_SECRET": "env-secret"}):
                    self.assertEqual(original(), "env-secret")
                with patch.dict(bridge.os.environ, {"ROOMVALUE_ORIGIN_SECRET": ""}):
                    self.assertIsNone(original())
            with patch.object(bridge, "SECRET_FILE", path / "missing"), patch.dict(bridge.os.environ, {}, clear=True):
                self.assertIsNone(original())

    def test_exact_get_and_post_allowlist_with_uuid_job_routes(self):
        job_id = str(uuid4())
        get_paths = ["/api/health", "/api/room3d/catalog", "/api/room3d/minimize/latest",
                     "/api/room3d/preview/room", "/api/room3d/preview/field", f"/api/jobs/{job_id}"]
        post_paths = ["/api/room3d/minimize", f"/api/jobs/{job_id}/resume"]
        for path in get_paths:
            self.assertEqual(self.client.get(path, headers=self.headers).status_code, 202)
        for path in post_paths:
            self.assertEqual(self.client.post(path, headers=self.headers, json={}).status_code, 202)
        self.assertEqual([call["path"] for call in self.calls], get_paths + post_paths)

    def test_legacy_unknown_and_docs_routes_are_not_forwarded(self):
        for path in ("/docs", "/openapi.json", "/redoc", "/api/compare", "/api/room3d/optimize",
                     "/api/room3d/latest", "/api/jobs/not-a-uuid", "/api/jobs/../../secrets", "/api/room3d/catalog/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, headers=self.headers).status_code, 404)
        self.assertEqual(self.calls, [])

    def test_wrong_methods_and_queries_are_rejected_before_upstream(self):
        self.assertEqual(self.client.post("/api/room3d/catalog", headers=self.headers, json={}).status_code, 405)
        self.assertEqual(self.client.get("/api/room3d/minimize", headers=self.headers).status_code, 405)
        self.assertEqual(self.client.delete("/api/health", headers=self.headers).status_code, 405)
        self.assertEqual(self.client.get("/api/health?upstream=https://elsewhere.example", headers=self.headers).status_code, 400)
        self.assertEqual(self.calls, [])

    def test_headers_are_rebuilt_and_upstream_headers_do_not_escape(self):
        headers = {**self.headers, "Cookie": "browser=session", "Authorization": "Bearer browser-key",
                   "X-Forwarded-For": "1.2.3.4", "Forwarded": "for=1.2.3.4", "X-Custom": "browser",
                   "Accept": "text/html", "Content-Type": "text/plain", "Host": "untrusted.example"}
        response = self.client.post("/api/room3d/minimize", headers=headers, content=b'{"max_panels":0}')
        self.assertEqual(response.status_code, 202)
        sent = self.calls[-1]
        self.assertEqual(sent["body"], b'{"max_panels":0}')
        self.assertEqual(sent["headers"]["accept"], "application/json")
        self.assertEqual(sent["headers"]["content-type"], "application/json")
        self.assertEqual(sent["headers"]["host"], "127.0.0.1:8002")
        self.assertLessEqual(set(sent["headers"]), {"host", "accept", "content-type", "content-length"})
        self.assertEqual(response.headers["retry-after"], "10")
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertNotIn("set-cookie", response.headers)
        self.assertNotIn("x-private", response.headers)
        # The shared HTTP client's cookie jar must not send an upstream cookie
        # learned from the first request on a later request.
        self.client.get("/api/health", headers=self.headers)
        self.assertNotIn("cookie", self.calls[-1]["headers"])

    def test_announced_and_streamed_body_size_limits(self):
        exact = b"a" * bridge.MAX_BODY_BYTES
        self.assertEqual(self.client.post("/api/room3d/minimize", headers=self.headers, content=exact).status_code, 202)
        self.assertEqual(len(self.calls), 1)
        too_large = b"a" * (bridge.MAX_BODY_BYTES + 1)
        self.assertEqual(self.client.post("/api/room3d/minimize", headers=self.headers, content=too_large).status_code, 413)

        def chunks():
            yield b"a" * 8192
            yield b"b" * 8193

        self.assertEqual(self.client.post("/api/room3d/minimize", headers=self.headers, content=chunks()).status_code, 413)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.client.request("GET", "/api/health", headers=self.headers, content=b"unexpected").status_code, 400)

    def test_safe_content_type_and_retry_after_only(self):
        self.response_status = 200
        self.response_type = "image/png"
        image = self.client.get("/api/room3d/preview/room", headers=self.headers)
        self.assertEqual(image.headers["content-type"], "image/png")
        self.assertEqual(image.content, b"example-content")
        self.response_type = "text/html"
        unsupported = self.client.get("/api/health", headers=self.headers)
        self.assertEqual(unsupported.status_code, 502)
        self.assertNotIn(b"example-content", unsupported.content)
        self.response_type = "application/json"
        self.response_headers["Retry-After"] = "Wed, 01 Jan 2030 00:00:00 GMT"
        self.assertNotIn("retry-after", self.client.get("/api/health", headers=self.headers).headers)

    def test_unreachable_upstream_is_json_503_without_exception_text(self):
        async def unavailable(*_args, **_kwargs):
            raise httpx.ConnectError("private diagnostic text")

        with patch.object(bridge.app.state.upstream, "send", side_effect=unavailable):
            response = self.client.get("/api/health", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "PC API offline"})
        self.assertNotIn("private", response.text)


if __name__ == "__main__":
    unittest.main()
