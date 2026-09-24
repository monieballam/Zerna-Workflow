#!/usr/bin/env bash
set -euo pipefail

# ── Zerna Production Deployment Script ───────────────────────────────────────
# ECS-oriented deployment helper. This is not the default EC2 Compose path used
# by the current lightweight server deployment.
#
# Orchestrates a safe production deployment with pre-flight checks,
# staging validation, deployment trigger, and post-deploy verification.
#
# Usage:
#   ./scripts/deploy-production.sh [--skip-staging-tests] [--dry-run]
#
# Options:
#   --skip-staging-tests  Skip running integration tests against staging
#   --dry-run             Show what would happen without deploying
#
# Required environment variables:
#   STAGING_API_URL       — Staging API base URL (e.g. https://api.staging.zerna.example)
#   STAGING_WEB_URL       — Staging web app URL (e.g. https://staging.zerna.example)
#   PRODUCTION_API_URL    — Production API base URL (e.g. https://api.zerna.example)
#   PRODUCTION_WEB_URL    — Production web app URL (e.g. https://zerna.example)
#
# Optional environment variables:
#   GITHUB_REPO           — GitHub repo (owner/name) for workflow dispatch
#                           (default: auto-detected from git remote)
#   GITHUB_TOKEN          — GitHub PAT for triggering workflow dispatch
#   AWS_REGION            — AWS region (default: us-east-1)
#   ECS_CLUSTER           — ECS cluster name (default: zerna-production-cluster)

# ── Globals ──────────────────────────────────────────────────────────────────
SKIP_STAGING_TESTS=false
DRY_RUN=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
ECS_CLUSTER="${ECS_CLUSTER:-zerna-production-cluster}"
SERVICES=(api web temporal worker)

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Functions ────────────────────────────────────────────────────────────────

usage() {
  echo "Usage: $0 [--skip-staging-tests] [--dry-run]"
  echo ""
  echo "This helper targets the ECS deployment surface, not docker-compose.ec2.yml."
  echo ""
  echo "Options:"
  echo "  --skip-staging-tests  Skip integration tests against staging"
  echo "  --dry-run             Show what would happen without deploying"
  echo ""
  echo "Required environment variables:"
  echo "  STAGING_API_URL       Staging API base URL"
  echo "  STAGING_WEB_URL       Staging web app URL"
  echo "  PRODUCTION_API_URL    Production API base URL"
  echo "  PRODUCTION_WEB_URL    Production web app URL"
  exit 1
}

log() {
  echo -e "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"
}

info() {
  echo -e "${GREEN}[INFO]${NC}  $*"
}

warn() {
  echo -e "${YELLOW}[WARN]${NC}  $*"
}

error() {
  echo -e "${RED}[ERROR]${NC} $*" >&2
}

step() {
  echo ""
  echo -e "${CYAN}━━━ $* ━━━${NC}"
  echo ""
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --skip-staging-tests)
        SKIP_STAGING_TESTS=true
        shift
        ;;
      --dry-run)
        DRY_RUN=true
        shift
        ;;
      --help|-h)
        usage
        ;;
      *)
        error "Unknown argument: $1"
        usage
        ;;
    esac
  done
}

