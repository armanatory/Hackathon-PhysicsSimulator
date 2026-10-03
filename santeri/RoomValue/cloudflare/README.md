# RoomValue on Cloudflare Workers

This Worker serves the built React app and forwards only the current 3D website's API routes to its Python simulation service through a private Workers VPC binding. The local Python service submits the actual finite-element jobs to Allsolve's cloud and retains persistent jobs and large cached fields. The Worker contains no Allsolve credentials and does not run Python simulations.

The configured custom domain is `roomvalue.santerihukari.com`. The `workers.dev` URL and version preview URLs are disabled. This leaves the existing apex website alone.

Build `RoomValue/frontend` before deploying this package; `assets.directory` points to its `dist` output. Install Wrangler as a development dependency or run it through the deployment environment's existing Wrangler installation. Run `npm test` from this directory for local, network-free route and credential-isolation checks.

## Private origin connection

The production `ROOMVALUE_API` binding points to an HTTP Workers VPC Service configured for `127.0.0.1:8004` through the deployment's Cloudflare Tunnel. This loopback port is a small authenticated bridge to the existing Python API at `127.0.0.1:8002`. No public backend hostname, DNS record or inbound port is needed. The VPC binding always routes to its configured service; the Worker's fixed `http://roomvalue.internal` request hostname does not select a network target.

The deployment configures `vpc_services` with binding `ROOMVALUE_API` and the provisioned service ID. This package does not guess an account or service ID. The local bridge, Python service, tunnel and PC must remain online for live simulations.

Set the Worker secret `ROOMVALUE_ORIGIN_SECRET` to a random value of at least 32 printable non-space ASCII characters. Configure the loopback bridge to require that same value in the `X-RoomValue-Origin-Secret` header. Keep this value in Worker secrets and the private `.runtime/cloudflare/origin-secret.txt` file (or the bridge process environment), never in frontend variables or public files. The Worker replaces caller headers with its own allowlist, strips caller cookies and authorization, and refuses upstream redirects.

For deployments that do not use Workers VPC, the optional `ROOMVALUE_API_ORIGIN` setting accepts a **HTTPS origin** without a path, query, credentials or fragment. A valid VPC binding takes precedence. This fallback also requires the origin secret and is not used by the current deployment.

## Offline saved example

If the PC or private origin is unreachable, the cloud site still displays the frozen dataset catalog and a previously verified completed example. These exact assets are generated from the existing successful simulation, not estimated or recomputed values:

- `/deployment/catalog.json`
- `/deployment/default-job.json`
- `/deployment/room.png` and `/deployment/field.png`

Offline health returns `allsolve_ready: false`, `deployment: "worker-pc"` and a clear PC-offline message. Catalog and saved-job responses carry `offline: true`, `snapshot: true` and `X-RoomValue-Mode: offline-snapshot`. Only the saved example's own job UUID can resolve to that snapshot. Other jobs and new submissions remain unavailable while the PC is disconnected. The Worker checks MIME type and basic snapshot structure so a missing asset's SPA HTML cannot masquerade as API data.

## Simulation admission

Both simulation submission and job resume require `ROOMVALUE_ALLOW_RUNS` to be the string `"true"` and a valid private binding/origin plus secret. The configuration starts with the switch disabled while the connection is provisioned; the deployment enables it after verification. The user authorized any visitor to launch simulations. Setting the switch to `"false"` later stops new submissions while preserving result viewing.

This switch is a deployment admission gate, **not user authentication**. A same-origin browser check blocks cross-origin POSTs but does not identify a user. Public requests use the existing Python API's single planner coordinator and validation before consuming solver resources. Each planner run launches independent Allsolve source/layout cases in parallel within the shared core quota. A request error never substitutes a saved example for a newly requested simulation.

## Exposed API routes

| Method | Route |
| --- | --- |
| GET | `/api/health` |
| GET | `/api/room3d/catalog` |
| GET | `/api/room3d/minimize/latest` |
| GET | `/api/room3d/preview/room` and `/api/room3d/preview/field` |
| GET | `/api/jobs/<UUID>` |
| POST | `/api/room3d/minimize` |
| POST | `/api/jobs/<UUID>/resume` |

Other paths under `/api` return `404`, wrong methods return `405`, query strings are rejected, and POST bodies are limited to 32 KiB. The earlier 2D comparison and budget/quiet-area optimization routes are deliberately unavailable here.

Configuration uses Cloudflare's [static assets routing](https://developers.cloudflare.com/workers/static-assets/routing/worker-script/), [SPA fallback](https://developers.cloudflare.com/workers/static-assets/routing/single-page-application/), [custom domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/) and [Workers VPC Services](https://developers.cloudflare.com/workers-vpc/configuration/vpc-services/).

## Run this PC connector

From the workspace PowerShell terminal, run `& '.\RoomValue\start-cloud.ps1'`. It verifies RoomValue on port 8002, starts the authenticated bridge on port 8004, checks unsigned requests return 403, and starts only this deployment's QUIC connector. Keep the PC awake and connected for new simulations. Run the script again after a reboot; automatic Windows startup is not configured.

Build and publish updates with `pnpm build` from `frontend`, then `pnpm dlx wrangler deploy --config wrangler.jsonc` from `cloudflare`. The configuration contains the provisioned account and VPC service IDs; secrets stay outside it.
