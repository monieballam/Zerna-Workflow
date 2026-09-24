#!/usr/bin/env bash
set -euo pipefail

# ── Zerna Smoke Tests ───────────────────────────────────────────────────────
# Runs smoke tests against a target environment to verify core services
# are operational after deployment.
#
# Usage:
#   ./scripts/smoke-tests.sh <api_url> <web_url>
#   ./scripts/smoke-tests.sh https://api.staging.zerna.example https://staging.zerna.example
#
# Environment variables (optional):
#   SMOKE_TEST_TIMEOUT   — curl timeout in seconds (default: 30)
#   SMOKE_TEST_RETRIES   — number of retries per check (default: 3)
#   SMOKE_TEST_RETRY_DELAY — delay between retries in seconds (default: 10)

# ── Globals ──────────────────────────────────────────────────────────────────
API_URL=""
WEB_URL=""
TIMEOUT="${SMOKE_TEST_TIMEOUT:-30}"
RETRIES="${SMOKE_TEST_RETRIES:-3}"
RETRY_DELAY="${SMOKE_TEST_RETRY_DELAY:-10}"
PASSED=0
FAILED=0
TOTAL=0

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── Functions ────────────────────────────────────────────────────────────────

usage() {
  echo "Usage: $0 <api_url> <web_url>"
  echo ""
  echo "Arguments:"
  echo "  api_url   Base URL for the API (e.g. https://api.zerna.example)"
  echo "  web_url   Base URL for the web app (e.g. https://zerna.example)"
  echo ""
  echo "Environment variables:"
  echo "  SMOKE_TEST_TIMEOUT      curl timeout in seconds (default: 30)"
  echo "  SMOKE_TEST_RETRIES      number of retries per check (default: 3)"
  echo "  SMOKE_TEST_RETRY_DELAY  delay between retries in seconds (default: 10)"
  exit 1
}

log_pass() {
  echo -e "  ${GREEN}✓ PASS${NC}  $*"
  PASSED=$((PASSED + 1))
  TOTAL=$((TOTAL + 1))
}

log_fail() {
  echo -e "  ${RED}✗ FAIL${NC}  $*"
  FAILED=$((FAILED + 1))
  TOTAL=$((TOTAL + 1))
}

log_info() {
  echo -e "${YELLOW}[INFO]${NC} $*"
}

# Perform an HTTP check with retries.
# Arguments: <description> <url> <expected_status>
http_check() {
  local description="$1"
  local url="$2"
  local expected_statuses="$3"

  for attempt in $(seq 1 "$RETRIES"); do
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$url" 2>/dev/null || echo "000")

    if [[ " ${expected_statuses} " == *" ${status} "* ]]; then
      log_pass "$description (HTTP $status)"
      return 0
    fi

    if [ "$attempt" -lt "$RETRIES" ]; then
      echo -e "    ${YELLOW}↻${NC} Attempt $attempt/$RETRIES failed (HTTP $status), retrying in ${RETRY_DELAY}s..."
      sleep "$RETRY_DELAY"
    fi
  done

  log_fail "$description (expected HTTP ${expected_statuses}, got HTTP $status)"
  return 1
}

# Perform an HTTP check and validate JSON response body contains a key.
# Arguments: <description> <url> <expected_status> <json_key>
http_check_json() {
  local description="$1"
  local url="$2"
  local expected_status="$3"
  local json_key="$4"

  for attempt in $(seq 1 "$RETRIES"); do
    local response_file
    response_file=$(mktemp)

    local status
    status=$(curl -s -o "$response_file" -w "%{http_code}" --max-time "$TIMEOUT" "$url" 2>/dev/null || echo "000")

    if [ "$status" = "$expected_status" ]; then
      # Check if the response body contains the expected key
      if grep -q "\"$json_key\"" "$response_file" 2>/dev/null; then
        log_pass "$description (HTTP $status, key '$json_key' present)"
        rm -f "$response_file"
        return 0
      else
        log_fail "$description (HTTP $status but missing key '$json_key')"
        rm -f "$response_file"
        return 1
      fi
    fi

    rm -f "$response_file"

    if [ "$attempt" -lt "$RETRIES" ]; then
      echo -e "    ${YELLOW}↻${NC} Attempt $attempt/$RETRIES failed (HTTP $status), retrying in ${RETRY_DELAY}s..."
      sleep "$RETRY_DELAY"
    fi
  done

  log_fail "$description (expected HTTP $expected_status, got HTTP $status)"
  return 1
}