validate_env() {
  local missing=()

  [ -z "${STAGING_API_URL:-}" ]    && missing+=("STAGING_API_URL")
  [ -z "${STAGING_WEB_URL:-}" ]    && missing+=("STAGING_WEB_URL")
  [ -z "${PRODUCTION_API_URL:-}" ] && missing+=("PRODUCTION_API_URL")
  [ -z "${PRODUCTION_WEB_URL:-}" ] && missing+=("PRODUCTION_WEB_URL")

  if [ ${#missing[@]} -gt 0 ]; then
    error "Missing required environment variables:"
    for var in "${missing[@]}"; do
      echo "  - $var"
    done
    echo ""
    echo "Set them before running this script, e.g.:"
    echo "  export STAGING_API_URL=https://api.staging.zerna.example"
    echo "  export STAGING_WEB_URL=https://staging.zerna.example"
    echo "  export PRODUCTION_API_URL=https://api.zerna.example"
    echo "  export PRODUCTION_WEB_URL=https://zerna.example"
    exit 1
  fi
}

# ── Step 1: Pre-flight checks ───────────────────────────────────────────────

preflight_checks() {
  step "Step 1: Pre-flight checks"

  # Check required tools
  for cmd in curl aws; do
    if command -v "$cmd" &>/dev/null; then
      info "$cmd is available"
    else
      error "$cmd is not installed or not in PATH"
      exit 1
    fi
  done

  # Verify AWS credentials
  if aws sts get-caller-identity &>/dev/null; then
    local account_id
    account_id=$(aws sts get-caller-identity --query "Account" --output text)
    info "AWS credentials valid (account: $account_id)"
  else
    error "AWS credentials are not configured or expired"
    error "Run 'aws configure' or set AWS_PROFILE"
    exit 1
  fi

  # Verify ECS cluster exists
  if aws ecs describe-clusters --clusters "$ECS_CLUSTER" --region "$AWS_REGION" \
       --query "clusters[0].status" --output text 2>/dev/null | grep -q "ACTIVE"; then
    info "ECS cluster '$ECS_CLUSTER' is active"
  else
    warn "Could not verify ECS cluster '$ECS_CLUSTER' — deployment may fail"
  fi

  info "Pre-flight checks passed"
}

# ── Step 2: Run staging smoke tests ─────────────────────────────────────────

run_staging_tests() {
  step "Step 2: Staging validation"

  if [ "$SKIP_STAGING_TESTS" = true ]; then
    warn "Skipping staging tests (--skip-staging-tests)"
    return 0
  fi

  info "Running smoke tests against staging..."
  info "  API: ${STAGING_API_URL}"
  info "  Web: ${STAGING_WEB_URL}"

  if [ "$DRY_RUN" = true ]; then
    info "[DRY RUN] Would run: ${SCRIPT_DIR}/smoke-tests.sh ${STAGING_API_URL} ${STAGING_WEB_URL}"
    return 0
  fi

  if "${SCRIPT_DIR}/smoke-tests.sh" "${STAGING_API_URL}" "${STAGING_WEB_URL}"; then
    info "Staging smoke tests passed ✓"
  else
    error "Staging smoke tests failed!"
    error "Fix staging issues before deploying to production."
    exit 1
  fi
}

# ── Step 3: Deploy to production ─────────────────────────────────────────────

deploy_to_production() {
  step "Step 3: Deploy to production"

  if [ "$DRY_RUN" = true ]; then
    info "[DRY RUN] Would deploy the following services to ${ECS_CLUSTER}:"
    for svc in "${SERVICES[@]}"; do
      info "  - zerna-production-${svc}"
    done
    return 0
  fi

  # Check if GITHUB_TOKEN is set for workflow dispatch
  if [ -n "${GITHUB_TOKEN:-}" ] && [ -n "${GITHUB_REPO:-}" ]; then
    info "Triggering deployment via GitHub Actions workflow dispatch..."
    local http_status
    http_status=$(curl -s -o /dev/null -w "%{http_code}" \
      -X POST \
      -H "Accept: application/vnd.github.v3+json" \
      -H "Authorization: token ${GITHUB_TOKEN}" \
      "https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/cd-deploy.yml/dispatches" \
      -d '{"ref":"main","inputs":{"environment":"production"}}')

    if [ "$http_status" = "204" ]; then
      info "GitHub Actions workflow dispatch triggered successfully"
      info "Monitor the deployment at: https://github.com/${GITHUB_REPO}/actions"
      info "Waiting 60s for deployment to start..."
      sleep 60
    else
      warn "GitHub Actions dispatch returned HTTP $http_status"
      warn "Falling back to direct ECS deployment..."
      deploy_ecs_direct
    fi
  else
    info "No GITHUB_TOKEN/GITHUB_REPO set — deploying directly via ECS..."
    deploy_ecs_direct
  fi
}

deploy_ecs_direct() {
  for svc in "${SERVICES[@]}"; do
    local full_name="zerna-production-${svc}"
    info "Deploying ${full_name}..."
    aws ecs update-service \
      --cluster "$ECS_CLUSTER" \
      --service "$full_name" \
      --force-new-deployment \
      --region "$AWS_REGION" \
      --output text > /dev/null
    info "  ${full_name} deployment initiated"
  done

  info "Waiting for all services to stabilize..."
  local full_service_names=()
  for svc in "${SERVICES[@]}"; do
    full_service_names+=("zerna-production-${svc}")
  done

  aws ecs wait services-stable \
    --cluster "$ECS_CLUSTER" \
    --services "${full_service_names[@]}" \
    --region "$AWS_REGION"

  info "All services are stable ✓"
}

# ── Step 4: Verify health checks ────────────────────────────────────────────

verify_health_checks() {
  step "Step 4: Verify health checks"

  if [ "$DRY_RUN" = true ]; then
    info "[DRY RUN] Would verify health checks for all services"
    return 0
  fi

  local all_healthy=true

  for svc in "${SERVICES[@]}"; do
    local full_name="zerna-production-${svc}"
    info "Checking ECS service health: ${full_name}..."

    local desired running
    desired=$(aws ecs describe-services \
      --cluster "$ECS_CLUSTER" \
      --services "$full_name" \
      --region "$AWS_REGION" \
      --query "services[0].desiredCount" \
      --output text 2>/dev/null || echo "0")

    running=$(aws ecs describe-services \
      --cluster "$ECS_CLUSTER" \
      --services "$full_name" \
      --region "$AWS_REGION" \
      --query "services[0].runningCount" \
      --output text 2>/dev/null || echo "0")

    if [ "$desired" = "$running" ] && [ "$running" != "0" ]; then
      info "  ${full_name}: ${running}/${desired} tasks running ✓"
    else
      error "  ${full_name}: ${running}/${desired} tasks running ✗"
      all_healthy=false
    fi
  done

  if [ "$all_healthy" = false ]; then
    error "Not all services are healthy!"
    print_rollback_instructions
    exit 1
  fi

  info "All ECS service health checks passed ✓"
}

# ── Step 5: Run production smoke tests ───────────────────────────────────────

run_production_smoke_tests() {
  step "Step 5: Production smoke tests"

  if [ "$DRY_RUN" = true ]; then
    info "[DRY RUN] Would run: ${SCRIPT_DIR}/smoke-tests.sh ${PRODUCTION_API_URL} ${PRODUCTION_WEB_URL}"
    return 0
  fi

  info "Running smoke tests against production..."
  info "  API: ${PRODUCTION_API_URL}"
  info "  Web: ${PRODUCTION_WEB_URL}"

  if "${SCRIPT_DIR}/smoke-tests.sh" "${PRODUCTION_API_URL}" "${PRODUCTION_WEB_URL}"; then
    info "Production smoke tests passed ✓"
  else
    error "Production smoke tests failed!"
    print_rollback_instructions
    exit 1
  fi
}

# ── Rollback instructions ────────────────────────────────────────────────────

print_rollback_instructions() {
  echo ""
  echo -e "${RED}=========================================${NC}"
  echo -e "${RED}  DEPLOYMENT FAILED — ROLLBACK REQUIRED${NC}"
  echo -e "${RED}=========================================${NC}"
  echo ""
  echo "  Run the rollback script to revert to the previous deployment:"
  echo ""
  echo "    ./scripts/rollback.sh production"
  echo ""
  echo "  Or do a dry run first:"
  echo ""
  echo "    ./scripts/rollback.sh production --dry-run"
  echo ""
  echo "  Monitor services after rollback:"
  echo ""
  echo "    aws ecs describe-services \\"
  echo "      --cluster ${ECS_CLUSTER} \\"
  echo "      --services zerna-production-api zerna-production-web \\"
  echo "        zerna-production-temporal zerna-production-worker \\"
  echo "      --query 'services[].{name:serviceName,status:status,running:runningCount,desired:desiredCount}' \\"
  echo "      --output table"
  echo ""
}

# ── Summary ──────────────────────────────────────────────────────────────────

print_summary() {
  echo ""
  echo -e "${GREEN}=========================================${NC}"
  if [ "$DRY_RUN" = true ]; then
    echo -e "${GREEN}  PRODUCTION DEPLOYMENT DRY RUN COMPLETE${NC}"
  else
    echo -e "${GREEN}  PRODUCTION DEPLOYMENT SUCCESSFUL ✓${NC}"
  fi
  echo -e "${GREEN}=========================================${NC}"
  echo ""
  echo "  Environment:  production"
  echo "  ECS Cluster:  ${ECS_CLUSTER}"
  echo "  API URL:      ${PRODUCTION_API_URL}"
  echo "  Web URL:      ${PRODUCTION_WEB_URL}"
  echo ""
  echo "  Services deployed:"
  for svc in "${SERVICES[@]}"; do
    echo "    - zerna-production-${svc}"
  done
  echo ""
  if [ "$DRY_RUN" = false ]; then
    echo "  Post-deployment monitoring:"
    echo "    - Grafana dashboards for API latency, error rates"
    echo "    - CloudWatch Logs for service logs"
    echo "    - Jaeger for distributed tracing"
    echo ""
    echo "  If issues arise, rollback with:"
    echo "    ./scripts/rollback.sh production"
  fi
  echo ""
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
  parse_args "$@"
  validate_env

  echo ""
  echo "========================================="
  echo "  Zerna Production Deployment"
  echo "========================================="
  echo ""
  if [ "$DRY_RUN" = true ]; then
    warn "DRY RUN mode — no changes will be made"
    echo ""
  fi
  echo "  Staging API:     ${STAGING_API_URL}"
  echo "  Staging Web:     ${STAGING_WEB_URL}"
  echo "  Production API:  ${PRODUCTION_API_URL}"
  echo "  Production Web:  ${PRODUCTION_WEB_URL}"
  echo "  ECS Cluster:     ${ECS_CLUSTER}"
  echo ""

  # Step 1: Pre-flight checks
  preflight_checks

  # Step 2: Run staging smoke tests
  run_staging_tests

  # Step 3: Deploy to production
  deploy_to_production

  # Step 4: Verify health checks
  verify_health_checks

  # Step 5: Run production smoke tests
  run_production_smoke_tests

  # Done
  print_summary
}

main "$@"
