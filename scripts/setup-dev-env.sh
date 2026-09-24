#!/usr/bin/env bash
# Zerna Platform - Development Environment Setup Script
# This script initializes the Docker development environment

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

WITH_OBSERVABILITY=false

zerna_cd_repo_root

while [[ $# -gt 0 ]]; do
    case "$1" in
        --with-observability)
            WITH_OBSERVABILITY=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--with-observability]"
            echo ""
            echo "Options:"
            echo "  --with-observability  Start Jaeger, Prometheus, and Grafana in addition to core services"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown argument: $1${NC}"
            echo "Usage: $0 [--with-observability]"
            exit 1
            ;;
    esac
done

COMPOSE_PROFILE_ARGS=()
if [ "${WITH_OBSERVABILITY}" = true ]; then
    COMPOSE_PROFILE_ARGS=(--profile observability)
    export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://jaeger:4317}"
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Zerna Platform - Development Setup${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running${NC}"
    echo "Please start Docker and try again"
    exit 1
fi

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}No .env file found. Creating from .env.example...${NC}"
    cp .env.example .env
    echo -e "${GREEN}✓ Created .env file${NC}"
    echo -e "${YELLOW}Please review and update .env with your configuration${NC}"
    echo ""
fi

# Host ports for health checks (must match .env when MinIO ports are overridden)
POSTGRES_USER_VALUE="$(zerna_read_env POSTGRES_USER zerna)"
POSTGRES_PORT_VALUE="$(zerna_read_env POSTGRES_PORT 5432)"
REDIS_PORT_VALUE="$(zerna_read_env REDIS_PORT 6379)"
REDIS_PASSWORD_VALUE="$(zerna_read_env REDIS_PASSWORD zerna_redis_password)"
TEMPORAL_UI_PORT_VALUE="$(zerna_read_env TEMPORAL_UI_PORT 8080)"
MINIO_HEALTH_PORT="$(zerna_read_env MINIO_PORT 19000)"
MINIO_CONSOLE_URL_PORT="$(zerna_read_env MINIO_CONSOLE_PORT 19001)"
JAEGER_UI_PORT_VALUE="$(zerna_read_env JAEGER_UI_PORT 16686)"
PROMETHEUS_PORT_VALUE="$(zerna_read_env PROMETHEUS_PORT 9090)"
GRAFANA_PORT_VALUE="$(zerna_read_env GRAFANA_PORT 3001)"

compose() {
    if [[ ${#COMPOSE_PROFILE_ARGS[@]} -eq 0 ]]; then
        zerna_compose "$@"
    else
        zerna_compose "${COMPOSE_PROFILE_ARGS[@]}" "$@"
    fi
}

# Start Docker services
echo "Starting Docker services..."
compose up -d

echo ""
echo "Waiting for services to be healthy..."
echo -e "${YELLOW}This may take 30-60 seconds...${NC}"
echo ""

# Wait for PostgreSQL
echo -n "Waiting for PostgreSQL... "
until compose exec -T postgres pg_isready -U "${POSTGRES_USER_VALUE}" > /dev/null 2>&1; do
    sleep 2
done
echo -e "${GREEN}✓${NC}"

# Wait for Redis
echo -n "Waiting for Redis... "
until compose exec -T redis redis-cli -a "${REDIS_PASSWORD_VALUE}" ping > /dev/null 2>&1; do
    sleep 2
done
echo -e "${GREEN}✓${NC}"

# Wait for Temporal
echo -n "Waiting for Temporal... "
sleep 10  # Give Temporal extra time to initialize
echo -e "${GREEN}✓${NC}"

if [ "${WITH_OBSERVABILITY}" = true ]; then
    echo -n "Waiting for Jaeger... "
    until curl -s "http://localhost:${JAEGER_UI_PORT_VALUE}" > /dev/null 2>&1; do
        sleep 2
    done
    echo -e "${GREEN}✓${NC}"
fi

# Wait for MinIO
echo -n "Waiting for MinIO... "
until curl -s "http://localhost:${MINIO_HEALTH_PORT}/minio/health/live" > /dev/null 2>&1; do
    sleep 2
done
echo -e "${GREEN}✓${NC}"

echo ""
echo "Syncing Python workspace..."
zerna_uv_sync

echo ""
echo "Installing scientific R runtime dependencies..."
bash scripts/install-r-method-deps.sh

echo ""
# macOS: binary R Cairo often needs XQuartz (/opt/X11); pipelines use Docker worker R regardless.
if [[ "$(uname -s)" == "Darwin" && -z "${ZERNA_SKIP_R_VERIFY:-}" ]]; then
    if ! Rscript -e "quit(save='no', status=if (suppressWarnings(requireNamespace('Cairo', quietly=TRUE))) 0 else 1)" 2>/dev/null; then
        echo -e "${YELLOW}Host R Cairo is not loadable (typical without XQuartz). Skipping host R verify; Docker worker includes R.${NC}"
        export ZERNA_SKIP_R_VERIFY=1
    fi
fi
python3 scripts/verify_python_setup.py

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}All services are running!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Service URLs:"
echo "  PostgreSQL:      localhost:${POSTGRES_PORT_VALUE}"
echo "  Redis:           localhost:${REDIS_PORT_VALUE}"
echo "  Temporal UI:     http://localhost:${TEMPORAL_UI_PORT_VALUE}"
echo "  MinIO Console:   http://localhost:${MINIO_CONSOLE_URL_PORT}"
if [ "${WITH_OBSERVABILITY}" = true ]; then
    echo "  Jaeger UI:       http://localhost:${JAEGER_UI_PORT_VALUE}"
    echo "  Prometheus:      http://localhost:${PROMETHEUS_PORT_VALUE}"
    echo "  Grafana:         http://localhost:${GRAFANA_PORT_VALUE}"
fi
echo ""
echo "Default credentials:"
echo "  PostgreSQL:      zerna / zerna_dev_password"
echo "  Redis:           zerna_redis_password"
echo "  MinIO:           minioadmin / minioadmin"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Review and update .env file if needed"
echo "  2. Run database migrations: uv run --directory apps/api alembic upgrade head"
echo "  3. Start the API server: ./scripts/start-api.sh"
echo "  4. The worker is now available as a supervised Docker Compose service"
echo "     - Start or follow it: ./scripts/start-worker.sh"
echo "     - Local unsupervised mode: ./scripts/start-worker.sh --local"
echo "  5. Start the web app: pnpm --dir apps/web dev"
if [ "${WITH_OBSERVABILITY}" = false ]; then
    echo "  6. Optional observability stack: ./scripts/setup-dev-env.sh --with-observability"
fi
echo ""
echo -e "${GREEN}Setup complete!${NC}"
