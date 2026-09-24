#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Zerna Platform – Integration Test Runner
#
# Starts the integration test services (PostgreSQL, Redis, MinIO, Temporal),
# waits for them to become healthy, runs pytest with the integration marker,
# and tears everything down afterwards.
#
# Usage:
#   ./scripts/run_integration_tests.sh            # run all integration tests
#   ./scripts/run_integration_tests.sh -k "auth"  # pass extra pytest args
# ---------------------------------------------------------------------------
set -euo pipefail

COMPOSE_FILE="docker-compose.integration.yml"
PROJECT_NAME="zerna-integration"
MAX_WAIT_SECONDS=120

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Colour

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ---------------------------------------------------------------------------
# Cleanup handler – always tear down containers
# ---------------------------------------------------------------------------
cleanup() {
    info "Tearing down integration test services …"
    docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" down -v --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# 1. Start services
# ---------------------------------------------------------------------------
info "Starting integration test services …"
docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" up -d --wait --wait-timeout "$MAX_WAIT_SECONDS"

# ---------------------------------------------------------------------------
# 2. Wait for all services to be healthy
# ---------------------------------------------------------------------------
wait_for_service() {
    local name="$1"
    local host="$2"
    local port="$3"
    local elapsed=0

    info "Waiting for $name on $host:$port …"
    while ! nc -z "$host" "$port" 2>/dev/null; do
        sleep 1
        elapsed=$((elapsed + 1))
        if [ "$elapsed" -ge "$MAX_WAIT_SECONDS" ]; then
            error "$name did not become available within ${MAX_WAIT_SECONDS}s"
            exit 1
        fi
    done
    info "$name is ready."
}

wait_for_service "PostgreSQL"  localhost 5433
wait_for_service "Redis"       localhost 6380
wait_for_service "MinIO"       localhost 9002

# Temporal takes longer; give it extra time via the compose healthcheck
info "Waiting for Temporal (may take up to 60 s) …"
TEMPORAL_READY=0
for i in $(seq 1 "$MAX_WAIT_SECONDS"); do
    if nc -z localhost 7234 2>/dev/null; then
        TEMPORAL_READY=1
        break
    fi
    sleep 1
done
if [ "$TEMPORAL_READY" -eq 0 ]; then
    warn "Temporal did not become available – integration tests that need it may fail."
else
    info "Temporal is ready."
fi

# ---------------------------------------------------------------------------
# 3. Generate synthetic test data (if fixture doesn't exist yet)
# ---------------------------------------------------------------------------
FIXTURE_PATH="tests/integration/fixtures/synthetic_1k.h5ad"
if [ ! -f "$FIXTURE_PATH" ]; then
    info "Generating synthetic test data …"
    uv run python scripts/generate_test_data.py --output "$FIXTURE_PATH"
fi

# ---------------------------------------------------------------------------
# 4. Run integration tests
# ---------------------------------------------------------------------------
info "Running integration tests …"

# Export integration-specific env vars so the test process picks them up
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

TEST_EXIT_CODE=0
uv run pytest -m integration --tb=short -q "$@" || TEST_EXIT_CODE=$?

# ---------------------------------------------------------------------------
# 5. Report result
# ---------------------------------------------------------------------------
if [ "$TEST_EXIT_CODE" -eq 0 ]; then
    info "All integration tests passed ✓"
else
    error "Integration tests failed (exit code $TEST_EXIT_CODE)"
fi

exit "$TEST_EXIT_CODE"
