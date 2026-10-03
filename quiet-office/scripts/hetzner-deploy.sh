#!/usr/bin/env bash
# Server-side deploy entrypoint. Called over SSH by deploy-local.sh
# from the laptop. Assumes the operational files (this script,
# docker-compose*.yml, Caddyfile.snippet) have been copied to
# /srv/quietoffice/ as part of the same deploy.
#
# Required env (passed via the SSH command line):
#   TAG          - image tag to roll (e.g. local-abc1234)
#   IMAGE_OWNER  - GHCR owner / org
# Optional:
#   GHCR_PAT, GHCR_USERNAME - for `docker login ghcr.io` (private images)
#   FORWARDED_KEYS - space-separated list of runtime keys whose values
#                    were sent in via this SSH env. Each one is sync'd
#                    into /srv/quietoffice/.env.
#
# This script never touches git. The server has no checkout - the
# laptop is source-of-truth.

set -euo pipefail

cd /srv/quietoffice

if [ ! -f .env ]; then
  echo "ERROR: /srv/quietoffice/.env missing. Run Exovento's add-app first." >&2
  exit 1
fi

# Self-heal CRLF in .env (Windows editors sneak \r into values, which
# silently breaks API keys).
if grep -q $'\r' .env 2>/dev/null; then
  echo "⚠ .env had CRLF - stripping \\r"
  sed -i 's/\r$//' .env
fi

export IMAGE_OWNER="${IMAGE_OWNER:?IMAGE_OWNER not set}"
export TAG="${TAG:?TAG not set}"

# Persist what tag is on disk so the cockpit (and humans) can read it.
echo "$TAG" > .last-deploy.tag
date -u +%FT%TZ > .last-deploy.at

if [ -n "${GHCR_PAT:-}" ]; then
  GHCR_USER="${GHCR_USERNAME:-$IMAGE_OWNER}"
  echo "🔑 docker login ghcr.io as $GHCR_USER"
  echo "$GHCR_PAT" | docker login ghcr.io -u "$GHCR_USER" --password-stdin
fi

# ─────────────────────────────────────────────────────────────
# Sync runtime keys into /srv/quietoffice/.env
# ─────────────────────────────────────────────────────────────
# Every deploy, the laptop forwards the runtime keys (Allsolve, OpenAI)
# via SSH env vars. Empty values are skipped, so the value already on
# the server is kept.
sync_env_key() {
  local key="$1" val="$2"
  if [ -z "$val" ]; then return 0; fi
  val="${val%$'\r'}"
  if grep -q "^${key}=" .env 2>/dev/null; then
    awk -v k="$key" -v v="$val" '
      BEGIN { rewrote = 0 }
      $0 ~ "^"k"=" { print k"="v; rewrote = 1; next }
      { print }
      END { if (!rewrote) print k"="v }
    ' .env > .env.tmp && chmod 600 .env.tmp && mv .env.tmp .env
  else
    echo "${key}=${val}" >> .env
  fi
}

if [ -n "${FORWARDED_KEYS:-}" ]; then
  for fkey in $FORWARDED_KEYS; do
    sync_env_key "$fkey" "${!fkey:-}"
  done
fi

# Self-heal: a stale TAG=latest in .env would shadow the SSH-passed value.
sed -i '/^TAG=/d' .env

COMPOSE=(docker compose --env-file ./.env -f docker-compose.yml -f docker-compose.prod.yml)

echo "Deploying TAG=$TAG (owner=$IMAGE_OWNER)"
"${COMPOSE[@]}" pull

echo "▶ backend + frontend"
"${COMPOSE[@]}" up -d --remove-orphans

# Force-recreate the backend so a changed key actually loads (settings are
# read once at startup). Run state is in memory, so this also forgets any
# search that was running.
echo "🔁 Force-recreating backend"
"${COMPOSE[@]}" up -d --force-recreate --no-deps backend

# ─────────────────────────────────────────────────────────────
# Install / refresh Caddy snippet, reload host Caddy
# ─────────────────────────────────────────────────────────────
if [ -f Caddyfile.snippet ] && [ -d /etc/caddy/Caddyfile.d ]; then
  if sudo install -m 0644 -o root -g root Caddyfile.snippet /etc/caddy/Caddyfile.d/quietoffice.caddyfile; then
    if sudo caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
      sudo systemctl reload caddy && echo "↻ Reloaded host Caddy"
    else
      echo "⚠ Host Caddyfile failed to validate - NOT reloading." >&2
      sudo caddy validate --config /etc/caddy/Caddyfile >&2 || true
    fi
  fi
elif [ ! -d /etc/caddy/Caddyfile.d ]; then
  echo "ℹ /etc/caddy/Caddyfile.d not present - host Caddy not bootstrapped yet." >&2
fi

# Image prune: only `until=168h`, NEVER `docker system prune` or
# `--volumes` - the other apps' data lives on the same host.
docker image prune -f --filter "until=168h" >/dev/null

# ─────────────────────────────────────────────────────────────
# Stack health probe
# ─────────────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════════"
echo "Stack health"
echo "════════════════════════════════════════════════════════════"
STACK_FAIL=0

probe() {
  # probe <label> <url>
  local label="$1" url="$2" i
  echo -n "  waiting for $label "
  for i in $(seq 1 40); do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      echo "(${i}s) ok"; return 0
    fi
    echo -n "."; sleep 1
  done
  echo " timed out"; return 1
}

BACKEND_PORT="$("${COMPOSE[@]}" port backend 8000 2>/dev/null | awk -F: 'NR==1{print $NF}')"
FRONTEND_PORT="$("${COMPOSE[@]}" port frontend 80 2>/dev/null | awk -F: 'NR==1{print $NF}')"
probe "backend /health on 127.0.0.1:${BACKEND_PORT:-6000}" "http://127.0.0.1:${BACKEND_PORT:-6000}/health" || STACK_FAIL=1
probe "frontend on 127.0.0.1:${FRONTEND_PORT:-6001}" "http://127.0.0.1:${FRONTEND_PORT:-6001}/" || STACK_FAIL=1

if systemctl is-active caddy >/dev/null 2>&1; then
  echo "  ✓ host Caddy is active"
else
  echo "  ✗ host Caddy is $(systemctl is-active caddy)" >&2; STACK_FAIL=1
fi

if [ "$STACK_FAIL" = 1 ]; then
  echo                                                                >&2
  echo "════════════════════════════════════════════════════════════" >&2
  echo "✗ Stack health failed. Diagnostic dumps:"                      >&2
  echo "─── compose ps ───"                                            >&2
  "${COMPOSE[@]}" ps                                                   >&2 || true
  echo "─── backend logs (last 80) ───"                                >&2
  "${COMPOSE[@]}" logs --tail=80 --no-color backend                    2>&1 >&2 || true
  echo "─── frontend logs (last 30) ───"                               >&2
  "${COMPOSE[@]}" logs --tail=30 --no-color frontend                   2>&1 >&2 || true
  echo "─── host Caddy (journalctl, last 30) ───"                      >&2
  journalctl -u caddy -n 30 --no-pager                                 2>&1 >&2 || true
  exit 1
fi

echo "Deploy complete: $TAG"
