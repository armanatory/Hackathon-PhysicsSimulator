"""Provision this case's private PC connector; no public API DNS is created."""
from __future__ import annotations

import json
import secrets
from pathlib import Path

from cloudflare_inspect import ACCOUNT, DOMAIN, api

HERE = Path(__file__).resolve().parent / ".runtime" / "cloudflare"
STATE = HERE / "deployment.json"


def require(response, action):
    if not response.get("success"):
        raise RuntimeError(f"Cloudflare {action} returned HTTP {response['status']}; codes {response.get('error_codes', [])}")
    return response["result"]


def save(state):
    STATE.write_text(json.dumps(state, indent=2)+"\n", encoding="utf-8")


def main():
    HERE.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {"account_id": ACCOUNT, "hostname": "roomvalue."+DOMAIN}
    if not (HERE / "origin-secret.txt").exists():
        (HERE / "origin-secret.txt").write_text(secrets.token_urlsafe(48), encoding="utf-8")
    if not state.get("tunnel_id"):
        tunnels = require(api(f"/accounts/{ACCOUNT}/cfd_tunnel"), "list tunnels")
        if any(tunnel.get("name") == "roomvalue-pc" and not tunnel.get("deleted_at") for tunnel in tunnels):
            raise RuntimeError("A roomvalue-pc tunnel already exists without local ownership state; inspect before reusing")
        tunnel = require(api(f"/accounts/{ACCOUNT}/cfd_tunnel", "POST", {
            "name": "roomvalue-pc", "config_src": "cloudflare"
        }), "create private tunnel")
        state["tunnel_id"] = tunnel["id"]
        save(state)
    tunnel_id = state["tunnel_id"]
    require(api(f"/accounts/{ACCOUNT}/cfd_tunnel/{tunnel_id}/configurations", "PUT", {
        "config": {"ingress": [{"service": "http_status:404"}], "warp-routing": {"enabled": True}}
    }), "configure private tunnel")
    tunnel_token = require(api(f"/accounts/{ACCOUNT}/cfd_tunnel/{tunnel_id}/token"), "read connector token")
    (HERE / "tunnel-token.txt").write_text(tunnel_token, encoding="utf-8")
    print(json.dumps({"tunnel_id": tunnel_id, "hostname": state["hostname"],
                      "credentials_saved_privately": True, "public_api_hostname": False}), flush=True)


if __name__ == "__main__":
    main()
