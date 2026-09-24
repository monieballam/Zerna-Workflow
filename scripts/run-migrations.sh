#!/usr/bin/env bash
# Run Alembic migrations using DATABASE_URL from repo root .env (with ${...} expanded by env.py).
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

zerna_cd_repo_root

if ! zerna_require_env_file; then
    echo "Copy .env.example to .env and adjust POSTGRES_* / API_PORT first."
    exit 1
fi

echo "Running: alembic upgrade head (from apps/api, .env loaded by Alembic env.py)"
PYTHONPATH=. uv run --directory apps/api alembic upgrade head "$@"
