#!/usr/bin/env bash
# Explorer + annotation deployment smoke (modern vs legacy H5AD fixtures).
# Usage: from repo root, ./scripts/explorer_deployment_smoke.sh [extra pytest args]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH=.
exec uv run --project apps/api pytest apps/api/tests/test_explorer_deployment_smoke.py \
  -o addopts= \
  -m deployment_smoke \
  "$@"
