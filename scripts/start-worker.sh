#!/usr/bin/env bash
# Start the Temporal worker for Zerna Control Plane workflows.

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

zerna_cd_repo_root
WORKER_PATTERN='uv run python -m workflows\.worker|python3 -m workflows\.worker|python -m workflows\.worker'
STEP_RUNNER_PATTERN='python3? -m workflows\.run_execution\.step_runner'
WORKER_MODE="${ZERNA_WORKER_MODE:-supervised}"
if [ "${1:-}" = "--local" ]; then
    WORKER_MODE="local"
elif [ "${1:-}" = "--supervised" ]; then
    WORKER_MODE="supervised"
fi

echo -e "${GREEN}Starting Zerna Temporal Worker...${NC}"

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}Warning: .env file not found. Using .env.example as template.${NC}"
    echo -e "${YELLOW}Please copy .env.example to .env and configure it.${NC}"
    exit 1
fi

# Check if Temporal is running (Compose project must match for `ps temporal`; host worker also needs gRPC up)
echo -e "${GREEN}Checking Temporal server...${NC}"
_temporal_running="$(zerna_compose ps -q temporal 2>/dev/null || true)"
_temporal_host="$(zerna_read_env TEMPORAL_HOST localhost)"
_temporal_host="${_temporal_host//\"/}"
_temporal_port="$(zerna_read_env TEMPORAL_PORT 7233)"
_temporal_port="${_temporal_port//\"/}"

_temporal_skip_exec_health=false
if [ -n "${_temporal_running}" ]; then
    :
elif [ "${WORKER_MODE}" = "local" ]; then
    _tcp_ok=false
    if command -v nc >/dev/null 2>&1 && nc -z "${_temporal_host}" "${_temporal_port}" 2>/dev/null; then
        _tcp_ok=true
    elif (echo >/dev/tcp/"${_temporal_host}"/"${_temporal_port}") 2>/dev/null; then
        _tcp_ok=true
    fi
    if [ "${_tcp_ok}" = true ]; then
        echo -e "${YELLOW}Compose did not list service 'temporal' for this project, but ${_temporal_host}:${_temporal_port} is reachable.${NC}"
        echo -e "${YELLOW}Continuing (--local). Tip: export COMPOSE_PROJECT_NAME=zerna_kiro so compose and this script agree.${NC}"
        _temporal_skip_exec_health=true
    fi
fi

if [ -z "${_temporal_running}" ] && [ "${_temporal_skip_exec_health}" != true ]; then
    echo -e "${RED}Error: Temporal server is not running (or not visible to this compose project).${NC}"
    echo -e "${YELLOW}Start the core stack first: ./scripts/setup-dev-env.sh${NC}"
    echo -e "${YELLOW}Or manually: docker compose up -d postgres redis temporal minio minio-init worker${NC}"
    echo -e "${YELLOW}If containers are already up, set: export COMPOSE_PROJECT_NAME=zerna_kiro   # match docker ps names (e.g. zerna_kiro-temporal-1)${NC}"
    exit 1
fi

# Wait for Temporal to be healthy (tctl inside container; skip when compose project has no temporal service)
if [ "${_temporal_skip_exec_health}" = true ]; then
    echo -e "${GREEN}Skipping in-container tctl check; worker will connect to ${_temporal_host}:${_temporal_port}.${NC}"
else
    echo -e "${GREEN}Waiting for Temporal to be healthy...${NC}"
    timeout=30
    elapsed=0
    while ! zerna_compose exec -T temporal tctl cluster health &>/dev/null; do
        if [ $elapsed -ge $timeout ]; then
            echo -e "${RED}Error: Temporal server did not become healthy within ${timeout}s${NC}"
            exit 1
        fi
        echo -e "${YELLOW}Waiting for Temporal... (${elapsed}s/${timeout}s)${NC}"
        sleep 2
        elapsed=$((elapsed + 2))
    done
    echo -e "${GREEN}Temporal is healthy!${NC}"
fi

