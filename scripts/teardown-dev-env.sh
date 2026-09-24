#!/usr/bin/env bash
# Zerna Platform - Development Environment Teardown Script
# This script stops and optionally removes all Docker resources

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

zerna_cd_repo_root

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}Zerna Platform - Environment Teardown${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

# Parse arguments
REMOVE_VOLUMES=false
if [ "${1:-}" = "--remove-volumes" ] || [ "${1:-}" = "-v" ]; then
    REMOVE_VOLUMES=true
    echo -e "${RED}WARNING: This will remove all data volumes!${NC}"
    read -r -p "Are you sure? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "Aborted."
        exit 0
    fi
fi

# Stop services
echo "Stopping Docker services..."
zerna_compose down

if [ "$REMOVE_VOLUMES" = true ]; then
    echo "Removing volumes..."
    zerna_compose down -v
    echo -e "${GREEN}✓ Services stopped and volumes removed${NC}"
else
    echo -e "${GREEN}✓ Services stopped (volumes preserved)${NC}"
fi

echo ""
echo "To remove volumes later, run:"
echo "  ./scripts/teardown-dev-env.sh --remove-volumes"
