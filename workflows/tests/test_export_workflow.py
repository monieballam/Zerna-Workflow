"""Test ExportWorkflow activities and workflow execution."""

import asyncio
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_export_workflow_structure():
    """Test that export workflow has the correct structure."""
    from workflows.export.workflow import ExportWorkflow

    # Verify the workflow class exists
    assert ExportWorkflow is not None

    # Verify the workflow has the run method
    assert hasattr(ExportWorkflow, "run")

    # Verify the workflow has compensation logic
    assert hasattr(ExportWorkflow, "_cleanup_partial_export")

    print("✓ ExportWorkflow has correct structure with compensation logic")


@pytest.mark.asyncio
async def test_export_schemas():
    """Test that export schemas are properly defined."""
    from workflows.export.schemas import ExportInput, ExportOutput, ExportStatus

    # Create test input
    test_input = ExportInput(
        export_id=uuid4(),
        run_id=uuid4(),
        include_provenance=True,
    )

    assert test_input.export_id is not None
    assert test_input.run_id is not None
    assert test_input.include_provenance is True

    # Create test output
    test_output = ExportOutput(
        export_id=uuid4(),
        status=ExportStatus.COMPLETED,
        h5ad_url="https://example.com/data.h5ad",
        report_url="https://example.com/report.html",
        error_message=None,
    )

    assert test_output.status == ExportStatus.COMPLETED
    assert test_output.h5ad_url is not None
    assert test_output.report_url is not None

    print("✓ Export schemas are properly defined")


if __name__ == "__main__":
    # Run tests directly
    print("Testing export workflow structure...")
    asyncio.run(test_export_workflow_structure())
    print("\nTesting export schemas...")
    asyncio.run(test_export_schemas())
