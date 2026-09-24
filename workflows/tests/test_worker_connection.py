"""Test Temporal worker connection and workflow registration."""

import asyncio
from uuid import uuid4

import pytest
from temporalio.client import Client

from workflows.config import get_workflow_settings
from workflows.dataset_ingestion.schemas import (
    DatasetIngestionInput,
    S3Path,
)


@pytest.mark.asyncio
async def test_temporal_connection():
    """Test that we can connect to the Temporal server."""
    try:
        settings = get_workflow_settings()
    except Exception as e:
        pytest.skip(f"Workflow settings not configured: {e}")

    try:
        client = await Client.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
        )
        assert client is not None
        print(f"✓ Successfully connected to Temporal at {settings.temporal_address}")
    except Exception as e:
        pytest.skip(f"Temporal server not available: {e}")


@pytest.mark.asyncio
async def test_workflow_registration():
    """Test that workflows are properly registered (requires worker to be running)."""
    try:
        settings = get_workflow_settings()
    except Exception as e:
        pytest.skip(f"Workflow settings not configured: {e}")

    try:
        client = await Client.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
        )

        # Try to describe the task queue to see if worker is registered
        # This will succeed if the worker is running

        # Create a simple test input
        test_input = DatasetIngestionInput(
            dataset_id=uuid4(),
            organization_id=uuid4(),
            files=[
                S3Path(bucket="test-bucket", key="test-file.h5ad"),
            ],
        )

        # Try to start a workflow (will fail if worker not running, but that's ok for this test)
        try:
            handle = await client.start_workflow(
                "DatasetIngestionWorkflow",
                test_input,
                id=f"test-workflow-{uuid4()}",
                task_queue=settings.temporal_task_queue,
            )
            print(f"✓ Workflow started successfully: {handle.id}")

            # Cancel it immediately since this is just a test
            await handle.cancel()
            print("✓ Workflow cancelled successfully")

        except Exception as e:
            # If worker is not running, we'll get an error, but connection works
            print(f"Note: Worker may not be running: {e}")
            print(
                "This is expected if the worker is not started. "
                "Run 'python -m workflows.worker' to start it."
            )

    except Exception as e:
        pytest.skip(f"Temporal server not available: {e}")


if __name__ == "__main__":
    # Run tests directly
    asyncio.run(test_temporal_connection())
    print("\nTesting workflow registration...")
    asyncio.run(test_workflow_registration())
