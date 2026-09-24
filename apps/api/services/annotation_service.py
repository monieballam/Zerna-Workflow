"""AnnotationService for managing annotation revisions."""

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from zerna_contracts.enums import ArtifactType, RunStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.models.annotation import AnnotationRevision
from apps.api.models.pipeline import Artifact, Run
from apps.api.services.audit_service import AuditService
from apps.api.services.s3_service import S3Service
from methods.annotation.cell_type_annotation import build_hierarchical_annotation


class AnnotationService:
    """Service for annotation revision management."""

    def __init__(
        self,
        db: AsyncSession,
        audit_service: AuditService | None = None,
        s3_service: S3Service | None = None,
    ):
        self.db = db
        self.audit = audit_service or AuditService(db)
        self.s3_service = s3_service or S3Service()

    async def create_revision(
        self,
        run_id: UUID,
        annotations: dict,
        created_by: UUID,
        method: str | None = None,
        knowledge_pack_id: UUID | None = None,
        org_id: UUID | None = None,
    ) -> AnnotationRevision:
        """Create a new annotation revision with auto-incremented revision_number."""
        # Compute next revision number (max existing + 1, starting at 1)
        stmt = select(func.max(AnnotationRevision.revision_number)).where(
            AnnotationRevision.run_id == run_id
        )
        result = await self.db.execute(stmt)
        max_rev = result.scalar_one_or_none()
        next_rev = (max_rev or 0) + 1

        revision = AnnotationRevision(
            run_id=run_id,
            revision_number=next_rev,
            annotations=annotations,
            created_by=created_by,
            method=method,
            knowledge_pack_id=knowledge_pack_id,
            created_at=datetime.utcnow(),
        )
        self.db.add(revision)
        await self.db.commit()
        await self.db.refresh(revision)

        # Audit: annotation created
        if org_id is not None:
            await self.audit.audit_log(
                org_id=org_id,
                user_id=created_by,
                action_type="annotation.create",
                resource_type="annotation_revision",
                resource_id=revision.id,
                after_state={"run_id": str(run_id), "revision_number": next_rev},
            )
            await self.db.commit()

        return revision

    async def edit_annotations(
        self, revision_id: UUID, edits: dict, user_id: UUID, org_id: UUID | None = None
    ) -> AnnotationRevision:
        """Merge edits into existing revision's annotations and create a new revision."""
        existing = await self.get_revision(revision_id)
        if existing is None:
            raise ValueError(f"AnnotationRevision {revision_id} not found")

        merged = {**existing.annotations, **edits}
        new_revision = await self.create_revision(
            run_id=existing.run_id,
            annotations=merged,
            created_by=user_id,
            method=existing.method,
            knowledge_pack_id=existing.knowledge_pack_id,
            org_id=org_id,
        )

        # Audit: annotation edited (override action_type set by create_revision)
        if org_id is not None:
            await self.audit.audit_log(
                org_id=org_id,
                user_id=user_id,
                action_type="annotation.edit",
                resource_type="annotation_revision",
                resource_id=new_revision.id,
                before_state={"revision_id": str(revision_id)},
                after_state={"revision_number": new_revision.revision_number},
            )
            await self.db.commit()

        return new_revision

    async def approve_revision(
        self, revision_id: UUID, approver_id: UUID, org_id: UUID | None = None
    ) -> AnnotationRevision:
        """Approve a revision. Raises ValueError if already approved."""
        revision = await self.get_revision(revision_id)
        if revision is None:
            raise ValueError(f"AnnotationRevision {revision_id} not found")
        if revision.approved_by is not None:
            raise ValueError(f"AnnotationRevision {revision_id} is already approved")
        revision.approved_by = approver_id
        revision.approved_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(revision)

        # Audit: annotation approved
        if org_id is not None:
            await self.audit.audit_log(
                org_id=org_id,
                user_id=approver_id,
                action_type="annotation.approve",
                resource_type="annotation_revision",
                resource_id=revision.id,
                after_state={
                    "approved_by": str(approver_id),
                    "approved_at": revision.approved_at.isoformat(),
                },
            )
            await self.db.commit()

        return revision

    async def list_revisions(self, run_id: UUID) -> list[AnnotationRevision]:
        """Return all revisions for a run ordered by revision_number."""
        stmt = (
            select(AnnotationRevision)
            .where(AnnotationRevision.run_id == run_id)
            .order_by(AnnotationRevision.revision_number)
            .options(selectinload(AnnotationRevision.knowledge_pack))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_revision(self, revision_id: UUID) -> AnnotationRevision | None:
        """Return AnnotationRevision by ID or None."""
        stmt = select(AnnotationRevision).where(AnnotationRevision.id == revision_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def bootstrap_revision_from_run(
        self,
        run_id: UUID,
        created_by: UUID,
        org_id: UUID,
        method: str = "run_bootstrap",
    ) -> AnnotationRevision:
        """Create an annotation revision directly from a completed run artifact."""
        run_stmt = select(Run).where(
            Run.id == run_id,
            Run.organization_id == org_id,
        )
        run_result = await self.db.execute(run_stmt)
        run = run_result.scalar_one_or_none()
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        if run.status != RunStatus.COMPLETED:
            raise ValueError(
                f"Run {run_id} must be completed before annotations can be bootstrapped"
            )

        artifact_stmt = (
            select(Artifact)
            .where(
                Artifact.run_id == run_id,
                Artifact.artifact_type == ArtifactType.H5AD,
            )
            .order_by(Artifact.created_at.desc())
        )
        artifact_result = await self.db.execute(artifact_stmt)
        artifact = artifact_result.scalar_one_or_none()
        if artifact is None:
            raise ValueError(f"Run {run_id} has no H5AD artifact to bootstrap from")

        annotations = self._extract_annotations_from_artifact(artifact)
        if not annotations:
            raise ValueError(f"Run {run_id} artifact did not contain any annotation-ready cells")

        return await self.create_revision(
            run_id=run_id,
            annotations=annotations,
            created_by=created_by,
            method=method,
            org_id=org_id,
        )

    def _extract_annotations_from_artifact(
        self, artifact: Artifact
    ) -> dict[str, dict[str, object]]:
        """Download a run artifact and derive per-cell annotation records."""
        import anndata as ad

        bucket, key = self._resolve_s3_location(artifact.s3_path)

        with tempfile.TemporaryDirectory(prefix="zerna_annotation_bootstrap_") as tmp_dir:
            local_path = Path(tmp_dir) / "artifact.h5ad"
            self.s3_service.s3_client.download_file(bucket, key, str(local_path))
            adata = ad.read_h5ad(local_path)
            return self._extract_annotations_from_adata(adata)

    def _resolve_s3_location(self, s3_path: str) -> tuple[str, str]:
        """Resolve ``s3://bucket/key`` or ``key`` into ``(bucket, key)``."""
        if s3_path.startswith("s3://"):
            bucket, key = s3_path[5:].split("/", 1)
            return bucket, key
        return self.s3_service.artifacts_bucket, s3_path

    @staticmethod
    def _pick_obs_column(obs_columns: list[str], *candidates: str) -> str | None:
        """Return the first matching obs column from a candidate list."""
        for candidate in candidates:
            if candidate in obs_columns:
                return candidate
        return None

    @staticmethod
    def _clean_obs_value(value: object, default: str = "Unknown") -> str:
        """Normalize obs values into usable strings."""
        text = str(value).strip()
        if not text or text.lower() == "nan":
            return default
        return text

    def _extract_annotations_from_adata(self, adata: Any) -> dict[str, dict[str, object]]:
        """Convert an AnnData object's obs columns into annotation payloads."""
        obs_columns = list(adata.obs.columns)
        cell_type_col = self._pick_obs_column(
            obs_columns,
            "annotation_cell_type",
            "celltypist_majority_voting",
            "celltypist_cell_type",
            "cell_type",
        )
        if cell_type_col is None:
            raise ValueError("Artifact is missing annotation columns in obs")

        tissue_col = self._pick_obs_column(
            obs_columns,
            "annotation_tissue",
            "tissue",
            "organ",
            "site",
            "sample_tissue",
        )
        lineage_col = self._pick_obs_column(
            obs_columns,
            "annotation_lineage",
            "annotation_broad",
            "lineage",
        )
        confidence_col = self._pick_obs_column(
            obs_columns,
            "annotation_confidence",
            "celltypist_conf_score",
            "confidence",
        )

        annotations: dict[str, dict[str, object]] = {}
        for cell_id, row in adata.obs.iterrows():
            raw_cell_type = self._clean_obs_value(row.get(cell_type_col, "Unknown"))
            tissue = self._clean_obs_value(row.get(tissue_col, "Unknown"))
            confidence_raw = row.get(confidence_col, 0.0) if confidence_col else 0.0
            confidence = float(cast(Any, confidence_raw))

            harmonized = build_hierarchical_annotation(
                raw_cell_type,
                tissue=tissue,
                confidence=confidence,
            )
            lineage = (
                self._clean_obs_value(
                    row.get(lineage_col, harmonized["lineage"]), default=str(harmonized["lineage"])
                )
                if lineage_col
                else str(harmonized["lineage"])
            )

            annotations[str(cell_id)] = {
                "tissue": str(harmonized["tissue"]),
                "lineage": lineage,
                "cell_type": str(harmonized["cell_type"]),
                "confidence": float(cast(Any, harmonized["confidence"])),
            }

        return annotations
