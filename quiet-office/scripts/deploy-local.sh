#!/usr/bin/env bash
# Laptop-side deploy: build the two images locally, push them to GHCR, copy
# the operational files (compose, Caddy snippet, scripts) into
# /srv/quietoffice/, then SSH in and run hetzner-deploy.sh.
#
# Server has NO git, NO repo - the laptop is source-of-truth. Each deploy
# overwrites /srv/quietoffice/{docker-compose.yml,docker-compose.prod.yml,
# Caddyfile.snippet,scripts/} with whatever is on the laptop.
#
# Usage (from quiet-office/, in Git Bash):
#   ./scripts/deploy-local.sh                  # build + push + deploy
#   DRY_RUN=1 ./scripts/deploy-local.sh        # build only, no push, no SSH
#   SKIP_BUILD=1 TAG=local-abc123 ./scripts/deploy-local.sh
#   SKIP_DEPLOY=1 ./scripts/deploy-local.sh    # build + push, no SSH
#   AUTO_PULL=1 ./scripts/deploy-local.sh      # fast-forward to the remote first
#   SKIP_GITCHECK=1 ./scripts/deploy-local.sh  # deploy this tree even if it is behind
#
# Reads quiet-office/.env.deploy (gitignored) for:
#   SSH_HOST, SSH_KEY, SSH_USER, SSH_PORT
#     (HETZNER_HOST / HETZNER_SSH_KEY_PATH still accepted as legacy aliases)
#   IMAGE_OWNER, GHCR_PAT
#
# Runtime keys (QS_ACCESS_KEY, QS_SECRET_KEY, QS_HOST, OPENAI_API_KEY) are read
# from the same files the app uses locally - the repository-root .env, then
# quiet-office/.env - and forwarded to /srv/quietoffice/.env on each deploy.
# A key set in .env.deploy wins, in case the server should use different keys.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Later files win.
ENV_FILES=("$ROOT/../.env" "$ROOT/.env" "$ROOT/.env.deploy")

# Parse env files literally - never `source` them. Sourcing runs every
# value through the shell, so `$` / `!` / backticks in a key trip
# variable expansion or history substitution and fail under `set -u`.
parse_env_file() {
  local file="$1" line key val
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    case "$line" in *=*) ;; *) continue ;; esac
    key="${line%%=*}"
    val="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    case "$val" in
      \"*)
        val="${val#\"}"; val="${val%%\"*}" ;;
      \'*)
        val="${val#\'}"; val="${val%%\'*}" ;;
      *)
        val="${val%%[[:space:]]#*}"
        val="${val%"${val##*[![:space:]]}"}"
        ;;
    esac
    export "$key=$val"
  done < "$file"
}
for f in "${ENV_FILES[@]}"; do parse_env_file "$f"; done

# Legacy aliases - older .env.deploy files used HETZNER_* names.
: "${SSH_HOST:=${HETZNER_HOST:-}}"
: "${SSH_KEY:=${HETZNER_SSH_KEY_PATH:-}}"
: "${SSH_USER:=${HETZNER_USER:-deploy}}"
: "${SSH_PORT:=${HETZNER_SSH_PORT:-22}}"

: "${IMAGE_OWNER:=armanatory}"
: "${REGISTRY:=ghcr.io}"
: "${GHCR_USERNAME:=$IMAGE_OWNER}"

