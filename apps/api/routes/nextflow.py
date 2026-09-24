"""
Nextflow integration routes.

Provides endpoints for:
  - POST /v1/nextflow/runs          — Temporal invokes Nextflow pipeline
  - GET  /v1/nextflow/runs/{run_id} — Temporal polls pipeline status
  - POST /v1/runs/{run_id}/progress — Nextflow emits step progress events

Requirements: 13.3, 4.17
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from zerna_contracts.enums import RunStatus
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_db
from apps.api.services.run_service import RunService
from services.compute.nextflow_client import NextflowClient, NextflowRunStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["nextflow"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class InvokeNextflowRequest(BaseModel):
    """Payload sent by the Temporal invoke_nextflow activity."""

    run_id: UUID
    dataset_s3_path: str
    parameters: dict[str, Any] = {}
    random_seed: int = 42


class InvokeNextflowResponse(BaseModel):
    run_id: UUID
    status: str
    output_path: str
    software_versions: dict[str, str] = {}
    error_message: str | None = None


class NextflowStatusResponse(BaseModel):
    run_id: UUID
    nextflow_status: str


class ProgressEventRequest(BaseModel):
    """Progress event emitted by the Nextflow EMIT_PROGRESS process."""

    step: str
    status: str
    metadata: dict[str, Any] = {}


class ProgressEventResponse(BaseModel):
    accepted: bool


# ---------------------------------------------------------------------------
# Dependency: NextflowClient
# ---------------------------------------------------------------------------


def get_nextflow_client() -> NextflowClient:
    """Provide a configured NextflowClient instance."""
    import os

    return NextflowClient(
        output_base=os.getenv("NEXTFLOW_OUTPUT_BASE", "s3://zerna-artifacts/runs"),
        control_plane_url=os.getenv("CONTROL_PLANE_URL", "http://localhost:8000"),
        control_plane_token=os.getenv("INTERNAL_API_TOKEN"),
        profile=os.getenv("NEXTFLOW_PROFILE", "local"),
    )


async def get_run_service(db: AsyncSession = Depends(get_db)) -> RunService:
    return RunService(db=db)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/nextflow/runs",
    response_model=InvokeNextflowResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Invoke Nextflow pipeline",
    description="Called by the Temporal RunExecutionWorkflow to launch a Nextflow pipeline.",
)
async def invoke_nextflow_run(
    request: InvokeNextflowRequest,
    nf_client: NextflowClient = Depends(get_nextflow_client),
    run_service: RunService = Depends(get_run_service),
) -> InvokeNextflowResponse:
    """
    Launch a Nextflow pipeline for the given run.

    The Temporal activity calls this endpoint instead of invoking Nextflow
    directly, keeping orchestration concerns in the Control Plane.
    """
    logger.info("Received Nextflow invocation request for run %s", request.run_id)

    result = await nf_client.launch(
        run_id=str(request.run_id),
        dataset_s3_path=request.dataset_s3_path,
        parameters=request.parameters,
        random_seed=request.random_seed,
    )

    # Propagate terminal status back to the run record
    if result.status == NextflowRunStatus.FAILED:
        await run_service.update_run_status(
            run_id=request.run_id,
            new_status=RunStatus.FAILED,
            error_message=result.error_message,
        )

    return InvokeNextflowResponse(
        run_id=request.run_id,
        status=result.status.value,
        output_path=result.output_path,
        software_versions=result.software_versions,
        error_message=result.error_message,
    )


@router.get(
    "/nextflow/runs/{run_id}",
    response_model=NextflowStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Poll Nextflow pipeline status",
    description="Called by the Temporal activity to check whether a pipeline has finished.",
)
async def get_nextflow_run_status(
    run_id: UUID,
    nf_client: NextflowClient = Depends(get_nextflow_client),
) -> NextflowStatusResponse:
    """Return the current Nextflow execution status for a run."""
    nf_status = await nf_client.get_status(str(run_id))
    return NextflowStatusResponse(run_id=run_id, nextflow_status=nf_status.value)


@router.post(
    "/runs/{run_id}/progress",
    response_model=ProgressEventResponse,
    status_code=status.HTTP_200_OK,
    summary="Receive pipeline progress event",
    description="Called by the Nextflow EMIT_PROGRESS process after each pipeline step.",
)
async def receive_progress_event(
    run_id: UUID,
    event: ProgressEventRequest,
    run_service: RunService = Depends(get_run_service),
) -> ProgressEventResponse:
    """
    Accept a progress event from the Nextflow pipeline and forward it to
    the RunService so the UI can display real-time step progress.
    """
    logger.info(
        "Progress event for run %s: step=%s status=%s",
        run_id,
        event.step,
        event.status,
    )

    try:
        await run_service.update_progress(
            run_id=run_id,
            progress_data={
                "step": event.step,
                "status": event.status,
                "metadata": event.metadata,
            },
        )
    except Exception as exc:
        # Progress events are best-effort; don't fail the pipeline
        logger.warning("Failed to store progress event for run %s: %s", run_id, exc)

    return ProgressEventResponse(accepted=True)
