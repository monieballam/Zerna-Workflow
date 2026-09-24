#!/usr/bin/env bash
# Rebuild and recreate services so local code changes are picked up.
#
# Usage:
#   ./scripts/rebuild-restart-stack.sh worker
#       Default: rebuild worker with Docker layer cache (fast when Dockerfile unchanged).
#
#   ./scripts/rebuild-restart-stack.sh worker-fresh
#       Same as worker but docker build --no-cache (slow; use when deps/base image must be rebuilt).
#
#   ./scripts/rebuild-restart-stack.sh full-docker
#       Rebuild api + web + worker (cached) via docker-compose.yml + docker-compose.ec2.yml.
#       Stop host processes on API_PORT and 3000 first if you run API/web on the host.
#
#   ./scripts/rebuild-restart-stack.sh full-docker-fresh
#       full-docker with --no-cache on all three images (very slow).
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:-worker}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required." >&2
  exit 1
fi

case "$MODE" in
  worker)
    echo "==> Building worker image (using cache)..."
    docker compose build worker
    echo "==> Recreating worker container..."
    docker compose up -d --force-recreate worker
    echo "==> Done. Worker is running with a rebuilt image."
    docker compose ps worker
    ;;
  worker-fresh)
    echo "==> Building worker image (--no-cache; may take 20–40+ minutes)..."
    docker compose build --no-cache worker
    echo "==> Recreating worker container..."
    docker compose up -d --force-recreate worker
    echo "==> Done."
    docker compose ps worker
    ;;
  full-docker)
    echo "==> Building api, web, worker (cached) with EC2 compose overlay..."
    docker compose -f docker-compose.yml -f docker-compose.ec2.yml build api web worker
    echo "==> Recreating api, web, worker..."
    docker compose -f docker-compose.yml -f docker-compose.ec2.yml up -d --force-recreate api web worker
    echo "==> Done."
    docker compose -f docker-compose.yml -f docker-compose.ec2.yml ps api web worker
    ;;
  full-docker-fresh)
    echo "==> Building api, web, worker (--no-cache)..."
    docker compose -f docker-compose.yml -f docker-compose.ec2.yml build --no-cache api web worker
    docker compose -f docker-compose.yml -f docker-compose.ec2.yml up -d --force-recreate api web worker
    echo "==> Done."
    docker compose -f docker-compose.yml -f docker-compose.ec2.yml ps api web worker
    ;;
  *)
    echo "Usage: $0 [worker|worker-fresh|full-docker|full-docker-fresh]" >&2
    exit 1
    ;;
esac

echo ""
echo "Host-based dev (README): if API/dashboard run on the host, restart them manually after pulling code:"
echo "  API:       stop the old terminal (Ctrl+C), then ./scripts/start-api.sh"
echo "  Dashboard: stop the old terminal (Ctrl+C), then pnpm --dir apps/web dev"