# ─────────────────────────────────────────────────────────────
# Freshness check: is this checkout actually what we think it is?
# ─────────────────────────────────────────────────────────────
# This script builds the files on this disk and reads git only to name the
# image tag, so a checkout that has not been pulled deploys old code with a
# green tick. Fetch (read-only) and refuse to build when this checkout is
# behind or has diverged. Deliberately NOT an automatic `git pull`.
#   AUTO_PULL=1     fast-forward only, never a merge, never on a dirty tree
#   SKIP_GITCHECK=1 skip this entirely
if [ -z "${SKIP_GITCHECK:-}" ]; then
  BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
  UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"

  if [ "$BRANCH" = "HEAD" ]; then
    echo "⚠ Detached HEAD - skipping the freshness check."
  elif [ -z "$UPSTREAM" ]; then
    echo "⚠ Branch '$BRANCH' tracks nothing upstream - skipping the freshness check."
  else
    echo "▶ Checking '$BRANCH' against $UPSTREAM"
    REMOTE="${UPSTREAM%%/*}"
    REMOTE_BRANCH="${UPSTREAM#*/}"
    if ! git fetch --quiet "$REMOTE" "$REMOTE_BRANCH" 2>/dev/null; then
      echo "  ⚠ Could not reach the remote. Proceeding on stale remote refs -"
      echo "    this deploy may not be current with $UPSTREAM."
    fi

    COUNTS="$(git rev-list --left-right --count "$UPSTREAM...HEAD" 2>/dev/null || echo "0	0")"
    BEHIND="$(echo "$COUNTS" | cut -f1)"
    AHEAD="$(echo "$COUNTS" | cut -f2)"

    if [ "$BEHIND" -gt 0 ] && [ "$AHEAD" -gt 0 ]; then
      echo "✗ '$BRANCH' has diverged from $UPSTREAM: $BEHIND behind, $AHEAD ahead." >&2
      echo "  Reconcile it yourself before deploying, so you know what ships:"   >&2
      echo "    git pull --rebase && git push"                                   >&2
      echo "  (Or SKIP_GITCHECK=1 if you really mean to deploy this tree.)"      >&2
      exit 6
    elif [ "$BEHIND" -gt 0 ]; then
      if [ -n "${AUTO_PULL:-}" ]; then
        if ! git diff --quiet || ! git diff --cached --quiet; then
          echo "✗ $BEHIND commit(s) behind $UPSTREAM, and this tree has uncommitted changes." >&2
          echo "  AUTO_PULL will not touch a dirty tree. Commit or stash first."              >&2
          exit 6
        fi
        echo "  ↧ $BEHIND commit(s) behind - fast-forwarding"
        git merge --ff-only "$UPSTREAM"
      else
        echo "✗ '$BRANCH' is $BEHIND commit(s) behind $UPSTREAM." >&2
        echo                                                       >&2
        echo "  You would be deploying code older than what is on the remote."  >&2
        git --no-pager log --oneline -n 10 "HEAD..$UPSTREAM" >&2
        if [ "$BEHIND" -gt 10 ]; then echo "    ... and $((BEHIND - 10)) older" >&2; fi
        echo                                                       >&2
        echo "  Run:  git pull"                                    >&2
        echo "  Or:   AUTO_PULL=1 ./scripts/deploy-local.sh"       >&2
        echo "  Or:   SKIP_GITCHECK=1 ./scripts/deploy-local.sh   (deploy this tree anyway)" >&2
        exit 6
      fi
    elif [ "$AHEAD" -gt 0 ]; then
      echo "  ⚠ $AHEAD commit(s) ahead of $UPSTREAM (not pushed). Deploying them anyway."
    else
      echo "  ✓ up to date with $UPSTREAM"
    fi
  fi
fi

GIT_SHA="$(git rev-parse --short HEAD)"
GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DIRTY=""
if ! git diff --quiet || ! git diff --cached --quiet; then
  DIRTY="-dirty"
fi
: "${TAG:=local-${GIT_SHA}${DIRTY}}"

IMG_BACKEND="${REGISTRY}/${IMAGE_OWNER}/quietoffice-backend:${TAG}"
IMG_FRONTEND="${REGISTRY}/${IMAGE_OWNER}/quietoffice-frontend:${TAG}"

GIT_FULL_SHA="$(git rev-parse HEAD)"
GIT_LAST_MSG="$(git log -1 --pretty=format:%s)"

echo "→ Tag       : $TAG"
echo "→ Branch    : $GIT_BRANCH"
echo "→ Commit    : ${GIT_FULL_SHA:0:12} - $GIT_LAST_MSG"
echo "→ Owner     : $IMAGE_OWNER"

SECONDS=0

# ─────────────────────────────────────────────────────────────
# Pre-flight: confirm the server is bootstrapped for QuietOffice.
# Fails fast before a build that can't deploy.
# ─────────────────────────────────────────────────────────────
if [ -z "${DRY_RUN:-}" ]; then
  : "${SSH_HOST:?Set SSH_HOST in .env.deploy or the environment}"
  : "${SSH_KEY:?Set SSH_KEY in .env.deploy (absolute path to your private key)}"

  [ -f "$SSH_KEY" ] || { echo "✗ SSH key not found: $SSH_KEY" >&2; exit 2; }
  chmod 600 "$SSH_KEY" 2>/dev/null || true

  SSH_OPTS=(
    -i "$SSH_KEY"
    -p "$SSH_PORT"
    -o StrictHostKeyChecking=accept-new
    -o ServerAliveInterval=30
    -o ConnectTimeout=15
    -o ConnectionAttempts=3
    -o IdentitiesOnly=yes
  )
fi

