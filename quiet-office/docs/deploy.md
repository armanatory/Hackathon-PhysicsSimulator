# Running QuietOffice in Docker

QuietOffice ships as two containers, described in [`docker-compose.yml`](../docker-compose.yml):

| Container | What it is | Reachable from outside |
|-----------|------------|------------------------|
| `frontend` | nginx serving the built Vue app, and passing `/api` to the backend | Yes, port 8080 by default |
| `backend` | FastAPI + Allsolve SDK ([Dockerfile](../backend/Dockerfile)) | No, only from the frontend container |

The browser talks to one address only, so there is nothing to configure for CORS.

## On your own machine

With Docker Desktop running, from the `quiet-office/` folder:

```bash
docker compose up -d --build
```

Open http://localhost:8080.

```bash
docker compose logs -f backend
```

```bash
docker compose down
```

For day-to-day development `run.bat` is still quicker, because it reloads on every code change.
Docker is for checking the thing you will ship.

## Keys

The backend reads `QS_ACCESS_KEY` and `QS_SECRET_KEY` from an env file. Compose looks in two
places and neither is required:

1. the repository-root `.env` (what `run.bat` uses)
2. `quiet-office/.env`, which wins if both exist

The keys are passed to the container at start. They are not copied into the image, so the
image is safe to push to a registry.

An optional `OPENAI_API_KEY` in the same file turns on the plain-language explanation. When it
is used, the result summary and the run log messages are sent to OpenAI.

Without keys the app still starts; "Run on Allsolve" stays disabled and the page shows the
quick estimate.

## On the shared Hetzner server (allsolve.hiarman.com)

QuietOffice is registered on the shared server next to Vocabulens, Everonward and the others,
under the slug `quietoffice`. The host (Caddy with HTTPS, `/srv/<slug>/`, port ranges) is owned
by the Exovento repository's platform scripts. This was done once:

```bash
cd /c/myGit/Exovento
```

```bash
./scripts/host-ssh.sh add-app quietoffice allsolve.hiarman.com armanatory/Hackathon-PhysicsSimulator
```

Ports 6000 (backend) and 6001 (frontend), loopback only. `add-app` first handed out 5900-5903,
which Exovento itself listens on, so the range was moved by hand in `/etc/exovento/ports.tsv`,
`apps.tsv`, `caddy.env` and `/srv/quietoffice/.env`.

To deploy, from `quiet-office/` in Git Bash, with Docker Desktop running:

```bash
./scripts/deploy-local.sh
```

It builds the two images from the files on this disk, pushes them to GHCR
(`ghcr.io/armanatory/quietoffice-backend` and `-frontend`), copies `docker-compose.yml`,
[`docker-compose.prod.yml`](../docker-compose.prod.yml), [`Caddyfile.snippet`](../Caddyfile.snippet)
and `scripts/` to `/srv/quietoffice/`, and runs `scripts/hetzner-deploy.sh` there. The server has
no checkout of the code.

- SSH and GHCR settings come from `quiet-office/.env.deploy` (gitignored, see
  [`.env.deploy.example`](../.env.deploy.example)). `GHCR_PAT` needs `write:packages`.
- The Allsolve and OpenAI keys are taken from the repository-root `.env` and written to
  `/srv/quietoffice/.env` on each deploy.
- `DRY_RUN=1` builds only. `SKIP_GITCHECK=1` deploys this tree even when it is behind the remote.
- A deploy restarts the backend, so a search that is running at that moment is forgotten.

Logs on the server:

```bash
ssh deploy@204.168.171.29 'cd /srv/quietoffice && docker compose logs --tail=80 backend'
```

## On a fresh Hetzner server

A small cloud server is enough (the solving happens on Allsolve, not on the server). On a
fresh Ubuntu server:

1. Install Docker: follow https://docs.docker.com/engine/install/ubuntu/
2. Get the code:

```bash
git clone https://github.com/armanatory/Hackathon-PhysicsSimulator.git
```

```bash
cd Hackathon-PhysicsSimulator/quiet-office
```

3. Create `quiet-office/.env` on the server with the two keys:

```
QS_ACCESS_KEY=...
QS_SECRET_KEY=...
```

4. Start it:

```bash
docker compose up -d --build
```

5. Open `http://<server-ip>:8080`. To serve on the normal web port instead:

```bash
QUIETOFFICE_PORT=80 docker compose up -d
```

To update later: `git pull`, then `docker compose up -d --build` again. Both containers
restart on their own after a reboot.

## Before putting it on the public internet

These are not done yet. On a public server they matter.

- **There is no login.** Anyone who can open the page can press "Run on Allsolve", and every
  run spends your Allsolve compute. Put a password in front (nginx basic auth is the
  shortest route), or restrict the port to your own IP in the Hetzner firewall.
- **No HTTPS** on a fresh server: the app is served over plain HTTP. Put a reverse proxy with
  certificates in front, for example Caddy. (The shared server already does this.)
- **Run state is in memory.** A backend restart forgets running and finished searches. The
  Allsolve projects themselves stay in your Allsolve account.
- **One run at a time is the safe assumption.** Nothing limits how many searches are started
  at once, and a shared Allsolve account has a compute quota.
