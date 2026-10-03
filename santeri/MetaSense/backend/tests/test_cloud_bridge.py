"""Protected-origin proxy tests with a local HTTP mock; no optimization launches."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import cloud_bridge


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    secret = "fixture-origin-secret-" + "a" * 48
    secret_file = tmp_path / "origin-secret.txt"
    secret_file.write_text(secret + "\n", encoding="utf-8")
    monkeypatch.setenv("METASENSE_ORIGIN_SECRET_FILE", str(secret_file))
    calls = []
    reply = {"status": 200, "headers": {"Content-Type": "application/json"}, "body": b'{"status":"ok"}'}

    def upstream(request):
        calls.append(request)
        return httpx.Response(reply["status"], headers=reply["headers"], content=reply["body"])

    monkeypatch.setattr(cloud_bridge, "_upstream_client", lambda: httpx.AsyncClient(
        base_url=cloud_bridge.UPSTREAM, transport=httpx.MockTransport(upstream),
        trust_env=False, follow_redirects=False,
    ))
    with TestClient(cloud_bridge.app) as client:
        yield client, {"X-MetaSense-Origin-Secret": secret}, calls, reply


def test_unsigned_wrong_and_duplicated_secrets_never_reach_api(bridge):
    client, headers, calls, _ = bridge
    assert client.get("/api/health").status_code == 403
    assert client.get("/api/health", headers={"X-MetaSense-Origin-Secret": "wrong"}).status_code == 403
    duplicates = [("X-MetaSense-Origin-Secret", headers["X-MetaSense-Origin-Secret"])] * 2
    assert client.get("/api/health", headers=duplicates).status_code == 403
    assert calls == []


def test_missing_secret_file_fails_closed(bridge, monkeypatch, tmp_path):
    client, headers, calls, _ = bridge
    monkeypatch.setenv("METASENSE_ORIGIN_SECRET_FILE", str(tmp_path / "missing.txt"))
    assert client.get("/api/health", headers=headers).status_code == 503
    assert calls == []


@pytest.mark.parametrize("path", ["/api/health", "/api/optimization/config", "/api/optimization/jobs/latest",
                                  "/api/optimization/jobs/" + "a" * 32, "/api/validation/slab"])
def test_signed_allowed_get_uses_fixed_upstream_without_browser_credentials(bridge, path):
    client, headers, calls, _ = bridge
    response = client.get(path, headers={**headers, "Cookie": "browser-cookie=private",
                                        "Authorization": "Bearer browser-token", "X-Forwarded-Host": "attacker.test"})
    assert response.status_code == 200
    assert str(calls[0].url) == cloud_bridge.UPSTREAM + path
    assert set(calls[0].headers) <= {"accept", "content-type", "host", "content-length"}
    assert "x-metasense-origin-secret" not in calls[0].headers


def test_signed_post_forwards_json_and_preserves_durable_job_202(bridge):
    client, headers, calls, reply = bridge
    reply.update(status=202, body=b'{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","status":"queued"}')
    payload = {"candidate_count": 1, "seed": 42}
    response = client.post("/api/optimization/jobs", headers=headers, json=payload)
    assert response.status_code == 202 and response.json()["status"] == "queued"
    assert calls[0].method == "POST"
    assert json.loads(calls[0].content) == payload
    assert calls[0].headers["Content-Type"] == "application/json"


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/api/jobs",
                                  "/api/jobs/" + "a" * 32, "/api/optimization/jobs/" + "A" * 32,
                                  "/api/optimization/jobs/not-a-job", "/api/optimization/jobs/" + "a" * 32 + "/resume"])
def test_docs_legacy_and_malformed_routes_are_not_exposed(bridge, path):
    client, headers, calls, _ = bridge
    assert client.get(path, headers=headers).status_code == 404
    assert calls == []


def test_methods_query_strings_and_get_bodies_are_rejected(bridge):
    client, headers, calls, _ = bridge
    response = client.post("/api/health", headers=headers, json={})
    assert response.status_code == 405 and response.headers["Allow"] == "GET"
    assert client.get("/api/optimization/jobs", headers=headers).status_code == 405
    assert client.get("/api/health?upstream=https://attacker.test", headers=headers).status_code == 400
    assert client.request("GET", "/api/health", headers=headers, content=b"unexpected").status_code == 400
    assert calls == []


@pytest.mark.parametrize("length", ["not-an-integer", "-1"])
def test_invalid_announced_body_lengths_are_rejected(bridge, length):
    client, headers, calls, _ = bridge
    response = client.post("/api/optimization/jobs", headers={**headers, "Content-Type": "application/json",
                                                           "Content-Length": length}, content=b"{}")
    assert response.status_code == 400
    assert calls == []


def test_body_limit_is_enforced_for_announced_and_streamed_lengths(bridge):
    client, headers, calls, _ = bridge
    body = b"x" * (cloud_bridge.MAX_BODY_BYTES + 1)
    assert client.post("/api/optimization/jobs", headers={**headers, "Content-Type": "application/json"}, content=body).status_code == 413
    assert client.post("/api/optimization/jobs", headers={**headers, "Content-Type": "application/json", "Content-Length": "0"}, content=body).status_code == 413
    assert calls == []


def test_post_requires_json_content_type(bridge):
    client, headers, calls, _ = bridge
    assert client.post("/api/optimization/jobs", headers=headers, content=b"{}").status_code == 415
    assert calls == []


def test_response_cookies_locations_and_untrusted_headers_are_not_forwarded(bridge):
    client, headers, _, reply = bridge
    reply["headers"].update({"Set-Cookie": "api-session=private", "Location": "https://attacker.test/",
                             "X-Private": "internal", "Retry-After": "15"})
    response = client.get("/api/health", headers=headers)
    assert response.headers["Retry-After"] == "15"
    assert not ({"set-cookie", "location", "x-private"} & set(response.headers))
    response = client.get("/api/health", headers=headers)
    assert response.status_code == 200


def test_client_cookies_learned_upstream_do_not_reenter_the_api(bridge):
    client, headers, calls, reply = bridge
    reply["headers"]["Set-Cookie"] = "api-session=private; Path=/"
    client.get("/api/health", headers=headers)
    client.get("/api/health", headers=headers)
    assert all("cookie" not in request.headers for request in calls)


def test_html_upstream_response_and_connection_error_fail_with_generic_errors(bridge, monkeypatch):
    client, headers, _, reply = bridge
    reply["headers"]["Content-Type"] = "text/html"
    reply["body"] = b"<html>Private upstream detail</html>"
    response = client.get("/api/health", headers=headers)
    assert response.status_code == 502 and "Private" not in response.text

    async def disconnected(*_, **__):
        raise httpx.ConnectError("Private network details")

    monkeypatch.setattr(cloud_bridge.app.state.upstream, "send", disconnected)
    response = client.get("/api/health", headers=headers)
    assert response.status_code == 503 and "Private" not in response.text