if [ -z "${DRY_RUN:-}" ] && [ -z "${SKIP_PREFLIGHT:-}" ]; then
  echo
  echo "▶ Pre-flight: checking ${SSH_USER}@${SSH_HOST}:/srv/quietoffice"
  PREFLIGHT="$(ssh "${SSH_OPTS[@]}" "${SSH_USER}@${SSH_HOST}" '
    state=ok
    [ -d /srv/quietoffice ] || state=missing-dir
    [ -f /srv/quietoffice/.env ] || { [ "$state" = ok ] && state=missing-env; }
    [ -w /srv/quietoffice ] || { [ "$state" = ok ] && state=not-writable; }
    echo "$state"
  ' 2>/dev/null || echo "ssh-failed")"
  case "$PREFLIGHT" in
    ok)
      echo "  ✓ /srv/quietoffice ready"
      ;;
    missing-dir|missing-env|not-writable)
      echo "✗ Server not bootstrapped for QuietOffice (state: $PREFLIGHT)." >&2
      echo                                                                >&2
      echo "  Run this once, from the Exovento repo:"                      >&2
      echo "    ./scripts/host-ssh.sh add-app quietoffice allsolve.hiarman.com armanatory/Hackathon-PhysicsSimulator" >&2
      echo                                                                >&2
      echo "  (Override only if you know what you're doing:"              >&2
      echo "    SKIP_PREFLIGHT=1 ./scripts/deploy-local.sh)"               >&2
      exit 3
      ;;
    ssh-failed)
      echo "✗ SSH probe failed. Check SSH_HOST, SSH_USER, SSH_KEY, SSH_PORT." >&2
      exit 4
      ;;
    *)
      echo "✗ Unexpected pre-flight state: '$PREFLIGHT'" >&2
      exit 5
      ;;
  esac
fi

# ─────────────────────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────────────────────
if [ -z "${SKIP_BUILD:-}" ]; then
  echo
  echo "▶ Building backend image…"
  docker build -t "$IMG_BACKEND" ./backend

  echo
  echo "▶ Building frontend image (the page calls the API same-origin)…"
  docker build -t "$IMG_FRONTEND" ./frontend
else
  echo "↷ SKIP_BUILD set - using existing local images at $TAG"
fi

if [ -n "${DRY_RUN:-}" ]; then
  echo
  echo "✓ Dry run complete. Built images:"
  docker images --format '   {{.Repository}}:{{.Tag}}  {{.Size}}' | grep -F ":$TAG" || true
  exit 0
fi

# ─────────────────────────────────────────────────────────────
# Push to GHCR
# ─────────────────────────────────────────────────────────────
echo
echo "▶ Pushing images to ${REGISTRY}…"
if [ -n "${GHCR_PAT:-}" ]; then
  echo "$GHCR_PAT" | docker login "$REGISTRY" -u "$GHCR_USERNAME" --password-stdin >/dev/null
fi
docker push "$IMG_BACKEND"
docker push "$IMG_FRONTEND"

if [ -n "${SKIP_DEPLOY:-}" ]; then
  echo
  echo "✓ Pushed but SKIP_DEPLOY set - server not touched. Tag: $TAG"
  exit 0
fi

# ─────────────────────────────────────────────────────────────
# Sync operational files to /srv/quietoffice/
# ─────────────────────────────────────────────────────────────
RSYNC_E="ssh -i ${SSH_KEY} -p ${SSH_PORT} -o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes"

echo
echo "▶ Syncing operational files → ${SSH_USER}@${SSH_HOST}:/srv/quietoffice/"
if command -v rsync >/dev/null 2>&1; then
  echo "  using rsync"
  # --delete only for paths we explicitly include - keeps .env,
  # .last-deploy.tag, etc. (server-only state) intact.
  rsync -az --delete \
    -e "$RSYNC_E" \
    --include='Caddyfile.snippet' \
    --include='docker-compose.yml' \
    --include='docker-compose.prod.yml' \
    --include='scripts/' --include='scripts/**' \
    --exclude='*' \
    ./ "${SSH_USER}@${SSH_HOST}:/srv/quietoffice/"
