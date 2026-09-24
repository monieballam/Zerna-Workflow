#!/usr/bin/env bash
# Test script to verify Temporal setup is working correctly

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

zerna_cd_repo_root

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Zerna Temporal Setup Verification${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Test 1: Check if docker compose is available
echo -e "${YELLOW}[1/6] Checking docker compose...${NC}"
if ! docker compose version &> /dev/null; then
    echo -e "${RED}✗ docker compose not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ docker compose is available${NC}"
echo ""

# Test 2: Check if Temporal service is defined
echo -e "${YELLOW}[2/6] Checking Temporal service in docker compose...${NC}"
if ! zerna_compose config --services | grep -q "temporal"; then
    echo -e "${RED}✗ Temporal service not found in the compose configuration${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Temporal service is defined${NC}"
echo ""

# Test 3: Check if Temporal is running
echo -e "${YELLOW}[3/6] Checking if Temporal is running...${NC}"
if ! zerna_compose ps temporal | grep -q "Up"; then
    echo -e "${RED}✗ Temporal is not running${NC}"
    echo -e "${YELLOW}Start it with: docker compose up -d temporal${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Temporal is running${NC}"
echo ""

# Test 4: Check Temporal health
echo -e "${YELLOW}[4/6] Checking Temporal health...${NC}"
if ! zerna_compose exec -T temporal tctl cluster health &>/dev/null; then
    echo -e "${RED}✗ Temporal is not healthy${NC}"
    echo -e "${YELLOW}Check logs with: docker compose logs temporal${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Temporal is healthy${NC}"
echo ""

# Test 5: Check if worker runtime modules import
echo -e "${YELLOW}[5/6] Checking worker imports...${NC}"
if ! PYTHONPATH=. uv run python -c "
from workflows.worker import WorkerManager
from workflows.run_execution.activities import execute_pipeline
from methods.preprocessing.doublet_detection import DoubletDetectionMethod
print('OK')
" &>/dev/null; then
    echo -e "${RED}✗ Worker imports failed${NC}"
    echo -e "${YELLOW}Check Python dependencies: uv sync${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Worker imports successfully${NC}"
echo ""

# Test 6: Check if workflows can import
echo -e "${YELLOW}[6/6] Checking workflow imports...${NC}"
if ! PYTHONPATH=. uv run python -c "
from workflows.dataset_ingestion.workflow import DatasetIngestionWorkflow
from workflows.run_execution.workflow import RunExecutionWorkflow
from workflows.export.workflow import ExportWorkflow
print('OK')
" &>/dev/null; then
    echo -e "${RED}✗ Workflow imports failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ All workflows import successfully${NC}"
echo ""

# Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✓ All checks passed!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo -e "  1. Start the worker: ${BLUE}./scripts/start-worker.sh${NC}"
echo -e "  2. View Temporal UI: ${BLUE}http://localhost:8080${NC}"
echo -e "  3. Run tests: ${BLUE}PYTHONPATH=. uv run pytest workflows/tests/${NC}"
echo ""
