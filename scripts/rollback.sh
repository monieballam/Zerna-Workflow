#!/usr/bin/env bash
set -euo pipefail

# ── Zerna ECS Rollback Script ───────────────────────────────────────────────
# ECS rollback helper. This is not the default EC2 Compose rollback path.
#
# Rolls back all ECS services to their previous task definition revision.
#
# Usage:
#   ./scripts/rollback.sh <environment> [--dry-run]
#
# Arguments:
#   environment   Target environment: staging or production
#   --dry-run     Show what would happen without making changes
#
# Examples:
#   ./scripts/rollback.sh staging
#   ./scripts/rollback.sh production --dry-run

# ── Globals ──────────────────────────────────────────────────────────────────
DRY_RUN=false
ENVIRONMENT=""
CLUSTER=""
SERVICES=(api web temporal worker)

# Parallel arrays for tracking rollback info per service
CURRENT_REVISIONS=()
PREVIOUS_TASK_DEF_ARNS=()

# ── Functions ────────────────────────────────────────────────────────────────

usage() {
  echo "Usage: $0 <environment> [--dry-run]"
  echo ""
  echo "This helper targets ECS services, not docker-compose.ec2.yml."
  echo ""
  echo "Arguments:"
  echo "  environment   staging or production"
  echo "  --dry-run     Show what would happen without making changes"
  exit 1
}

log() {
  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"
}

error() {
  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] ERROR: $*" >&2
}

parse_args() {
  if [[ $# -lt 1 ]]; then
    error "Missing required argument: environment"
    usage
  fi

  ENVIRONMENT="$1"
  shift

  if [[ "$ENVIRONMENT" != "staging" && "$ENVIRONMENT" != "production" ]]; then
    error "Invalid environment: ${ENVIRONMENT}. Must be 'staging' or 'production'."
    exit 1
  fi

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        DRY_RUN=true
        shift
        ;;
      *)
        error "Unknown argument: $1"
        usage
        ;;
    esac
  done

  CLUSTER="zerna-${ENVIRONMENT}-cluster"
}

get_previous_task_def() {
  local idx="$1"
  local service_name="${SERVICES[$idx]}"
  local full_service_name="zerna-${ENVIRONMENT}-${service_name}"

  log "Fetching current task definition for ${full_service_name}..."

  local current_task_def_arn
  current_task_def_arn=$(aws ecs describe-services \
    --cluster "$CLUSTER" \
    --services "$full_service_name" \
    --query "services[0].taskDefinition" \
    --output text)

  if [[ -z "$current_task_def_arn" || "$current_task_def_arn" == "None" ]]; then
    error "Could not retrieve task definition for service ${full_service_name}"
    exit 1
  fi

  # Extract the revision number from the ARN (e.g., ...task-definition/family:42 → 42)
  local current_revision
  current_revision=$(echo "$current_task_def_arn" | grep -oE ':[0-9]+$' | tr -d ':')

  if [[ -z "$current_revision" || "$current_revision" -le 1 ]]; then
    error "No previous revision available for ${full_service_name} (current revision: ${current_revision:-unknown})"
    exit 1
  fi

  local previous_revision=$((current_revision - 1))

  # Build the previous task definition ARN by replacing the revision number
  local previous_task_def_arn
  previous_task_def_arn=$(echo "$current_task_def_arn" | sed "s/:${current_revision}$/:${previous_revision}/")

  CURRENT_REVISIONS[$idx]="$current_revision"
  PREVIOUS_TASK_DEF_ARNS[$idx]="$previous_task_def_arn"

  log "  ${full_service_name}: revision ${current_revision} → ${previous_revision}"
}

rollback_service() {
  local idx="$1"
  local service_name="${SERVICES[$idx]}"
  local full_service_name="zerna-${ENVIRONMENT}-${service_name}"
  local previous_task_def="${PREVIOUS_TASK_DEF_ARNS[$idx]}"

  if [[ "$DRY_RUN" == true ]]; then
    log "[DRY RUN] Would update ${full_service_name} to ${previous_task_def}"
    return
  fi

  log "Rolling back ${full_service_name}..."
  aws ecs update-service \
    --cluster "$CLUSTER" \
    --service "$full_service_name" \
    --task-definition "$previous_task_def" \
    --output text > /dev/null

  log "  ${full_service_name} updated successfully."
}

wait_for_stability() {
  if [[ "$DRY_RUN" == true ]]; then
    log "[DRY RUN] Would wait for services to stabilize."
    return
  fi

  local full_service_names=()
  for svc in "${SERVICES[@]}"; do
    full_service_names+=("zerna-${ENVIRONMENT}-${svc}")
  done

  log "Waiting for all services to stabilize..."
  aws ecs wait services-stable \
    --cluster "$CLUSTER" \
    --services "${full_service_names[@]}"

  log "All services are stable."
}

print_summary() {
  echo ""
  echo "========================================="
  if [[ "$DRY_RUN" == true ]]; then
    echo "  ROLLBACK DRY RUN SUMMARY (${ENVIRONMENT})"
  else
    echo "  ROLLBACK SUMMARY (${ENVIRONMENT})"
  fi
  echo "========================================="
  echo ""
  printf "  %-12s  %-12s  %-12s\n" "SERVICE" "FROM REV" "TO REV"
  printf "  %-12s  %-12s  %-12s\n" "-------" "--------" "------"

  for i in "${!SERVICES[@]}"; do
    local svc="${SERVICES[$i]}"
    local current_rev="${CURRENT_REVISIONS[$i]}"
    local previous_rev=$((current_rev - 1))
    printf "  %-12s  %-12s  %-12s\n" "$svc" "$current_rev" "$previous_rev"
  done

  echo ""
  if [[ "$DRY_RUN" == true ]]; then
    echo "  No changes were made (dry run)."
  else
    echo "  Rollback complete. All services are stable."
  fi
  echo ""
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
  parse_args "$@"

  log "Starting rollback for environment: ${ENVIRONMENT} (cluster: ${CLUSTER})"
  if [[ "$DRY_RUN" == true ]]; then
    log "DRY RUN mode enabled — no changes will be made."
  fi
  echo ""

  # Step 1: Resolve previous task definitions for all services
  for i in "${!SERVICES[@]}"; do
    get_previous_task_def "$i"
  done
  echo ""

  # Step 2: Roll back each service
  for i in "${!SERVICES[@]}"; do
    rollback_service "$i"
  done
  echo ""

  # Step 3: Wait for stability
  wait_for_stability

  # Step 4: Print summary
  print_summary
}

main "$@"