parse_args() {
  if [ $# -lt 2 ]; then
    usage
  fi
  API_URL="${1%/}"  # strip trailing slash
  WEB_URL="${2%/}"
}

# ── Smoke Test Suites ────────────────────────────────────────────────────────

run_api_health_checks() {
  log_info "Running API health checks..."

  http_check "API /health endpoint" "${API_URL}/health" "200" || true
  http_check_json "API /health returns status" "${API_URL}/health" "200" "status" || true
  http_check "API /v1/health versioned endpoint" "${API_URL}/v1/health" "200" || true
}

run_web_app_checks() {
  log_info "Running web app checks..."

  http_check "Web app root page or auth redirect" "${WEB_URL}/" "200 307 308" || true
}

run_auth_checks() {
  log_info "Running auth endpoint checks..."

  # Auth endpoints should exist and respond (401 for unauthenticated is expected)
  http_check "Auth login endpoint exists" "${API_URL}/v1/auth/login" "405" || \
  http_check "Auth login endpoint exists (POST expected)" "${API_URL}/v1/auth/login" "422" || true
}

run_dataset_checks() {
  log_info "Running dataset endpoint checks..."

  # Unauthenticated requests should return 401/403
  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "${API_URL}/v1/datasets" 2>/dev/null || echo "000")

  if [ "$status" = "401" ] || [ "$status" = "403" ]; then
    log_pass "Dataset listing requires authentication (HTTP $status)"
  elif [ "$status" = "200" ]; then
    log_pass "Dataset listing endpoint responds (HTTP $status)"
  else
    log_fail "Dataset listing endpoint unexpected response (HTTP $status)"
  fi
  TOTAL=$((TOTAL))  # already counted above
}

run_runs_checks() {
  log_info "Running run endpoint checks..."

  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "${API_URL}/v1/runs" 2>/dev/null || echo "000")

  if [ "$status" = "401" ] || [ "$status" = "403" ]; then
    log_pass "Run listing requires authentication (HTTP $status)"
  elif [ "$status" = "200" ]; then
    log_pass "Run listing endpoint responds (HTTP $status)"
  else
    log_fail "Run listing endpoint unexpected response (HTTP $status)"
  fi
}

print_summary() {
  echo ""
  echo "========================================="
  echo "  SMOKE TEST RESULTS"
  echo "========================================="
  echo ""
  echo "  API URL:  ${API_URL}"
  echo "  Web URL:  ${WEB_URL}"
  echo ""
  echo -e "  Total:  ${TOTAL}"
  echo -e "  ${GREEN}Passed: ${PASSED}${NC}"
  echo -e "  ${RED}Failed: ${FAILED}${NC}"
  echo ""

  if [ "$FAILED" -gt 0 ]; then
    echo -e "  ${RED}Some smoke tests failed!${NC}"
    echo ""
    return 1
  else
    echo -e "  ${GREEN}All smoke tests passed ✓${NC}"
    echo ""
    return 0
  fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
  parse_args "$@"

  echo ""
  echo "========================================="
  echo "  Zerna Smoke Tests"
  echo "========================================="
  echo ""
  echo "  API: ${API_URL}"
  echo "  Web: ${WEB_URL}"
  echo "  Timeout: ${TIMEOUT}s | Retries: ${RETRIES} | Delay: ${RETRY_DELAY}s"
  echo ""

  run_api_health_checks
  echo ""
  run_web_app_checks
  echo ""
  run_auth_checks
  echo ""
  run_dataset_checks
  echo ""
  run_runs_checks
  echo ""

  print_summary
}

main "$@"
