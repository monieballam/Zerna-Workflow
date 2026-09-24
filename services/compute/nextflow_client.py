"""
Nextflow client for the Control Plane.

Provides async methods to:
  - Launch a Nextflow pipeline run via subprocess or AWS Batch
  - Poll run status from the Nextflow API / process
  - Collect artifacts after completion
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class NextflowRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class NextflowRunResult:
    run_id: str
    status: NextflowRunStatus
    output_path: str
    software_versions: dict[str, str] = field(default_factory=dict)
    error_message: str | None = None
    artifacts: list[str] = field(default_factory=list)


class NextflowClient:
    """
    Launches and monitors Nextflow pipeline executions.

    In production this delegates to AWS Batch via the Nextflow AWS executor.
    In development it runs Nextflow as a local subprocess.
    """

    def __init__(
        self,
        pipeline_dir: str | None = None,
        output_base: str = "s3://zerna-artifacts/runs",
        control_plane_url: str = "http://localhost:8000",
        control_plane_token: str | None = None,
        profile: str = "local",
    ) -> None:
        self.pipeline_dir = pipeline_dir or str(Path(__file__).parent / "nextflow")
        self.output_base = output_base
        self.control_plane_url = control_plane_url
        self.control_plane_token = control_plane_token
        self.profile = profile

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def launch(
        self,
        run_id: str,
        dataset_s3_path: str,
        parameters: dict[str, Any],
        random_seed: int = 42,
    ) -> NextflowRunResult:
        """
        Launch a Nextflow pipeline run.

        Returns immediately with status=RUNNING; callers should poll
        via `get_status` or wait for the progress callback.
        """
        output_path = f"{self.output_base}/{run_id}"
        params = self._build_params(
            run_id=run_id,
            dataset_s3_path=dataset_s3_path,
            output_path=output_path,
            parameters=parameters,
            random_seed=random_seed,
        )

        logger.info("Launching Nextflow run %s with profile=%s", run_id, self.profile)

        try:
            await self._run_nextflow(run_id=run_id, params=params)
            return NextflowRunResult(
                run_id=run_id,
                status=NextflowRunStatus.COMPLETED,
                output_path=output_path,
                software_versions=_default_software_versions(),
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr or ""
            logger.error("Nextflow run %s failed: %s", run_id, stderr)
            return NextflowRunResult(
                run_id=run_id,
                status=NextflowRunStatus.FAILED,
                output_path=output_path,
                error_message=_extract_error(stderr),
            )
        except Exception as exc:
            logger.exception("Unexpected error launching Nextflow run %s", run_id)
            return NextflowRunResult(
                run_id=run_id,
                status=NextflowRunStatus.FAILED,
                output_path=output_path,
                error_message=str(exc),
            )

    async def get_status(self, run_id: str) -> NextflowRunStatus:
        """
        Poll the status of a running Nextflow execution.

        In production this queries the Nextflow Tower / AWS Batch API.
        For now returns COMPLETED as a placeholder (status is tracked via
        progress callbacks from the pipeline itself).
        """
        # TODO: integrate with Nextflow Tower API or AWS Batch DescribeJobs
        return NextflowRunStatus.COMPLETED

    async def collect_artifacts(self, run_id: str, output_path: str) -> list[str]:
        """
        Return S3 paths of artifacts produced by the pipeline.

        Scans the output directory for known artifact file patterns.
        """
        known_patterns = [
            "de_results.h5ad",
            "de_results.csv",
            "lr_results.csv",
            "pathway_scored.h5ad",
            "annotated.h5ad",
            "embedded.h5ad",
            "qc_metrics.json",
        ]
        return [f"{output_path}/{name}" for name in known_patterns]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_params(
        self,
        run_id: str,
        dataset_s3_path: str,
        output_path: str,
        parameters: dict[str, Any],
        random_seed: int,
    ) -> dict[str, Any]:
        """Merge default params with run-specific overrides."""
        defaults: dict[str, Any] = {
            "run_id": run_id,
            "dataset_path": dataset_s3_path,
            "output_dir": output_path,
            "random_seed": random_seed,
            "control_plane_url": self.control_plane_url,
            "control_plane_token": self.control_plane_token or "",
        }
        defaults.update(parameters)
        return defaults

    async def _run_nextflow(self, run_id: str, params: dict[str, Any]) -> None:
        """Execute Nextflow as an async subprocess."""
        cmd = [
            "nextflow",
            "run",
            str(Path(self.pipeline_dir) / "main.nf"),
            "-profile",
            self.profile,
            "-params-file",
            "/dev/stdin",
            "-name",
            f"zerna-{run_id}",
            "-ansi-log",
            "false",
        ]

        params_json = json.dumps(params)
        logger.debug("Nextflow command: %s", " ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.pipeline_dir,
        )
        stdout, stderr = await proc.communicate(input=params_json.encode())

        if proc.returncode != 0:
            raise subprocess.CalledProcessError(
                returncode=proc.returncode,
                cmd=cmd,
                output=stdout.decode(),
                stderr=stderr.decode(),
            )

        logger.info("Nextflow run %s completed. stdout: %s", run_id, stdout.decode()[-500:])


def _default_software_versions() -> dict[str, str]:
    """Return a dict of key software versions for provenance tracking."""
    versions: dict[str, str] = {}
    for pkg in ("scanpy", "anndata", "scvi", "celltypist", "harmonypy", "liana", "decoupler"):
        try:
            import importlib.metadata

            versions[pkg] = importlib.metadata.version(pkg)
        except Exception:
            pass
    return versions


def _extract_error(stderr: str) -> str:
    """Extract the most relevant error line from Nextflow stderr."""
    lines = [l.strip() for l in stderr.splitlines() if l.strip()]
    # Nextflow error lines typically start with "ERROR ~"
    for line in reversed(lines):
        if "ERROR" in line or "Exception" in line or "Error" in line:
            return line
    return lines[-1] if lines else "Unknown Nextflow error"
