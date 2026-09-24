#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-quick}"

cd "$ROOT_DIR"

log_section() {
  printf '\n==> %s\n' "$1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

ensure_dev_services() {
  require_cmd docker
  log_section "Starting local CI dependencies (postgres, redis)"
  docker compose up -d postgres redis >/dev/null
}

run_quick_checks() {
  require_cmd uv
  require_cmd pnpm

  ensure_dev_services

  export DATABASE_URL="${DATABASE_URL:-postgresql://zerna:zerna_test@localhost:5432/zerna_test}"
  export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
  export ENVIRONMENT="${ENVIRONMENT:-test}"
  export SECRET_KEY="${SECRET_KEY:-test-secret-key-for-ci}"
  export PYTHONPATH="${PYTHONPATH:-.}"
  export CI=1

  log_section "Python lint"
  uv run ruff check .
  uv run ruff format --check .

  log_section "Python typing"
  (
    cd packages/contracts
    uv run mypy zerna_contracts
  )
  if ! uv run mypy -p apps.api --exclude '/tests/' --ignore-missing-imports --follow-imports=silent; then
    echo "Warning: apps/api mypy check failed (advisory in GitHub CI)." >&2
  fi

  log_section "Python tests"
  uv run pytest --cov --cov-report=xml -m "not integration and not slow and not property and not uat"

  log_section "Property tests"
  HYPOTHESIS_MAX_EXAMPLES="${HYPOTHESIS_MAX_EXAMPLES:-100}" uv run pytest -m property --hypothesis-seed=0 -x

  log_section "JavaScript lint"
  pnpm lint:js

  log_section "TypeScript check"
  pnpm --filter @zerna/web exec tsc --noEmit

  log_section "Frontend tests"
  if ! pnpm --filter @zerna/web test; then
    echo "Warning: frontend tests failed (advisory in GitHub CI)." >&2
  fi
}

run_integration_checks() {
  require_cmd docker

  log_section "Starting integration services"
  docker compose -f docker-compose.integration.yml up -d --wait --wait-timeout 120 \
    postgres-test redis-test minio-test temporal-test

  cleanup_integration() {
    docker compose -f docker-compose.integration.yml down -v --remove-orphans >/dev/null 2>&1 || true
  }
  trap cleanup_integration RETURN

  log_section "Initializing integration buckets"
  docker compose -f docker-compose.integration.yml up --no-deps --exit-code-from minio-test-init minio-test-init

  export DATABASE_URL="postgresql+asyncpg://zerna_test:zerna_test@localhost:5433/zerna_integration_test"
  export REDIS_URL="redis://:zerna_test_redis@localhost:6380/0"
  export S3_ENDPOINT_URL="http://localhost:9002"
  export S3_ACCESS_KEY_ID="minioadmin"
  export S3_SECRET_ACCESS_KEY="minioadmin"
  export S3_DATASETS_BUCKET="zerna-datasets-test"
  export S3_ARTIFACTS_BUCKET="zerna-artifacts-test"
  export JWT_SECRET_KEY="integration-test-secret-key"
  export JWT_ALGORITHM="HS256"
  export ENVIRONMENT="test"
  export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
  export PYTHONPATH="."

  log_section "Integration tests"
  uv run pytest -m integration --tb=short -q
}

run_migration_checks() {
  require_cmd docker

  log_section "Starting migration database"
  docker compose -f docker-compose.integration.yml up -d --wait --wait-timeout 120 postgres-test

  cleanup_migration() {
    docker compose -f docker-compose.integration.yml down -v --remove-orphans >/dev/null 2>&1 || true
  }
  trap cleanup_migration RETURN

  export DATABASE_URL="postgresql://zerna_test:zerna_test@localhost:5433/zerna_integration_test"
  export PYTHONPATH="."

  log_section "Migration tests"
  uv run pytest apps/api/tests/test_migrations.py -v --cov=apps/api/alembic --cov-report=term-missing

  log_section "Migration upgrade/downgrade/idempotency"
  (
    cd apps/api

    docker compose -f ../../docker-compose.integration.yml exec -T postgres-test psql \
      -U zerna_test \
      -d zerna_integration_test \
      -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"
    uv run alembic upgrade head
    uv run alembic current

    uv run alembic downgrade base
    docker compose -f ../../docker-compose.integration.yml exec -T postgres-test psql \
      -U zerna_test \
      -d zerna_integration_test \
      -c "\\dt" | grep -c "alembic_version" >/dev/null

    uv run alembic upgrade head
    uv run alembic upgrade head
  )
}

run_build_checks() {
  require_cmd docker

  local specs=(
    "api|apps/api/Dockerfile|"
    "web|apps/web/Dockerfile|"
    "worker|workflows/Dockerfile|"
    "compute|services/compute/Dockerfile|"
    "methods-preprocessing|methods/Dockerfile|preprocessing"
    "methods-dimreduction|methods/Dockerfile|dimensionality_reduction"
    "methods-annotation|methods/Dockerfile|annotation"
  )

  for spec in "${specs[@]}"; do
    IFS='|' read -r service dockerfile target <<<"$spec"
    log_section "Docker build validation: ${service}"

    build_args=(
      --file "$dockerfile"
      --tag "zerna/${service}:local-ci"
    )

    if [ -n "$target" ]; then
      build_args+=(--target "$target")
    fi

    docker build "${build_args[@]}" .
  done
}

case "$MODE" in
  quick)
    run_quick_checks
    ;;
  full)
    run_quick_checks
    run_integration_checks
    run_migration_checks
    run_build_checks
    ;;
  *)
    echo "Usage: $0 [quick|full]" >&2
    exit 1
    ;;
esac
