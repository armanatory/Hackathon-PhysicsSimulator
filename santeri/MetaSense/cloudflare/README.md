# MetaSense deployment

Public app: https://metasense.santerihukari.com/

Cloudflare Workers serves the production React assets and a narrow API gateway.
The `METASENSE_API` VPC binding connects through this case's private QUIC tunnel
to `127.0.0.1:8005`. The authenticated bridge forwards to the Python API on
`127.0.0.1:8001`; Python submits and monitors the real Allsolve jobs. The PC must
stay awake and connected for new optimization runs. The verified saved result
remains on Cloudflare when the PC is offline.

Anyone visiting the app may launch a run, as requested by the user. The API
validates input bounds and permits one active optimization at a time. The
Worker admission setting `METASENSE_ALLOW_RUNS` can disable new submissions.
This setting and same-origin checks are not user authentication.

Allsolve credentials remain in the private Python environment. The bridge
secret and tunnel token are kept under the ignored `.runtime/cloudflare/`
directory. The origin secret is also a Cloudflare Worker secret. Neither is
included in public assets, response headers, or browser storage. No public
backend hostname or inbound port is configured.

## Start after reboot

From the MetaSense directory:

```powershell
.\start-cloud.ps1
```

This checks ownership of the reserved ports and starts missing API, bridge,
and tunnel processes in hidden windows. It does not launch an optimization.
Automatic Windows startup is not configured.

## Publish updates

Build the frontend, export a completed verified result, then deploy:

```powershell
Push-Location frontend
pnpm build
Pop-Location
.\.venv\Scripts\python.exe cloudflare_deploy.py snapshot
Push-Location cloudflare
pnpm dlx wrangler@4.147.0 deploy --config wrangler.jsonc
Pop-Location
```

The snapshot exporter refuses an unfinished, synthetic, or unverified result.
Offline responses explicitly set `offline=true` and `snapshot=true`, preserve
the saved run's timestamp and provenance, and disable optimization. An unknown
job or new POST never receives the saved example as a replacement.

Provisioning uses the existing Wrangler login:

```powershell
.\.venv\Scripts\python.exe cloudflare_deploy.py inspect
.\.venv\Scripts\python.exe cloudflare_deploy.py provision
.\.venv\Scripts\python.exe cloudflare_deploy.py upload-secret
```

The saved deployment identifies only this case's hostname, tunnel, and service.
It does not modify the apex site or other case deployments.

## Validation

Worker tests: `node --test test/*.test.js` from this directory. Bridge tests:
`..\.venv\Scripts\python.exe -m pytest tests/test_cloud_bridge.py -q` from
`backend`. Production endpoint checks are recorded in
`deployment-validation.json`; the hosted screenshot is `hosted-app.jpg`.

Configuration follows Cloudflare's [custom domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/),
[static assets](https://developers.cloudflare.com/workers/static-assets/), and
[VPC Services](https://developers.cloudflare.com/workers-vpc/configuration/vpc-services/).
