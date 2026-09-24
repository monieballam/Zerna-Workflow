"""Run service for pipeline run lifecycle management."""

import asyncio
import logging
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from zerna_contracts.enums import RunStatus
from zerna_contracts.run_manifest import RunManifest
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from apps.api.models.dataset import DatasetVersion
from apps.api.models.organization import OrganizationUser
from apps.api.models.pipeline import Artifact, PipelineTemplate, Run
from apps.api.services.audit_service import AuditService
from apps.api.services.cache_service import CacheService, CacheTTL
from apps.api.services.dataset_service import DatasetService
from apps.api.services.pipeline_service import PipelineService
from apps.api.services.quota_service import QuotaService
from apps.api.services.s3_service import S3Service

logger = logging.getLogger(__name__)
CHECKPOINTS_PARAMETER_KEY = "_checkpoints"
EXECUTION_STATE_PARAMETER_KEY = "_execution_state"


class RunService:
    """Service for run lifecycle management with parameter validation."""

    def __init__(
        self,
        db: AsyncSession,
        pipeline_service: PipelineService | None = None,
        cache_service: CacheService | None = None,
        audit_service: AuditService | None = None,
        s3_service: S3Service | None = None,
    ):
        """Initialize RunService.

        Args:
            db: Database session
            pipeline_service: Pipeline service for parameter validation (optional, created if not provided)
            cache_service: Cache service for Redis caching (optional, no caching if not provided)
            audit_service: Audit service for compliance logging (optional, created if not provided)
        """
        self.db = db
        self.pipeline_service = pipeline_service or PipelineService(db)
        self.quota_service = QuotaService(db)
        self.cache = cache_service
        self.audit = audit_service or AuditService(db)
        self._s3_service = s3_service

    @property
    def s3_service(self) -> S3Service:
        """Lazily construct S3Service so tests that do not need it stay lightweight."""
        if self._s3_service is None:
            self._s3_service = S3Service()
        return self._s3_service

    @staticmethod
    def _resolve_dataset_column(
        requested: Any,
        options: list[str],
    ) -> str | None:
        """Resolve a requested column name against dataset-inspected options."""
        if not options:
            return None

        normalized_options = [str(option).strip() for option in options if str(option).strip()]
        if not normalized_options:
            return None

        if requested is None:
            return None

        requested_clean = str(requested).strip()
        if not requested_clean:
            return None

        option_lookup = {option.lower(): option for option in normalized_options}
        return option_lookup.get(requested_clean.lower())

    @staticmethod
    def _materialize_parameters(parameters: Any) -> dict[str, Any]:
        """Return a plain dict for persisted/run-manifest parameters."""
        if parameters is None:
            return {}
        if isinstance(parameters, Mapping):
            return dict(parameters)
        return {}

    def _apply_parameter_schema_constraints(
        self,
        parameter_schema: dict[str, Any] | None,
        parameters: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Apply schema constraints without trusting non-dict placeholder returns."""
        normalized = self._materialize_parameters(parameters)
        apply_constraints = getattr(
            self.pipeline_service,
            "apply_parameter_schema_constraints",
            None,
        )
        if not callable(apply_constraints):
            return normalized

        constrained = apply_constraints(parameter_schema, normalized)
        if isinstance(constrained, Mapping):
            return dict(constrained)

        logger.warning(
            "Pipeline parameter constraint helper returned %s; preserving original parameters",
            type(constrained).__name__,
        )
        return normalized

    async def _normalize_dataset_aware_parameters(
        self,
        *,
        org_id: UUID,
        dataset_version_id: UUID,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve dataset-specific batch and cluster keys before validation/execution."""
        normalized = dict(parameters or {})
        original_batch_key = parameters.get("batch_key")
        original_hvg_batch_key = parameters.get("hvg_batch_key")
        original_cluster_key = parameters.get("cluster_key")
        original_annotation_cluster_key = parameters.get("annotation_cluster_key")

        requires_dataset_lookup = bool(normalized.get("batch_correction")) or any(
            value is not None
            for value in (
                original_batch_key,
                original_hvg_batch_key,
                original_cluster_key,
                original_annotation_cluster_key,
            )
        )
        if not requires_dataset_lookup:
            return {key: value for key, value in normalized.items() if value is not None}

        dataset_service = DatasetService(
            db=self.db,
            s3_service=self.s3_service,
            cache_service=self.cache,
            audit_service=self.audit,
        )
        column_meta = await dataset_service.get_dataset_version_columns(
            dataset_version_id=dataset_version_id,
            org_id=org_id,
        )

        batch_options = [
            *column_meta.get("batch_candidates", []),
            *column_meta.get("obs_columns", []),
        ]
        cluster_options = [
            *column_meta.get("cluster_candidates", []),
            "cluster",
            "leiden",
            "louvain",
            *column_meta.get("obs_columns", []),
        ]

        resolved_batch_key = self._resolve_dataset_column(
            normalized.get("batch_key"), batch_options
        )

        if normalized.get("batch_correction"):
            normalized["batch_key"] = resolved_batch_key or (
                batch_options[0] if batch_options else None
            )
        elif original_batch_key is not None and resolved_batch_key:
            normalized["batch_key"] = resolved_batch_key

        resolved_hvg_batch_key = self._resolve_dataset_column(
            normalized.get("hvg_batch_key"),
            batch_options,
        )
        if original_hvg_batch_key is not None and resolved_hvg_batch_key:
            normalized["hvg_batch_key"] = resolved_hvg_batch_key
        elif original_hvg_batch_key is not None:
            normalized.pop("hvg_batch_key", None)

        resolved_cluster_key = self._resolve_dataset_column(
            normalized.get("cluster_key"),
            cluster_options,
        )
        requested_cluster_key = str(original_cluster_key or "").strip()
        if original_cluster_key is not None and resolved_cluster_key:
            normalized["cluster_key"] = resolved_cluster_key
        elif requested_cluster_key.lower() in {"cluster", "leiden", "louvain"}:
            normalized["cluster_key"] = requested_cluster_key.lower()
        elif original_cluster_key is not None:
            normalized.pop("cluster_key", None)

        resolved_annotation_cluster_key = self._resolve_dataset_column(
            normalized.get("annotation_cluster_key"),
            cluster_options,
        )
        requested_annotation_cluster_key = str(original_annotation_cluster_key or "").strip()
        if original_annotation_cluster_key is not None and resolved_annotation_cluster_key:
            normalized["annotation_cluster_key"] = resolved_annotation_cluster_key
        elif requested_annotation_cluster_key.lower() in {"cluster", "leiden", "louvain"}:
            normalized["annotation_cluster_key"] = requested_annotation_cluster_key.lower()
        elif (
            original_annotation_cluster_key is None
            and original_cluster_key is not None
            and normalized.get("cluster_key")
        ):
            normalized["annotation_cluster_key"] = normalized["cluster_key"]
        elif original_annotation_cluster_key is not None:
            normalized.pop("annotation_cluster_key", None)

        return {key: value for key, value in normalized.items() if value is not None}

    async def create_run(
        self,
        org_id: UUID,
        dataset_version_id: UUID,
        template_id: UUID,
        parameters: dict,
        random_seed: int | None = None,
        user_id: UUID | None = None,
    ) -> Run:
        """Create a new run with parameter validation.

        Args:
            org_id: Organization ID for scoping
            dataset_version_id: Dataset version to run against
            template_id: Pipeline template to execute
            parameters: Run parameters to validate against template schema
            random_seed: Optional random seed for reproducibility

        Returns:
            Created Run in QUEUED status

        Raises:
            ValueError: If dataset version not found, template not found, or parameters invalid
        """
        # Verify dataset version exists and belongs to organization
        dataset_stmt = (
            select(DatasetVersion)
            .join(DatasetVersion.dataset)
            .where(
                and_(
                    DatasetVersion.id == dataset_version_id,
                    DatasetVersion.dataset.has(organization_id=org_id),
                )
            )
            .options(selectinload(DatasetVersion.dataset))
        )
        dataset_result = await self.db.execute(dataset_stmt)
        dataset_version = dataset_result.scalar_one_or_none()

        if dataset_version is None:
            raise ValueError(
                f"Dataset version {dataset_version_id} not found or does not belong to organization {org_id}"
            )

        # Verify template exists and belongs to organization
        template_stmt = select(PipelineTemplate).where(
            and_(
                PipelineTemplate.id == template_id,
                PipelineTemplate.organization_id == org_id,
            )
        )
        template_result = await self.db.execute(template_stmt)
        template = template_result.scalar_one_or_none()

        if template is None:
            raise ValueError(
                f"Template {template_id} not found or does not belong to organization {org_id}"
            )

        parameters = await self._normalize_dataset_aware_parameters(
            org_id=org_id,
            dataset_version_id=dataset_version_id,
            parameters=parameters,
        )
        parameters = self._apply_parameter_schema_constraints(
            template.definition.get("parameter_schema", {}),
            parameters,
        )

        # Validate parameters against template schema
        is_valid, error_message = await self.pipeline_service.validate_parameters(
            template_id, parameters
        )

        if not is_valid:
            raise ValueError(f"Parameter validation failed: {error_message}")

        # Check compute quota before creating the run
        await self.quota_service.check_compute_quota(org_id)

        # Record dataset version checksum for the run manifest
        dataset_checksum = dataset_version.checksum or ""

        # Create run
        run = Run(
            organization_id=org_id,
            dataset_version_id=dataset_version_id,
            dataset_id_snapshot=dataset_version.dataset_id,
            dataset_version_id_snapshot=dataset_version.id,
            dataset_name_snapshot=dataset_version.dataset.name,
            dataset_version_label_snapshot=dataset_version.version,
            template_id=template_id,
            status=RunStatus.QUEUED,
            parameters=parameters,
            random_seed=random_seed,
            created_at=datetime.utcnow(),
        )

        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)

        # Audit: run created
        await self.audit.audit_log(
            org_id=org_id,
            user_id=user_id or org_id,
            action_type="run.create",
            resource_type="run",
            resource_id=run.id,
            after_state={
                "status": run.status.value,
                "dataset_version_id": str(dataset_version_id),
                "template_id": str(template_id),
            },
        )
        await self.db.commit()

        return run

    def build_run_manifest(
        self,
        run: Run,
        dataset_checksum: str,
        method_versions: dict[str, str] | None = None,
    ) -> RunManifest:
        """Build an immutable RunManifest for a run.

        The manifest captures the dataset version binding, checksum, template,
        parameters, and method versions — everything needed for reproducibility.

        Args:
            run: The Run ORM instance.
            dataset_checksum: SHA-256 checksum of the bound dataset version.
            method_versions: Optional mapping of step_name -> version string.

        Returns:
            A RunManifest contract instance.
        """
        return RunManifest(
            run_id=run.id,
            dataset_version_id=run.dataset_version_id,
            dataset_checksum=dataset_checksum,
            template_id=run.template_id,
            parameters=self._materialize_parameters(run.parameters),
            method_versions=method_versions or {},
            random_seed=run.random_seed,
            created_at=run.created_at,
        )

    async def create_run_with_manifest(
        self,
        org_id: UUID,
        dataset_version_id: UUID,
        template_id: UUID,
        parameters: dict,
        random_seed: int | None = None,
        user_id: UUID | None = None,
    ) -> tuple[Run, RunManifest]:
        """Create a new run and return it together with its RunManifest.

        This is the primary entry point for run creation that enforces
        dataset-version binding (Requirement 3). The manifest records the
        dataset version checksum so that reproducibility can be verified later.

        Args:
            org_id: Organization ID for scoping
            dataset_version_id: Dataset version to run against
            template_id: Pipeline template to execute
            parameters: Run parameters to validate against template schema
            random_seed: Optional random seed for reproducibility
            user_id: Optional user ID for audit logging

        Returns:
            Tuple of (Run, RunManifest)

        Raises:
            ValueError: If dataset_version_id is missing/invalid, template not
                found, or parameters invalid.
        """
        # Verify dataset version exists and belongs to organization
        stmt = (
            select(DatasetVersion)
            .join(DatasetVersion.dataset)
            .where(
                and_(
                    DatasetVersion.id == dataset_version_id,
                    DatasetVersion.dataset.has(organization_id=org_id),
                )
            )
        )
        result = await self.db.execute(stmt)
        dataset_version = result.scalar_one_or_none()

        if dataset_version is None:
            raise ValueError(
                f"Dataset version {dataset_version_id} not found or does not belong to organization {org_id}"
            )

        dataset_checksum = dataset_version.checksum or ""

        # Delegate to create_run for the actual run creation
        run = await self.create_run(
            org_id=org_id,
            dataset_version_id=dataset_version_id,
            template_id=template_id,
            parameters=parameters,
            random_seed=random_seed,
            user_id=user_id,
        )

        manifest = self.build_run_manifest(
            run=run,
            dataset_checksum=dataset_checksum,
        )

        return run, manifest

    async def start_run(self, run_id: UUID) -> Run:
        """Start a run by transitioning to RUNNING status and dispatching the Temporal workflow.

        Args:
            run_id: Run ID to start

        Returns:
            Updated Run

        Raises:
            ValueError: If run not found or not in QUEUED status
        """
        # Get run
        stmt = select(Run).where(Run.id == run_id)
        result = await self.db.execute(stmt)
        run = result.scalar_one_or_none()

        if run is None:
            raise ValueError(f"Run {run_id} not found")

        if run.status != RunStatus.QUEUED:
            raise ValueError(
                f"Run {run_id} cannot be started from status {run.status}. Must be QUEUED."
            )

        # Update status and started_at
        run.status = RunStatus.RUNNING
        run.started_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(run)

        # Invalidate cached status
        if self.cache:
            await self.cache.invalidate_run_status(str(run_id))

        await self._dispatch_workflow(run)

        return run

    async def _dispatch_workflow(
        self,
        run: Run,
        *,
        id_reuse_policy: Any | None = None,
        id_conflict_policy: Any | None = None,
        raise_on_error: bool = False,
    ) -> None:
        """Dispatch the Temporal workflow for a run."""
        try:
            from temporalio.client import Client as TemporalClient

            from workflows.config import get_workflow_settings
            from workflows.run_execution.schemas import RunExecutionInput
            from workflows.run_execution.workflow import RunExecutionWorkflow

            settings = get_workflow_settings()
            temporal_client = await TemporalClient.connect(
                settings.temporal_address,
                namespace=settings.temporal_namespace,
            )
            workflow_kwargs: dict[str, Any] = {
                "id": f"run-execution-{run.id}",
                "task_queue": settings.temporal_task_queue,
            }
            if id_reuse_policy is not None:
                workflow_kwargs["id_reuse_policy"] = id_reuse_policy
            if id_conflict_policy is not None:
                workflow_kwargs["id_conflict_policy"] = id_conflict_policy

            if run.dataset_version_id is None:
                raise ValueError(f"Run {run.id} is missing dataset_version_id")

            await temporal_client.start_workflow(
                RunExecutionWorkflow.run,
                RunExecutionInput(
                    run_id=run.id,
                    dataset_version_id=run.dataset_version_id,
                    template_id=run.template_id,
                    parameters=run.parameters,
                    random_seed=run.random_seed or 42,
                ),
                **workflow_kwargs,
            )
        except Exception as e:
            # Temporal unavailable — log but don't fail the run creation.
            # The run stays in RUNNING; a retry mechanism or manual trigger
            # can re-dispatch later.
            import logging

            logging.getLogger(__name__).warning(
                f"Could not dispatch Temporal workflow for run {run.id}: {e}"
            )
            if raise_on_error:
                raise

    @staticmethod
    def _workflow_id(run_id: UUID | str) -> str:
        """Return the Temporal workflow ID for a run."""
        return f"run-execution-{run_id}"

    async def _resolve_audit_user_id(
        self, organization_id: UUID, user_id: UUID | None
    ) -> UUID | None:
        """Return a valid user ID for audit logging when one is available."""
        if user_id is not None:
            return user_id

        result = await self.db.execute(
            select(OrganizationUser.c.user_id)
            .where(OrganizationUser.c.organization_id == organization_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _coerce_datetime(value: Any) -> datetime | None:
        """Normalize timestamp-like values into naive UTC datetimes."""
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value)
            except ValueError:
                return None
        else:
            return None

        if dt.tzinfo is not None:
            return dt.astimezone(UTC).replace(tzinfo=None)
        return dt

    @classmethod
    def _last_progress_update(cls, run: Run) -> datetime:
        """Return the best available timestamp for run liveness."""
        progress = run.parameters.get("progress") if isinstance(run.parameters, dict) else None
        if isinstance(progress, dict):
            updated_at = cls._coerce_datetime(progress.get("updated_at"))
            if updated_at is not None:
                return updated_at

        if run.started_at is not None:
            return cls._coerce_datetime(run.started_at) or run.started_at
        return cls._coerce_datetime(run.created_at) or run.created_at

    @staticmethod
    def _completed_checkpoint_count(parameters: dict[str, Any]) -> int:
        """Return the number of completed durable checkpoints on a run."""
        raw = parameters.get(CHECKPOINTS_PARAMETER_KEY)
        if not isinstance(raw, list):
            return 0

        count = 0
        for item in raw:
            if (
                isinstance(item, dict)
                and str(item.get("status", "")).lower() == RunStatus.COMPLETED.value
            ):
                count += 1
        return count

    @staticmethod
    def _auto_recovery_attempts(parameters: dict[str, Any]) -> int:
        """Read the reconciler restart count from internal execution state."""
        execution_state = parameters.get(EXECUTION_STATE_PARAMETER_KEY)
        if not isinstance(execution_state, dict):
            return 0

        value = execution_state.get("auto_recovery_attempts", 0)
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _set_auto_recovery_attempts(parameters: dict[str, Any], attempts: int) -> dict[str, Any]:
        """Persist the reconciler restart count in internal execution state."""
        updated = dict(parameters or {})
        execution_state = updated.get(EXECUTION_STATE_PARAMETER_KEY)
        if not isinstance(execution_state, dict):
            execution_state = {}
        else:
            execution_state = dict(execution_state)

        execution_state["auto_recovery_attempts"] = max(0, attempts)
        execution_state["updated_at"] = datetime.utcnow().isoformat()
        updated[EXECUTION_STATE_PARAMETER_KEY] = execution_state
        return updated

    @staticmethod
    def _update_progress_payload(
        parameters: dict[str, Any],
        *,
        state: str,
        current_step: str | None = None,
        clear_current_step: bool = False,
    ) -> dict[str, Any]:
        """Update progress metadata without dropping existing step summaries."""
        updated = dict(parameters or {})
        progress = updated.get("progress")
        if not isinstance(progress, dict):
            progress = {}
        else:
            progress = dict(progress)

        progress["state"] = state
        progress["updated_at"] = datetime.utcnow().isoformat()
        if current_step is not None:
            progress["current_step"] = current_step
        elif clear_current_step:
            progress["current_step"] = None
            progress["current_step_label"] = None
            progress["current_step_started_at"] = None

        updated["progress"] = progress
        return updated

    async def _connect_temporal_client(self) -> Any:
        """Connect to Temporal for run reconciliation."""
        from temporalio.client import Client as TemporalClient

        from workflows.config import get_workflow_settings

        settings = get_workflow_settings()
        return await TemporalClient.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
        )

    async def _describe_temporal_workflow_status(
        self,
        temporal_client: Any,
        run_id: UUID,
    ) -> Any | None:
        """Describe the Temporal workflow for a run, returning None if missing."""
        from temporalio.service import RPCError, RPCStatusCode

        handle = temporal_client.get_workflow_handle(self._workflow_id(run_id))
        try:
            description = await handle.describe()
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                return None
            raise
        return description.status

    async def _terminate_temporal_workflow(
        self,
        temporal_client: Any,
        run_id: UUID,
        *,
        reason: str,
    ) -> None:
        """Terminate an in-flight Temporal workflow if it still exists."""
        from temporalio.service import RPCError, RPCStatusCode

        handle = temporal_client.get_workflow_handle(self._workflow_id(run_id))
        try:
            await handle.terminate(reason=reason)
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                return
            raise

    async def _persist_run_parameters(self, run: Run, parameters: dict[str, Any]) -> Run:
        """Persist JSON parameter mutations safely."""
        run.parameters = parameters
        flag_modified(run, "parameters")
        await self.db.commit()
        await self.db.refresh(run)
        if self.cache:
            await self.cache.invalidate_run_status(str(run.id))
        return run

    @staticmethod
    def _resolve_s3_location(s3_path: str, default_bucket: str) -> tuple[str, str]:
        """Resolve bucket/key from stored artifact paths."""
        if s3_path.startswith("s3://"):
            bucket, key = s3_path[5:].split("/", 1)
            return bucket, key
        return default_bucket, s3_path

    @staticmethod
    def _extract_run_prefix(key: str, run_id: UUID) -> str | None:
        """Extract the run-scoped object prefix from a storage key."""
        run_segment = f"runs/{run_id}/"
        if key.startswith(run_segment):
            return run_segment

        marker = f"/{run_segment}"
        if marker in key:
            return f"{key.split(marker, 1)[0]}/{run_segment}"
        return None

    @staticmethod
    def _explorer_cache_root() -> Path:
        """Return the local artifact cache root used by explorer/results routes."""
        return Path(
            os.getenv(
                "ZERNA_EXPLORER_CACHE_DIR",
                str(Path(tempfile.gettempdir()) / "zerna_explorer_cache"),
            )
        )

    def _clear_local_artifact_cache(self, artifacts: list[Artifact]) -> None:
        """Delete cached local artifact copies for a run."""
        cache_root = self._explorer_cache_root()
        if not cache_root.exists():
            return

        for artifact in artifacts:
            suffix = Path(artifact.s3_path).suffix or ".bin"
            cached_path = cache_root / f"{artifact.id}{suffix}"
            if cached_path.exists():
                cached_path.unlink(missing_ok=True)

    def _collect_run_storage_objects(
        self,
        *,
        run_id: UUID,
        artifacts: list[Artifact],
    ) -> set[tuple[str, str]]:
        """Collect every known storage object owned by a run."""
        objects: set[tuple[str, str]] = set()
        prefixes_by_bucket: dict[str, set[str]] = {
            self.s3_service.artifacts_bucket: {f"runs/{run_id}/"}
        }

        for artifact in artifacts:
            bucket, key = self._resolve_s3_location(
                artifact.s3_path, self.s3_service.artifacts_bucket
            )
            objects.add((bucket, key))
            prefix = self._extract_run_prefix(key, run_id)
            if prefix:
                prefixes_by_bucket.setdefault(bucket, set()).add(prefix)

        for bucket, prefixes in prefixes_by_bucket.items():
            for prefix in prefixes:
                for entry in self.s3_service.list_files(bucket=bucket, prefix=prefix):
                    entry_key = entry.get("key")
                    if isinstance(entry_key, str) and entry_key:
                        objects.add((bucket, entry_key))

        return objects

    async def _delete_run_resources(self, run: Run) -> tuple[int, int]:
        """Delete all stored objects and local caches for a run."""
        artifacts = list(run.artifacts or [])
        storage_objects = self._collect_run_storage_objects(run_id=run.id, artifacts=artifacts)

        for bucket, key in storage_objects:
            self.s3_service.delete_file(bucket, key)

        self._clear_local_artifact_cache(artifacts)
        return len(artifacts), len(storage_objects)

    async def _delete_run_record(
        self,
        run: Run,
        *,
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Delete one run, including workflow execution and persisted storage."""
        if run.status in (RunStatus.QUEUED, RunStatus.RUNNING):
            try:
                temporal_client = await self._connect_temporal_client()
            except Exception as exc:
                logger.warning(
                    "Could not connect to Temporal while deleting run %s: %s", run.id, exc
                )
            else:
                try:
                    await self._terminate_temporal_workflow(
                        temporal_client,
                        run.id,
                        reason="Run deleted by user request",
                    )
                except Exception as exc:
                    logger.warning(
                        "Could not terminate workflow for deleted run %s: %s", run.id, exc
                    )

        deleted_artifacts, deleted_storage_objects = await self._delete_run_resources(run)
        audit_user_id = await self._resolve_audit_user_id(run.organization_id, user_id)
        deleted_run_id = run.id
        deleted_run_status = run.status.value

        await self.db.delete(run)
        await self.db.commit()

        if audit_user_id is not None:
            await self.audit.audit_log(
                org_id=run.organization_id,
                user_id=audit_user_id,
                action_type="run.delete",
                resource_type="run",
                resource_id=deleted_run_id,
                before_state={"status": deleted_run_status},
                after_state={"deleted": True},
            )
            await self.db.commit()

        if self.cache:
            await self.cache.invalidate_run_status(str(deleted_run_id))

        return {
            "run_id": deleted_run_id,
            "deleted_artifacts": deleted_artifacts,
            "deleted_storage_objects": deleted_storage_objects,
        }

    async def _mark_run_completed_by_reconciler(self, run: Run, reason: str) -> dict[str, Any]:
        """Repair a stale RUNNING row when Temporal already completed the workflow."""
        parameters = self._update_progress_payload(
            run.parameters or {},
            state=RunStatus.COMPLETED.value,
            clear_current_step=True,
        )
        run.parameters = parameters
        flag_modified(run, "parameters")
        run.status = RunStatus.COMPLETED
        run.completed_at = datetime.utcnow()
        run.error_message = None
        await self.db.commit()
        await self.db.refresh(run)
        if self.cache:
            await self.cache.invalidate_run_status(str(run.id))
        return {"run_id": str(run.id), "action": "completed", "reason": reason}

    async def _mark_run_failed_by_reconciler(self, run: Run, reason: str) -> dict[str, Any]:
        """Mark a stale run as failed with an explicit recovery message."""
        parameters = self._update_progress_payload(
            run.parameters or {},
            state=RunStatus.FAILED.value,
            clear_current_step=True,
        )
        run.parameters = parameters
        flag_modified(run, "parameters")
        run.status = RunStatus.FAILED
        run.completed_at = datetime.utcnow()
        run.error_message = reason
        await self.db.commit()
        await self.db.refresh(run)
        if self.cache:
            await self.cache.invalidate_run_status(str(run.id))
        return {"run_id": str(run.id), "action": "failed", "reason": reason}

    async def reconcile_stale_runs(
        self,
        *,
        stale_after_seconds: int,
        max_auto_restart_attempts: int = 2,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Detect and reconcile stale RUNNING runs.

        A run is considered stale when its progress timestamp has not moved for
        more than ``stale_after_seconds``. If a durable checkpoint exists, the
        workflow is re-dispatched from that checkpoint; otherwise the run is
        marked failed with a clear worker-crash message.
        """
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=max(1, stale_after_seconds))

        stmt = (
            select(Run)
            .where(Run.status == RunStatus.RUNNING)
            .order_by(desc(Run.started_at), desc(Run.created_at))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        candidate_runs = list(result.scalars().all())
        stale_runs = [run for run in candidate_runs if self._last_progress_update(run) <= cutoff]

        if not stale_runs:
            return []

        try:
            temporal_client = await self._connect_temporal_client()
        except Exception as exc:
            logger.warning(
                "Skipping stale-run reconciliation because Temporal is unavailable: %s", exc
            )
            return []

        reconciled: list[dict[str, Any]] = []
        for run in stale_runs:
            last_update = self._last_progress_update(run)
            age_seconds = int(max(0.0, (now - last_update).total_seconds()))
            completed_checkpoints = self._completed_checkpoint_count(run.parameters or {})
            recovery_attempts = self._auto_recovery_attempts(run.parameters or {})

            try:
                workflow_status = await self._describe_temporal_workflow_status(
                    temporal_client, run.id
                )
            except Exception as exc:
                logger.warning("Could not inspect workflow state for run %s: %s", run.id, exc)
                continue

            status_label = (
                workflow_status.name.lower() if workflow_status is not None else "missing"
            )
            recovery_reason = (
                "Automatic stale-run recovery restarted this run after "
                f"{age_seconds}s without progress updates. Temporal workflow status was {status_label}."
            )

            if workflow_status == WorkflowExecutionStatus.COMPLETED:
                reconciled.append(
                    await self._mark_run_completed_by_reconciler(
                        run,
                        "Temporal reported the workflow completed, so the stale RUNNING row was repaired automatically.",
                    )
                )
                continue

            if completed_checkpoints > 0 and recovery_attempts < max_auto_restart_attempts:
                if workflow_status == WorkflowExecutionStatus.RUNNING:
                    try:
                        await self._terminate_temporal_workflow(
                            temporal_client,
                            run.id,
                            reason="Stale-run reconciler restarting checkpointed workflow",
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to terminate stale workflow before restart for run %s: %s",
                            run.id,
                            exc,
                        )
                    else:
                        for _ in range(5):
                            await asyncio.sleep(0.5)
                            try:
                                workflow_status = await self._describe_temporal_workflow_status(
                                    temporal_client,
                                    run.id,
                                )
                            except Exception:
                                break
                            if workflow_status != WorkflowExecutionStatus.RUNNING:
                                break
                updated_parameters = self._set_auto_recovery_attempts(
                    run.parameters or {},
                    recovery_attempts + 1,
                )
                updated_parameters = self._update_progress_payload(
                    updated_parameters, state=RunStatus.RUNNING.value
                )
                await self._persist_run_parameters(run, updated_parameters)
                try:
                    await self._dispatch_workflow(
                        run,
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                        id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
                        raise_on_error=True,
                    )
                except Exception as exc:
                    reconciled.append(
                        await self._mark_run_failed_by_reconciler(
                            run,
                            "Automatic stale-run reconciliation attempted a checkpoint restart but "
                            f"Temporal rejected the new workflow start: {exc}",
                        )
                    )
                    continue
                reconciled.append(
                    {
                        "run_id": str(run.id),
                        "action": "rescheduled",
                        "reason": recovery_reason,
                        "checkpoint_count": completed_checkpoints,
                        "recovery_attempts": recovery_attempts + 1,
                    }
                )
                continue

            if completed_checkpoints == 0:
                reason = (
                    "Automatic stale-run reconciliation marked this run failed after "
                    f"{age_seconds}s without progress updates because no durable completed-step checkpoint "
                    "was available for safe recovery."
                )
            else:
                reason = (
                    "Automatic stale-run reconciliation marked this run failed after "
                    f"{recovery_attempts} recovery attempt(s). Progress remained stale for "
                    f"{age_seconds}s and the run exhausted the automatic restart budget."
                )
            if workflow_status == WorkflowExecutionStatus.RUNNING:
                try:
                    await self._terminate_temporal_workflow(
                        temporal_client,
                        run.id,
                        reason="Stale-run reconciler terminating unrecoverable workflow",
                    )
                except Exception as exc:
                    logger.warning("Failed to terminate stale workflow for run %s: %s", run.id, exc)
            reconciled.append(await self._mark_run_failed_by_reconciler(run, reason))

        return reconciled

    async def resume_run(
        self,
        run_id: UUID,
        org_id: UUID,
        parameters: dict[str, Any],
        *,
        random_seed: int | None = None,
        user_id: UUID | None = None,
    ) -> Run:
        """Resume a failed run after correcting parameters.

        The same run ID is reused so the workflow can continue from its persisted
        checkpoint rather than restarting from the beginning.
        """
        from temporalio.common import WorkflowIDReusePolicy

        run = await self.get_run(run_id=run_id, org_id=org_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        if run.status != RunStatus.FAILED:
            raise ValueError(
                f"Run {run_id} cannot be resumed from status {run.status}. Must be FAILED."
            )

        if run.dataset_version_id is None:
            raise ValueError(f"Run {run.id} is missing dataset_version_id")

        parameters = await self._normalize_dataset_aware_parameters(
            org_id=org_id,
            dataset_version_id=run.dataset_version_id,
            parameters=parameters,
        )
        parameters = self._apply_parameter_schema_constraints(
            (run.template.definition if run.template is not None else {}).get(
                "parameter_schema", {}
            ),
            parameters,
        )

        is_valid, error_message = await self.pipeline_service.validate_parameters(
            run.template_id, parameters
        )
        if not is_valid:
            raise ValueError(f"Parameter validation failed: {error_message}")

        previous_progress = run.parameters.get("progress")
        preserved_internal_state = {
            key: value
            for key, value in (run.parameters or {}).items()
            if isinstance(key, str) and key.startswith("_")
        }
        updated_parameters = dict(parameters)
        updated_parameters.update(preserved_internal_state)
        if isinstance(previous_progress, dict):
            progress = dict(previous_progress)
            progress["state"] = RunStatus.QUEUED.value
            progress["current_step"] = None
            progress["current_step_label"] = None
            progress["current_step_started_at"] = None
            progress["updated_at"] = datetime.utcnow().isoformat()
            updated_parameters["progress"] = progress

        run.parameters = updated_parameters
        if random_seed is not None:
            run.random_seed = random_seed
        run.status = RunStatus.QUEUED
        run.started_at = None
        run.completed_at = None
        run.error_message = None

        await self.db.commit()
        await self.db.refresh(run)

        audit_user_id = await self._resolve_audit_user_id(run.organization_id, user_id)
        if audit_user_id is not None:
            await self.audit.audit_log(
                org_id=run.organization_id,
                user_id=audit_user_id,
                action_type="run.resume",
                resource_type="run",
                resource_id=run.id,
                before_state={"status": RunStatus.FAILED.value},
                after_state={"status": RunStatus.QUEUED.value},
            )
            await self.db.commit()
        else:
            logger.warning(
                "Skipping run.resume audit log for %s because no valid user was found", run.id
            )

        if self.cache:
            await self.cache.invalidate_run_status(str(run.id))

        # Transition back to RUNNING and re-dispatch the same workflow ID so the
        # checkpointed step state can be reused.
        run.status = RunStatus.RUNNING
        run.started_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(run)

        if self.cache:
            await self.cache.invalidate_run_status(str(run.id))

        await self._dispatch_workflow(
            run,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
        return run

    async def cancel_run(self, run_id: UUID, user_id: UUID | None = None) -> Run:
        """Cancel a run by transitioning to CANCELLED status.

        Args:
            run_id: Run ID to cancel

        Returns:
            Updated Run

        Raises:
            ValueError: If run not found or already completed/failed/cancelled
        """
        # Get run
        stmt = select(Run).where(Run.id == run_id)
        result = await self.db.execute(stmt)
        run = result.scalar_one_or_none()

        if run is None:
            raise ValueError(f"Run {run_id} not found")

        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
            raise ValueError(f"Run {run_id} cannot be cancelled from status {run.status}")

        try:
            temporal_client = await self._connect_temporal_client()
        except Exception as exc:
            logger.warning("Could not connect to Temporal while cancelling run %s: %s", run.id, exc)
        else:
            try:
                await self._terminate_temporal_workflow(
                    temporal_client,
                    run.id,
                    reason="Run cancelled by user request",
                )
            except Exception as exc:
                logger.warning("Could not terminate workflow for cancelled run %s: %s", run.id, exc)

        parameters = self._update_progress_payload(
            run.parameters or {},
            state=RunStatus.CANCELLED.value,
            clear_current_step=True,
        )
        run.parameters = parameters
        flag_modified(run, "parameters")
        run.status = RunStatus.CANCELLED
        run.completed_at = datetime.utcnow()
        run.error_message = "Run cancelled by user."

        await self.db.commit()
        await self.db.refresh(run)

        # Audit: run cancelled
        audit_user_id = await self._resolve_audit_user_id(run.organization_id, user_id)
        if audit_user_id is not None:
            await self.audit.audit_log(
                org_id=run.organization_id,
                user_id=audit_user_id,
                action_type="run.cancel",
                resource_type="run",
                resource_id=run.id,
                before_state={"status": RunStatus.RUNNING.value},
                after_state={"status": RunStatus.CANCELLED.value},
            )
            await self.db.commit()
        else:
            logger.warning(
                "Skipping run.cancel audit log for %s because no valid user was found", run.id
            )

        # Invalidate cached status
        if self.cache:
            await self.cache.invalidate_run_status(str(run_id))

        # TODO: Cleanup logic - cancel Temporal workflow, cleanup partial artifacts
        # This will be implemented when Temporal integration is added

        return run

    async def delete_run(
        self,
        *,
        run_id: UUID,
        org_id: UUID,
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Delete one run and all persisted data owned by it."""
        run = await self.get_run(run_id=run_id, org_id=org_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found or does not belong to organization {org_id}")

        return await self._delete_run_record(run, user_id=user_id)

    async def bulk_delete_runs(
        self,
        *,
        org_id: UUID,
        scope: str,
        dataset_id: UUID | None = None,
        run_ids: list[UUID] | None = None,
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Delete many runs for an organization."""
        if scope not in {"failed", "all", "selected"}:
            raise ValueError("Bulk delete scope must be 'failed', 'all', or 'selected'")

        stmt = (
            select(Run)
            .where(Run.organization_id == org_id)
            .options(selectinload(Run.artifacts))
            .order_by(desc(Run.created_at))
        )
        if dataset_id is not None:
            stmt = stmt.where(Run.dataset_id_snapshot == dataset_id)
        if scope == "failed":
            stmt = stmt.where(Run.status == RunStatus.FAILED)
        elif scope == "selected":
            selected_ids = list(dict.fromkeys(run_ids or []))
            if not selected_ids:
                raise ValueError("Select at least one run to delete.")
            stmt = stmt.where(Run.id.in_(selected_ids))

        result = await self.db.execute(stmt)
        runs = list(result.scalars().all())
        if scope == "selected":
            selected_ids = list(dict.fromkeys(run_ids or []))
            run_by_id = {run.id: run for run in runs}
            missing = [run_id for run_id in selected_ids if run_id not in run_by_id]
            if missing:
                raise ValueError(
                    "One or more selected runs were not found or do not belong to this organization."
                )
            runs = [run_by_id[run_id] for run_id in selected_ids]

        deleted_run_ids: list[UUID] = []
        deleted_artifacts = 0
        deleted_storage_objects = 0

        for run in runs:
            summary = await self._delete_run_record(run, user_id=user_id)
            deleted_run_ids.append(summary["run_id"])
            deleted_artifacts += int(summary["deleted_artifacts"])
            deleted_storage_objects += int(summary["deleted_storage_objects"])

        return {
            "scope": scope,
            "dataset_id": dataset_id,
            "deleted_run_ids": deleted_run_ids,
            "deleted_runs": len(deleted_run_ids),
            "deleted_artifacts": deleted_artifacts,
            "deleted_storage_objects": deleted_storage_objects,
        }

    async def get_run_status(self, run_id: UUID) -> RunStatus | None:
        """Get the current status of a run.

        Caches the result for CacheTTL.RUN_STATUS seconds.

        Args:
            run_id: Run ID

        Returns:
            RunStatus if run found, None otherwise
        """
        # Try cache first
        if self.cache:
            cache_key = CacheService.run_status_key(str(run_id))
            cached = await self.cache.get(cache_key)
            if cached is not None:
                try:
                    return RunStatus(cached)
                except ValueError:
                    pass  # stale/invalid value — fall through to DB

        stmt = select(Run.status).where(Run.id == run_id)
        result = await self.db.execute(stmt)
        status = result.scalar_one_or_none()

        if status is not None and self.cache:
            cache_key = CacheService.run_status_key(str(run_id))
            await self.cache.set(cache_key, status.value, ttl=CacheTTL.RUN_STATUS)

        return status

    async def get_run(self, run_id: UUID, org_id: UUID) -> Run | None:
        """Get a run by ID with organization scoping.

        Caches the result for CacheTTL.RUN_STATUS seconds.

        Args:
            run_id: Run ID
            org_id: Organization ID for scoping

        Returns:
            Run if found and belongs to organization, None otherwise
        """
        stmt = (
            select(Run)
            .where(and_(Run.id == run_id, Run.organization_id == org_id))
            .options(
                selectinload(Run.dataset_version).selectinload(DatasetVersion.dataset),
                selectinload(Run.template),
                selectinload(Run.artifacts),
                selectinload(Run.annotations),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_runs(
        self,
        org_id: UUID,
        status: RunStatus | None = None,
        dataset_version_id: UUID | None = None,
        dataset_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Run], int]:
        """List runs with optional filtering, pagination, and total count.

        Args:
            org_id: Organization ID for scoping
            status: Optional status filter
            dataset_version_id: Optional dataset version filter
            dataset_id: Optional dataset filter
            limit: Maximum number of runs to return
            offset: Number of runs to skip

        Returns:
            Tuple of (list of Runs, total count)
        """
        from sqlalchemy import func

        base_stmt = select(Run).where(Run.organization_id == org_id)

        if status is not None:
            base_stmt = base_stmt.where(Run.status == status)

        if dataset_version_id is not None:
            base_stmt = base_stmt.where(Run.dataset_version_id == dataset_version_id)

        if dataset_id is not None:
            base_stmt = base_stmt.where(Run.dataset_id_snapshot == dataset_id)

        # Count total
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar_one()

        # Fetch page
        page_stmt = (
            base_stmt.order_by(desc(Run.created_at))
            .offset(offset)
            .limit(limit)
            .options(
                selectinload(Run.artifacts),
                selectinload(Run.dataset_version).selectinload(DatasetVersion.dataset),
                selectinload(Run.template),
            )
        )

        result = await self.db.execute(page_stmt)
        return list(result.scalars().all()), total

    async def update_progress(self, run_id: UUID, progress_data: dict) -> Run:
        """Update run progress from Compute Plane events.

        Args:
            run_id: Run ID
            progress_data: Progress data from Compute Plane (e.g., completed steps, current step)

        Returns:
            Updated Run

        Raises:
            ValueError: If run not found
        """
        # Get run
        stmt = select(Run).where(Run.id == run_id)
        result = await self.db.execute(stmt)
        run = result.scalar_one_or_none()

        if run is None:
            raise ValueError(f"Run {run_id} not found")

        # Store progress data in parameters (or we could add a separate progress column)
        # For now, we'll merge it into the parameters dict under a special key
        if "progress" not in run.parameters:
            run.parameters["progress"] = {}

        run.parameters["progress"].update(progress_data)

        # Mark the parameters as modified for SQLAlchemy to detect the change
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(run, "parameters")

        await self.db.commit()
        await self.db.refresh(run)

        return run

    async def complete_run(
        self, run_id: UUID, software_versions: dict, user_id: UUID | None = None
    ) -> Run:
        """Complete a run by transitioning to COMPLETED status.

        Args:
            run_id: Run ID
            software_versions: Software versions used in the run (e.g., {"scanpy": "1.9.3"})

        Returns:
            Updated Run

        Raises:
            ValueError: If run not found or not in RUNNING status
        """
        # Get run
        stmt = select(Run).where(Run.id == run_id)
        result = await self.db.execute(stmt)
        run = result.scalar_one_or_none()

        if run is None:
            raise ValueError(f"Run {run_id} not found")

        if run.status != RunStatus.RUNNING:
            raise ValueError(
                f"Run {run_id} cannot be completed from status {run.status}. Must be RUNNING."
            )

        # Update status and metadata
        run.status = RunStatus.COMPLETED
        run.completed_at = datetime.utcnow()
        run.software_versions = software_versions

        await self.db.commit()
        await self.db.refresh(run)

        # Audit: run completed
        audit_user_id = await self._resolve_audit_user_id(run.organization_id, user_id)
        if audit_user_id is not None:
            await self.audit.audit_log(
                org_id=run.organization_id,
                user_id=audit_user_id,
                action_type="run.complete",
                resource_type="run",
                resource_id=run.id,
                before_state={"status": RunStatus.RUNNING.value},
                after_state={
                    "status": RunStatus.COMPLETED.value,
                    "software_versions": software_versions,
                },
            )
            await self.db.commit()
        else:
            logger.warning(
                "Skipping run.complete audit log for %s because no valid user was found",
                run.id,
            )

        if self.cache:
            await self.cache.invalidate_run_status(str(run_id))

        return run

    async def fail_run(self, run_id: UUID, error_message: str) -> Run:
        """Fail a run by transitioning to FAILED status.

        Args:
            run_id: Run ID
            error_message: Error message describing the failure

        Returns:
            Updated Run

        Raises:
            ValueError: If run not found
        """
        # Get run
        stmt = select(Run).where(Run.id == run_id)
        result = await self.db.execute(stmt)
        run = result.scalar_one_or_none()

        if run is None:
            raise ValueError(f"Run {run_id} not found")

        # Update status and error message
        run.status = RunStatus.FAILED
        run.completed_at = datetime.utcnow()
        run.error_message = error_message

        await self.db.commit()
        await self.db.refresh(run)

        if self.cache:
            await self.cache.invalidate_run_status(str(run_id))

        return run

    async def update_run_status(
        self, run_id: UUID, new_status: RunStatus, error_message: str | None = None
    ) -> Run:
        """Update run status directly (used by Nextflow integration).

        Args:
            run_id: Run ID
            new_status: Target status
            error_message: Optional error message (for FAILED status)

        Returns:
            Updated Run

        Raises:
            ValueError: If run not found
        """
        stmt = select(Run).where(Run.id == run_id)
        result = await self.db.execute(stmt)
        run = result.scalar_one_or_none()

        if run is None:
            raise ValueError(f"Run {run_id} not found")

        run.status = new_status
        if new_status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
            run.completed_at = datetime.utcnow()
        if error_message:
            run.error_message = error_message

        await self.db.commit()
        await self.db.refresh(run)

        if self.cache:
            await self.cache.invalidate_run_status(str(run_id))

        return run

    # ------------------------------------------------------------------
    # Run manifest persistence and replay (Requirement 3.4, 5.1)
    # ------------------------------------------------------------------

    async def persist_manifest(self, manifest: RunManifest) -> RunManifest:
        """Persist a RunManifest to the database as a JSON blob on the Run row.

        The manifest is stored in the run's ``parameters`` dict under the
        ``_manifest`` key so it survives API restarts and can be retrieved
        later for replay.

        Args:
            manifest: The RunManifest to persist.

        Returns:
            The same RunManifest (round-trip guarantee).

        Raises:
            ValueError: If the run referenced by the manifest does not exist.
        """
        stmt = select(Run).where(Run.id == manifest.run_id)
        result = await self.db.execute(stmt)
        run = result.scalar_one_or_none()

        if run is None:
            raise ValueError(f"Run {manifest.run_id} not found")

        # Serialize manifest to a JSON-safe dict and store it
        manifest_data = manifest.model_dump(mode="json")
        run.parameters = {**run.parameters, "_manifest": manifest_data}

        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(run, "parameters")

        await self.db.commit()
        await self.db.refresh(run)

        return manifest

    async def get_manifest(self, run_id: UUID) -> RunManifest | None:
        """Retrieve a persisted RunManifest from the database.

        Args:
            run_id: The run whose manifest to retrieve.

        Returns:
            The RunManifest if found, None otherwise.
        """
        stmt = select(Run).where(Run.id == run_id)
        result = await self.db.execute(stmt)
        run = result.scalar_one_or_none()

        if run is None:
            return None

        manifest_data = run.parameters.get("_manifest")
        if manifest_data is None:
            return None

        return RunManifest.model_validate(manifest_data)

    async def replay_run(
        self,
        run_id: UUID,
        org_id: UUID,
        user_id: UUID | None = None,
    ) -> tuple[Run, RunManifest]:
        """Re-execute a run using its persisted manifest and dataset version.

        Retrieves the original manifest, creates a new run with the same
        parameters, dataset version, template, and random seed, then persists
        the new manifest.

        Args:
            run_id: The original run to replay.
            org_id: Organization ID for scoping.
            user_id: Optional user ID for audit logging.

        Returns:
            Tuple of (new Run, new RunManifest).

        Raises:
            ValueError: If the original run or its manifest is not found.
        """
        original_manifest = await self.get_manifest(run_id)
        if original_manifest is None:
            raise ValueError(
                f"No persisted manifest found for run {run_id}. Cannot replay without a manifest."
            )

        # Create a new run with the same parameters
        new_run, new_manifest = await self.create_run_with_manifest(
            org_id=org_id,
            dataset_version_id=original_manifest.dataset_version_id,
            template_id=original_manifest.template_id,
            parameters={k: v for k, v in original_manifest.parameters.items() if k != "_manifest"},
            random_seed=original_manifest.random_seed,
            user_id=user_id,
        )

        # Carry over method versions from the original manifest
        new_manifest = RunManifest(
            run_id=new_run.id,
            dataset_version_id=new_manifest.dataset_version_id,
            dataset_checksum=new_manifest.dataset_checksum,
            template_id=new_manifest.template_id,
            parameters=new_manifest.parameters,
            method_versions=original_manifest.method_versions,
            random_seed=new_manifest.random_seed,
            created_at=new_manifest.created_at,
        )

        # Persist the new manifest
        await self.persist_manifest(new_manifest)

        return new_run, new_manifest

    async def list_artifacts(
        self, run_id: UUID, org_id: UUID, generate_download_urls: bool = True
    ) -> list[tuple[Artifact, str | None]]:
        """List all artifacts for a run with organization scoping and optional pre-signed URLs.

        Args:
            run_id: Run ID
            org_id: Organization ID for scoping
            generate_download_urls: Whether to generate pre-signed S3 download URLs (default: True)

        Returns:
            List of tuples (Artifact, download_url). download_url is None if generate_download_urls=False.

        Raises:
            ValueError: If run not found or does not belong to organization
        """
        # Verify run exists and belongs to organization
        run = await self.get_run(run_id, org_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found or does not belong to organization {org_id}")

        # Get artifacts
        stmt = select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.created_at)
        result = await self.db.execute(stmt)
        artifacts = list(result.scalars().all())

        # Generate download URLs through API proxy (avoids MinIO CORS issues)
        if generate_download_urls:
            artifacts_with_urls: list[tuple[Artifact, str | None]] = []
            for artifact in artifacts:
                download_url = f"/v1/runs/{run_id}/artifacts/{artifact.id}/download"
                artifacts_with_urls.append((artifact, download_url))
            return artifacts_with_urls
        else:
            # Return artifacts without URLs
            return [(artifact, None) for artifact in artifacts]