else
  # Git Bash on Windows ships no rsync by default. Fall back to a
  # three-step bundle/scp/extract.
  echo "  rsync not found - bundle/scp/extract fallback"
  BUNDLE="$(mktemp -t quietoffice-deploy-XXXXXX.tgz 2>/dev/null || echo "$TMPDIR/quietoffice-deploy-$$.tgz")"
  trap 'rm -f "$BUNDLE"' EXIT

  echo "  packaging…"
  tar -czf "$BUNDLE" -C "$ROOT" \
    Caddyfile.snippet \
    docker-compose.yml \
    docker-compose.prod.yml \
    scripts

  echo "  uploading $(du -h "$BUNDLE" | awk '{print $1}')…"
  scp -i "$SSH_KEY" -P "$SSH_PORT" \
    -o StrictHostKeyChecking=accept-new \
    -o IdentitiesOnly=yes \
    "$BUNDLE" "${SSH_USER}@${SSH_HOST}:/tmp/quietoffice-deploy.tgz"

  echo "  extracting…"
  ssh "${SSH_OPTS[@]}" "${SSH_USER}@${SSH_HOST}" \
    'set -e
     rm -rf /srv/quietoffice/scripts
     tar -xzf /tmp/quietoffice-deploy.tgz -C /srv/quietoffice/
     rm -f /tmp/quietoffice-deploy.tgz
     sed -i "s/\r$//" /srv/quietoffice/scripts/*.sh
     chmod +x /srv/quietoffice/scripts/*.sh 2>/dev/null || true'
fi

# ─────────────────────────────────────────────────────────────
# SSH in and roll the stack
# ─────────────────────────────────────────────────────────────
# Forward runtime keys to hetzner-deploy.sh's sync_env_key step: every key
# found in the env files above, EXCEPT laptop-only deploy mechanics (SSH
# config, GHCR creds) and build-time VITE_* keys.
DEPLOY_ONLY_KEYS=(
  # SSH / Hetzner mechanics
  SSH_HOST SSH_USER SSH_PORT SSH_KEY HETZNER_HOST HETZNER_USER HETZNER_SSH_PORT HETZNER_SSH_KEY_PATH
  # Image registry mechanics
  REGISTRY IMAGE_OWNER GHCR_PAT GHCR_USERNAME
  # Tag bookkeeping
  TAG
  # Local docker-compose port
  QUIETOFFICE_PORT
)

declare -A IS_DEPLOY_ONLY
for k in "${DEPLOY_ONLY_KEYS[@]}"; do IS_DEPLOY_ONLY[$k]=1; done

declare -A SEEN
SSH_ENV_PAIRS=()
FORWARDED=()
for f in "${ENV_FILES[@]}"; do
  [ -f "$f" ] || continue
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    case "$line" in *=*) ;; *) continue ;; esac
    key="${line%%=*}"
    key="${key#"${key%%[![:space:]]*}"}"
    [ -n "${IS_DEPLOY_ONLY[$key]:-}" ] && continue
    [ -n "${SEEN[$key]:-}" ] && continue
    case "$key" in VITE_*) continue ;; esac
    val="${!key:-}"
    [ -z "$val" ] && continue
    escaped="${val//\'/\'\\\'\'}"
    SSH_ENV_PAIRS+=("${key}='${escaped}'")
    FORWARDED+=("$key")
    SEEN[$key]=1
  done < "$f"
done

if [ "${#FORWARDED[@]}" -gt 0 ]; then
  echo "  → forwarding to /srv/quietoffice/.env: ${FORWARDED[*]}"
else
  echo "  → no runtime keys to forward (server keeps whatever is in .env)"
fi
SSH_ENV="${SSH_ENV_PAIRS[*]:-}"

echo
echo "▶ Triggering hetzner-deploy.sh on ${SSH_HOST}"
FORWARDED_KEYS_STR="${FORWARDED[*]:-}"
ssh "${SSH_OPTS[@]}" "${SSH_USER}@${SSH_HOST}" \
  "TAG='$TAG' \
   IMAGE_OWNER='$IMAGE_OWNER' \
   GHCR_USERNAME='$GHCR_USERNAME' \
   GHCR_PAT='${GHCR_PAT:-}' \
   FORWARDED_KEYS='$FORWARDED_KEYS_STR' \
   $SSH_ENV \
   bash /srv/quietoffice/scripts/hetzner-deploy.sh"

# Confirm the server actually advanced.
SERVER_TAG="$(ssh "${SSH_OPTS[@]}" "${SSH_USER}@${SSH_HOST}" 'cat /srv/quietoffice/.last-deploy.tag 2>/dev/null' || echo '?')"

echo
echo "════════════════════════════════════════════════════════════"
if [ "$SERVER_TAG" = "$TAG" ]; then
  echo "✓ Deploy complete in ${SECONDS}s - server now on $TAG"
  echo "  https://allsolve.hiarman.com"
else
  echo "⚠ Server says .last-deploy.tag=$SERVER_TAG but we pushed $TAG. Investigate." >&2
  exit 1
fi
echo "════════════════════════════════════════════════════════════"
