"""Inspect the requested Cloudflare zone using the existing Wrangler login.

Credentials remain in memory and are never printed or written into this case.
"""
from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ACCOUNT = "6e68f6567ea557e526a0a258c03b3734"
DOMAIN = "santerihukari.com"


def token():
    if os.environ.get("CLOUDFLARE_API_TOKEN"):
        return os.environ["CLOUDFLARE_API_TOKEN"]
    config = Path(os.environ["APPDATA"]) / "xdg.config" / ".wrangler" / "config" / "default.toml"
    return tomllib.loads(config.read_text(encoding="utf-8"))["oauth_token"]


def api(path, method="GET", data=None):
    request = Request("https://api.cloudflare.com/client/v4"+path,
                      headers={"Authorization": "Bearer "+token(), "Content-Type": "application/json"},
                      method=method, data=json.dumps(data).encode() if data is not None else None)
    try:
        with urlopen(request, timeout=30) as response:
            return {"status": response.status, **json.load(response)}
    except HTTPError as error:
        # Never include headers, token-bearing URLs or raw SDK exception text.
        try:
            payload = json.load(error)
        except (ValueError, OSError):
            payload = {}
        return {"status": error.code, "success": False,
                "error_codes": [item.get("code") for item in payload.get("errors", [])]}


def main():
    zones = api("/zones?"+urlencode({"name": DOMAIN}))
    selected = [{"id": zone["id"], "name": zone["name"], "status": zone["status"],
                 "account_id": zone["account"]["id"]} for zone in zones.get("result", [])]
    print(json.dumps({"zones_status": zones["status"], "zones": selected}), flush=True)
    if not selected:
        return
    zone_id = selected[0]["id"]
    for hostname in ("roomvalue."+DOMAIN, "roomvalue-origin."+DOMAIN):
        dns = api(f"/zones/{zone_id}/dns_records?"+urlencode({"name": hostname}))
        print(json.dumps({"dns_name": hostname, "status": dns["status"],
                          "records": [{"id": record["id"], "type": record["type"], "name": record["name"]}
                                      for record in dns.get("result", [])]}), flush=True)
    for resource in ("workers/scripts", "cfd_tunnel", "access/apps", "subscriptions"):
        response = api(f"/accounts/{ACCOUNT}/{resource}")
        print(json.dumps({"resource": resource, "status": response["status"],
                          "items": [{"id": item.get("id"), "name": item.get("name"),
                                     "status": item.get("status"), "domain": item.get("domain"),
                                     "product": item.get("rate_plan", {}).get("public_name")}
                                    for item in response.get("result", [])],
                          "error_codes": response.get("error_codes", [])}), flush=True)


if __name__ == "__main__":
    main()
