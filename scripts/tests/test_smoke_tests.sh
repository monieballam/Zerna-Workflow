#!/usr/bin/env bash
set -euo pipefail

# ── Test suite for smoke-tests.sh ────────────────────────────────────────────
# Validates that the smoke test script handles various scenarios correctly.
#
# Usage:
#   ./scripts/tests/test_smoke_tests.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMOKE_SCRIPT="${SCRIPT_DIR}/smoke-tests.sh"
PASSED=0
FAILED=0

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

assert_exit_code() {
  local description="$1"
  local expected="$2"
  local actual="$3"

  if [ "$actual" -eq "$expected" ]; then
    echo -e "  ${GREEN}✓${NC} $description"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${RED}✗${NC} $description (expected exit $expected, got $actual)"
    FAILED=$((FAILED + 1))
  fi
}

assert_output_contains() {
  local description="$1"
  local expected="$2"
  local output="$3"

  if echo "$output" | grep -q "$expected"; then
    echo -e "  ${GREEN}✓${NC} $description"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${RED}✗${NC} $description (output missing: '$expected')"
    FAILED=$((FAILED + 1))
  fi
}

echo ""
echo "========================================="
echo "  Smoke Tests Script — Unit Tests"
echo "========================================="
echo ""

# ── Test 1: No arguments shows usage ────────────────────────────────────────
echo "Test 1: No arguments shows usage"
output=$("$SMOKE_SCRIPT" 2>&1 || true)
exit_code=$?
assert_exit_code "exits with 0 (usage)" 0 "$exit_code"
assert_output_contains "shows usage text" "Usage:" "$output"

# ── Test 2: Script is executable ─────────────────────────────────────────────
echo ""
echo "Test 2: Script is executable"
if [ -x "$SMOKE_SCRIPT" ]; then
  echo -e "  ${GREEN}✓${NC} smoke-tests.sh is executable"
  PASSED=$((PASSED + 1))
else
  echo -e "  ${RED}✗${NC} smoke-tests.sh is not executable"
  FAILED=$((FAILED + 1))
fi

# ── Test 3: Deploy script is executable ──────────────────────────────────────
echo ""
echo "Test 3: Deploy script is executable"
DEPLOY_SCRIPT="${SCRIPT_DIR}/deploy-production.sh"
if [ -x "$DEPLOY_SCRIPT" ]; then
  echo -e "  ${GREEN}✓${NC} deploy-production.sh is executable"
  PASSED=$((PASSED + 1))
else
  echo -e "  ${RED}✗${NC} deploy-production.sh is not executable"
  FAILED=$((FAILED + 1))
fi

# ── Test 4: Deploy script validates env vars ─────────────────────────────────
echo ""
echo "Test 4: Deploy script validates missing env vars"
output=$(env -u STAGING_API_URL -u STAGING_WEB_URL -u PRODUCTION_API_URL -u PRODUCTION_WEB_URL "$DEPLOY_SCRIPT" 2>&1 || true)
assert_output_contains "reports missing STAGING_API_URL" "STAGING_API_URL" "$output"
assert_output_contains "reports missing PRODUCTION_API_URL" "PRODUCTION_API_URL" "$output"

# ── Test 5: Deploy script --help shows usage ─────────────────────────────────
echo ""
echo "Test 5: Deploy script --help shows usage"
output=$("$DEPLOY_SCRIPT" --help 2>&1 || true)
assert_output_contains "shows usage text" "Usage:" "$output"
assert_output_contains "mentions --dry-run" "dry-run" "$output"
assert_output_contains "mentions --skip-staging-tests" "skip-staging-tests" "$output"

# ── Test 6: Smoke test with unreachable host fails gracefully ────────────────
echo ""
echo "Test 6: Smoke test with unreachable host"
export SMOKE_TEST_TIMEOUT=2
export SMOKE_TEST_RETRIES=1
export SMOKE_TEST_RETRY_DELAY=0
output=$("$SMOKE_SCRIPT" "http://localhost:19999" "http://localhost:19998" 2>&1 || true)
exit_code=$?
assert_output_contains "shows SMOKE TEST RESULTS" "SMOKE TEST RESULTS" "$output"
assert_output_contains "reports failures" "FAIL" "$output"
unset SMOKE_TEST_TIMEOUT SMOKE_TEST_RETRIES SMOKE_TEST_RETRY_DELAY

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "========================================="
echo "  Test Results"
echo "========================================="
echo ""
echo -e "  ${GREEN}Passed: ${PASSED}${NC}"
echo -e "  ${RED}Failed: ${FAILED}${NC}"
echo ""

if [ "$FAILED" -gt 0 ]; then
  echo -e "  ${RED}Some tests failed!${NC}"
  exit 1
else
  echo -e "  ${GREEN}All tests passed ✓${NC}"
  exit 0
fi
