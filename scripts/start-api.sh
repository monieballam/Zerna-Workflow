#!/usr/bin/env bash
# Start the Zerna Control Plane API from the repository root.

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

zerna_cd_repo_root

HOST="${ZERNA_API_HOST:-0.0.0.0}"

echo -e "${GREEN}Starting Zerna API...${NC}"

if [ ! -f .env ]; then
    echo -e "${YELLOW}Warning: .env file not found. Using .env.example as template.${NC}"
    cp .env.example .env
fi

# Port: ZERNA_API_PORT overrides .env API_PORT overrides default 8000
if [ -n "${ZERNA_API_PORT:-}" ]; then
    PORT="${ZERNA_API_PORT}"
else
    PORT="$(zerna_read_env API_PORT 8000)"
fi

POSTGRES_PORT="$(zerna_read_env POSTGRES_PORT 5432)"
if command -v nc >/dev/null 2>&1; then
    if ! nc -z 127.0.0.1 "${POSTGRES_PORT}" 2>/dev/null; then
        echo -e "${YELLOW}Nothing is accepting connections on 127.0.0.1:${POSTGRES_PORT} (Postgres).${NC}"
        echo -e "${YELLOW}Start the core stack first: ./scripts/setup-dev-env.sh${NC}"
    fi
fi

if command -v lsof >/dev/null 2>&1; then
    if lsof -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
        echo -e "${YELLOW}Port ${PORT} is already in use. Free it or set API_PORT / ZERNA_API_PORT to another port.${NC}"
        echo -e "${YELLOW}Example: lsof -iTCP:${PORT} -sTCP:LISTEN${NC}"
    fi
fi

echo -e "${GREEN}Syncing Python workspace...${NC}"
zerna_uv_sync

echo -e "${GREEN}Starting API on ${HOST}:${PORT}${NC}"
exec env PYTHONPATH=. uv run uvicorn apps.api.main:app --reload --host "${HOST}" --port "${PORT}" "$@"