if [ "${WORKER_MODE}" = "supervised" ]; then
    existing_workers="$(pgrep -f "${WORKER_PATTERN}" || true)"
    if [ -n "${existing_workers}" ]; then
        echo -e "${YELLOW}Stopping existing local worker processes: ${existing_workers}${NC}"
        kill ${existing_workers} 2>/dev/null || true
        sleep 2
    fi
    orphan_step_runners="$(pgrep -f "${STEP_RUNNER_PATTERN}" || true)"
    if [ -n "${orphan_step_runners}" ]; then
        echo -e "${YELLOW}Stopping orphaned local scientific subprocesses: ${orphan_step_runners}${NC}"
        kill ${orphan_step_runners} 2>/dev/null || true
        sleep 2
        remaining_step_runners="$(pgrep -f "${STEP_RUNNER_PATTERN}" || true)"
        if [ -n "${remaining_step_runners}" ]; then
            echo -e "${YELLOW}Force stopping stubborn scientific subprocesses: ${remaining_step_runners}${NC}"
            kill -9 ${remaining_step_runners} 2>/dev/null || true
            sleep 1
        fi
    fi

    echo -e "${GREEN}Starting supervised worker service via Docker Compose...${NC}"
    zerna_compose up -d --build worker

    echo -e "${GREEN}Waiting for supervised worker to become healthy...${NC}"
    worker_timeout=120
    worker_elapsed=0
    while true; do
        worker_container_id="$(zerna_compose ps -q worker)"
        if [ -n "${worker_container_id}" ]; then
            worker_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${worker_container_id}" 2>/dev/null || echo unknown)"
            if [ "${worker_health}" = "healthy" ]; then
                break
            fi
        else
            worker_health="missing"
        fi

        if [ "${worker_elapsed}" -ge "${worker_timeout}" ]; then
            echo -e "${RED}Error: worker did not become healthy within ${worker_timeout}s${NC}"
            echo -e "${YELLOW}Recent worker logs:${NC}"
            zerna_compose logs --tail=100 worker || true
            exit 1
        fi

        echo -e "${YELLOW}Waiting for worker... (${worker_elapsed}s/${worker_timeout}s, status: ${worker_health})${NC}"
        sleep 2
        worker_elapsed=$((worker_elapsed + 2))
    done

    echo -e "${GREEN}Worker is now supervised with restart=unless-stopped.${NC}"
    echo -e "${GREEN}Press Ctrl+C to stop following logs; the worker service will keep running.${NC}"
    echo ""
    zerna_compose logs -f --tail=50 worker
    exit 0
fi

# Ensure the workspace environment exists and includes workflow runtime dependencies.
echo -e "${GREEN}Syncing Python workspace...${NC}"
zerna_uv_sync

# Avoid stacking multiple long-lived workers on the same task queue.
existing_workers="$(pgrep -f "${WORKER_PATTERN}" || true)"
if [ -n "${existing_workers}" ]; then
    echo -e "${YELLOW}Stopping existing worker processes: ${existing_workers}${NC}"
    kill ${existing_workers} 2>/dev/null || true
    sleep 2
    remaining_workers="$(pgrep -f "${WORKER_PATTERN}" || true)"
    if [ -n "${remaining_workers}" ]; then
        echo -e "${YELLOW}Force stopping unresponsive worker processes: ${remaining_workers}${NC}"
        kill -9 ${remaining_workers} 2>/dev/null || true
        sleep 1
    fi
fi

orphan_step_runners="$(pgrep -f "${STEP_RUNNER_PATTERN}" || true)"
if [ -n "${orphan_step_runners}" ]; then
    echo -e "${YELLOW}Stopping orphaned scientific subprocesses: ${orphan_step_runners}${NC}"
    kill ${orphan_step_runners} 2>/dev/null || true
    sleep 2
    remaining_step_runners="$(pgrep -f "${STEP_RUNNER_PATTERN}" || true)"
    if [ -n "${remaining_step_runners}" ]; then
        echo -e "${YELLOW}Force stopping unresponsive scientific subprocesses: ${remaining_step_runners}${NC}"
        kill -9 ${remaining_step_runners} 2>/dev/null || true
        sleep 1
    fi
fi

echo -e "${YELLOW}Running worker locally without supervision.${NC}"
echo -e "${YELLOW}Use ./scripts/start-worker.sh or ZERNA_WORKER_MODE=supervised for auto-restart.${NC}"
echo -e "${GREEN}Starting worker on task queue: zerna-control-plane${NC}"
echo -e "${GREEN}Press Ctrl+C to stop the worker${NC}"
echo ""

export NUMBA_THREADING_LAYER="${NUMBA_THREADING_LAYER:-workqueue}"
PYTHONPATH=. uv run python -m workflows.worker
