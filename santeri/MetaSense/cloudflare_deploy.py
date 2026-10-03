"""Provision the requested MetaSense deployment using the existing Wrangler login.

Credentials stay in private files or memory. No root/other-case configuration is
modified, and the public hostname is a new subdomain rather than the apex site.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import tomllib
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / ".runtime" / "cloudflare"
STATE = PRIVATE / "deployment.json"
DOMAIN = "santerihukari.com"
HOSTNAME = "metasense." + DOMAIN
ACCOUNT = "6e68f6567ea557e526a0a258c03b3734"
WORKER = "metasense"


def token() -> str:
    configured = os.environ.get("CLOUDFLARE_API_TOKEN")
    if configured:
        return configured
    config = Path(os.environ["APPDATA"]) / "xdg.config" / ".wrangler" / "config" / "default.toml"
    return tomllib.loads(config.read_text(encoding="utf-8"))["oauth_token"]


def api(path: str, method: str = "GET", payload=None):
    request = Request(
        "https://api.cloudflare.com/client/v4" + path,
        headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json"},
        method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = json.load(response)
            if not body.get("success"):
                raise RuntimeError(f"Cloudflare operation failed: {path}; HTTP {response.status}")
            return body.get("result")
    except HTTPError as error:
        try:
            body = json.load(error)
            codes = [item.get("code") for item in body.get("errors", [])]
        except (ValueError, OSError):
            codes = []
        raise RuntimeError(f"Cloudflare {method} {path} returned HTTP {error.code}; codes {codes}") from None


def save(state: dict) -> None:
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, STATE)


def zone():
    zones = api("/zones?" + urlencode({"name": DOMAIN}))
    matched = [z for z in zones if z["name"] == DOMAIN and z["account"]["id"] == ACCOUNT and z["status"] == "active"]
    if len(matched) != 1:
        raise RuntimeError("The requested active zone is not available in the configured account")
    return matched[0]


def inspect() -> None:
    selected = zone()
    domains = api(f"/accounts/{ACCOUNT}/workers/domains")
    tunnels = api(f"/accounts/{ACCOUNT}/cfd_tunnel?is_deleted=false")
    services = api(f"/accounts/{ACCOUNT}/connectivity/directory/services")
    workers = api(f"/accounts/{ACCOUNT}/workers/scripts")
    print(json.dumps({
        "zone": selected["name"], "zone_id": selected["id"], "account_id": ACCOUNT,
        "hostname": HOSTNAME,
        "matching_worker_domains": [{"id": r["id"], "hostname": r["hostname"], "service": r.get("service")} for r in domains if r["hostname"] == HOSTNAME],
        "matching_tunnels": [{"id": t["id"], "name": t["name"]} for t in tunnels if t["name"] == "metasense-pc"],
        "matching_services": [{"id": s["service_id"], "name": s["name"]} for s in services if s["name"] == "metasense-api"],
        "matching_workers": [w["id"] for w in workers if w["id"] == WORKER],
    }), flush=True)


def provision() -> None:
    selected = zone()
    PRIVATE.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {
        "account_id": ACCOUNT, "zone_id": selected["id"], "hostname": HOSTNAME,
        "worker": WORKER, "bridge_port": 8005, "api_port": 8001,
    }
    if state.get("hostname") != HOSTNAME or state.get("account_id") != ACCOUNT:
        raise RuntimeError("Saved deployment does not belong to this MetaSense hostname/account")
    if not STATE.exists():
        domains = api(f"/accounts/{ACCOUNT}/workers/domains")
        workers = api(f"/accounts/{ACCOUNT}/workers/scripts")
        try:
            socket.getaddrinfo(HOSTNAME, 443)
            hostname_exists = True
        except socket.gaierror as error:
            if error.errno not in (socket.EAI_NONAME, 11001):
                raise RuntimeError("Could not check target hostname availability") from None
            hostname_exists = False
        if hostname_exists or any(d["hostname"] == HOSTNAME for d in domains) or any(w["id"] == WORKER for w in workers):
            raise RuntimeError("MetaSense hostname or Worker already exists without local deployment ownership")
        save(state)
    secret_file = PRIVATE / "origin-secret.txt"
    if not secret_file.exists():
        secret_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    if not state.get("tunnel_id"):
        tunnels = api(f"/accounts/{ACCOUNT}/cfd_tunnel?is_deleted=false")
        if any(t["name"] == "metasense-pc" for t in tunnels):
            raise RuntimeError("A metasense-pc tunnel exists without a saved ownership ID")
        created = api(f"/accounts/{ACCOUNT}/cfd_tunnel", "POST", {"name": "metasense-pc", "config_src": "cloudflare"})
        state["tunnel_id"] = created["id"]
        save(state)
    tunnel_id = state["tunnel_id"]
    api(f"/accounts/{ACCOUNT}/cfd_tunnel/{tunnel_id}/configurations", "PUT", {
        "config": {"ingress": [{"service": "http_status:404"}], "warp-routing": {"enabled": True}},
    })
    connector_token = api(f"/accounts/{ACCOUNT}/cfd_tunnel/{tunnel_id}/token")
    (PRIVATE / "tunnel-token.txt").write_text(connector_token, encoding="utf-8")
    if not state.get("service_id"):
        services = api(f"/accounts/{ACCOUNT}/connectivity/directory/services")
        existing = [s for s in services if s["name"] == "metasense-api"]
        if existing:
            if len(existing) != 1 or existing[0].get("type") != "http" or existing[0].get("http_port") != 8005 or existing[0].get("host", {}).get("ipv4") != "127.0.0.1" or existing[0].get("host", {}).get("network", {}).get("tunnel_id") != tunnel_id:
                raise RuntimeError("Existing metasense-api service does not match this deployment's owned tunnel and port")
            service = existing[0]
        else:
            service = api(f"/accounts/{ACCOUNT}/connectivity/directory/services", "POST", {
                "name": "metasense-api", "type": "http", "http_port": 8005,
                "host": {"ipv4": "127.0.0.1", "network": {"tunnel_id": tunnel_id}},
            })
        state["service_id"] = service["service_id"]
        save(state)
    config = {
        "$schema": "./node_modules/wrangler/config-schema.json", "name": WORKER,
        "main": "src/index.js", "compatibility_date": "2026-10-03",
        "workers_dev": False, "preview_urls": False, "account_id": ACCOUNT,
        "routes": [{"pattern": HOSTNAME, "custom_domain": True}],
        "assets": {"directory": "../frontend/dist", "binding": "ASSETS",
                   "not_found_handling": "single-page-application", "run_worker_first": ["/api", "/api/*"]},
        "vars": {"METASENSE_ALLOW_RUNS": "true"},
        "vpc_services": [{"binding": "METASENSE_API", "service_id": state["service_id"], "remote": True}],
    }
    (ROOT / "cloudflare" / "wrangler.jsonc").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**state, "credentials_saved_privately": True, "public_backend_hostname": False}), flush=True)


def upload_secret() -> None:
    value = (PRIVATE / "origin-secret.txt").read_text(encoding="utf-8").strip()
    api(f"/accounts/{ACCOUNT}/workers/scripts/{WORKER}/secrets", "PUT", {
        "name": "METASENSE_ORIGIN_SECRET", "text": value, "type": "secret_text",
    })
    print(json.dumps({"worker": WORKER, "origin_secret_uploaded": True}), flush=True)


def snapshot() -> None:
    with urlopen("http://127.0.0.1:8001/api/optimization/config", timeout=5) as response:
        config = json.load(response)
    with urlopen("http://127.0.0.1:8001/api/optimization/jobs/latest", timeout=5) as response:
        job = json.load(response)
    if not job or job.get("status") != "completed" or job.get("synthetic") is not False:
        raise RuntimeError("Only a completed real Allsolve job may become the public saved example")
    report = job.get("report", {})
    winner = report.get("best_design", {})
    if report.get("synthetic") is not False or winner.get("validated") is not True or winner.get("verification", {}).get("passed") is not True:
        raise RuntimeError("The public saved example must retain a verified numerical winner")
    # Public provenance includes cloud identifiers and hashes, not host filesystem paths.
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in {"path", "log_path", "worker_pid", "process_signature"}}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    destination = ROOT / "frontend" / "dist" / "deployment"
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in (("config.json", config), ("latest-job.json", clean(job))):
        (destination / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"saved_example": job["id"], "verified": True, "files": ["config.json", "latest-job.json"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["inspect", "provision", "upload-secret", "snapshot"])
    args = parser.parse_args()
    {"inspect": inspect, "provision": provision, "upload-secret": upload_secret, "snapshot": snapshot}[args.action]()
