"""Export service for generating h5ad files with complete annotations and embeddings."""

import json
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import anndata as ad
import numpy as np
import pandas as pd
from zerna_contracts.enums import ArtifactType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.annotation import AnnotationRevision
from apps.api.models.pipeline import Artifact, Run
from apps.api.services.s3_service import S3Service

logger = logging.getLogger(__name__)

# Supported export formats
SUPPORTED_DATA_FORMATS = {"h5ad", "csv", "seurat"}
SUPPORTED_PLOT_FORMATS = {"png", "svg"}


def _html_escape(text: str) -> str:
    """Escape HTML special characters to prevent injection in reports."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


class ExportService:
    """Service for exporting run results as enriched h5ad files."""

    def __init__(self, db: AsyncSession, s3_service: S3Service | None = None):
        """Initialize ExportService.

        Args:
            db: Database session
            s3_service: S3 service instance (created if not provided)
        """
        self.db = db
        self.s3_service = s3_service or S3Service()

    async def export_h5ad(self, run_id: UUID, org_id: UUID) -> str:
        """Generate an enriched h5ad file from a run and upload to S3.

        Fetches the primary h5ad artifact, enriches it with all annotation
        revisions, embeddings, and run metadata, then uploads to S3.

        Args:
            run_id: Run UUID to export
            org_id: Organization UUID for S3 path scoping

        Returns:
            S3 path of the exported h5ad file

        Raises:
            ValueError: If run not found or does not belong to organization
        """
        # Fetch run with org scoping
        run = await self._get_run(run_id, org_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found or does not belong to organization {org_id}")

        # Fetch artifacts for this run
        artifacts = await self._get_artifacts(run_id)

        # Find primary h5ad artifact
        h5ad_artifact = next((a for a in artifacts if a.artifact_type == ArtifactType.H5AD), None)

        # Fetch annotation revisions
        annotation_revisions = await self._get_annotation_revisions(run_id)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Load or create base AnnData
            adata = await self._load_or_create_adata(h5ad_artifact, tmp_path)

            # Enrich with annotations from all revisions
            adata = self._add_annotations(adata, annotation_revisions)

            # Add run metadata to uns
            adata = self._add_run_metadata(adata, run, artifacts)

            # Save enriched h5ad to temp file
            export_file = tmp_path / "export.h5ad"
            # Ensure obs/var indices use object dtype for h5ad compatibility
            adata = self._ensure_object_dtype_indices(adata)
            adata.write_h5ad(export_file)

            # Upload to S3
            s3_path = f"{org_id}/exports/{run_id}/export.h5ad"
            self.s3_service.upload_file(
                file_path=export_file,
                bucket=self.s3_service.artifacts_bucket,
                s3_path=s3_path,
                content_type="application/octet-stream",
            )

        logger.info(
            "Exported h5ad for run %s to s3://%s/%s",
            run_id,
            self.s3_service.artifacts_bucket,
            s3_path,
        )
        return s3_path

    async def export_de_results_csv(self, run_id: UUID, org_id: UUID) -> str:
        """Export differential expression results as a CSV file and upload to S3.

        Finds the DE_RESULTS artifact for the run, downloads the CSV from S3,
        and re-uploads it to the exports path. If no artifact is found, a minimal
        CSV with the correct headers is created.

        Args:
            run_id: Run UUID to export
            org_id: Organization UUID for S3 path scoping

        Returns:
            S3 path of the exported CSV file

        Raises:
            ValueError: If run not found or does not belong to organization
        """
        run = await self._get_run(run_id, org_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found or does not belong to organization {org_id}")

        artifacts = await self._get_artifacts(run_id)
        de_artifact = next(
            (a for a in artifacts if a.artifact_type == ArtifactType.DE_RESULTS), None
        )

        de_columns = ["gene", "cluster", "log_fold_change", "p_value", "adjusted_p_value"]
        s3_path = f"{org_id}/exports/{run_id}/de_results.csv"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            export_file = tmp_path / "de_results.csv"

            if de_artifact is not None:
                try:
                    artifact_s3_path = de_artifact.s3_path
                    if artifact_s3_path.startswith("s3://"):
                        artifact_s3_path = artifact_s3_path[5:]

                    parts = artifact_s3_path.split("/", 1)
                    if len(parts) == 2:
                        bucket, key = parts
                    else:
                        bucket = self.s3_service.artifacts_bucket
                        key = artifact_s3_path

                    self.s3_service.s3_client.download_file(bucket, key, str(export_file))
                    # Validate columns; if missing, fall back to minimal CSV
                    df = pd.read_csv(export_file)
                    for col in de_columns:
                        if col not in df.columns:
                            df[col] = None
                    df[de_columns].to_csv(export_file, index=False)
                except Exception as exc:
                    logger.warning(
                        "Failed to download/process DE results artifact %s: %s. Creating minimal CSV.",
                        de_artifact.id,
                        exc,
                    )
                    pd.DataFrame(columns=de_columns).to_csv(export_file, index=False)
            else:
                logger.info(
                    "No DE_RESULTS artifact found for run %s; creating minimal CSV.", run_id
                )
                pd.DataFrame(columns=de_columns).to_csv(export_file, index=False)

            self.s3_service.upload_file(
                file_path=export_file,
                bucket=self.s3_service.artifacts_bucket,
                s3_path=s3_path,
                content_type="text/csv",
            )

        logger.info(
            "Exported DE results CSV for run %s to s3://%s/%s",
            run_id,
            self.s3_service.artifacts_bucket,
            s3_path,
        )
        return s3_path

    async def export_embeddings_csv(self, run_id: UUID, org_id: UUID) -> str:
        """Export cell embeddings and metadata as a CSV file and upload to S3.

        Finds the primary H5AD artifact, extracts UMAP/tSNE embeddings from obsm
        and cell metadata from obs, then exports as CSV. If no artifact is found,
        a minimal CSV with the correct headers is created.

        Args:
            run_id: Run UUID to export
            org_id: Organization UUID for S3 path scoping

        Returns:
            S3 path of the exported CSV file

        Raises:
            ValueError: If run not found or does not belong to organization
        """
        run = await self._get_run(run_id, org_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found or does not belong to organization {org_id}")

        artifacts = await self._get_artifacts(run_id)
        h5ad_artifact = next((a for a in artifacts if a.artifact_type == ArtifactType.H5AD), None)

        base_columns = ["cell_id", "umap_1", "umap_2", "tsne_1", "tsne_2"]
        s3_path = f"{org_id}/exports/{run_id}/embeddings.csv"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            export_file = tmp_path / "embeddings.csv"

            if h5ad_artifact is not None:
                try:
                    artifact_s3_path = h5ad_artifact.s3_path
                    if artifact_s3_path.startswith("s3://"):
                        artifact_s3_path = artifact_s3_path[5:]

                    parts = artifact_s3_path.split("/", 1)
                    if len(parts) == 2:
                        bucket, key = parts
                    else:
                        bucket = self.s3_service.artifacts_bucket
                        key = artifact_s3_path

                    local_h5ad = tmp_path / "source.h5ad"
                    self.s3_service.s3_client.download_file(bucket, key, str(local_h5ad))
                    adata = ad.read_h5ad(local_h5ad)

                    # Build embeddings dataframe
                    df = pd.DataFrame(index=adata.obs_names)
                    df.index.name = "cell_id"

                    # Extract UMAP embeddings
                    if "X_umap" in adata.obsm:
                        umap = adata.obsm["X_umap"]
                        df["umap_1"] = umap[:, 0] if umap.shape[1] > 0 else None
                        df["umap_2"] = umap[:, 1] if umap.shape[1] > 1 else None
                    else:
                        df["umap_1"] = None
                        df["umap_2"] = None

                    # Extract tSNE embeddings
                    if "X_tsne" in adata.obsm:
                        tsne = adata.obsm["X_tsne"]
                        df["tsne_1"] = tsne[:, 0] if tsne.shape[1] > 0 else None
                        df["tsne_2"] = tsne[:, 1] if tsne.shape[1] > 1 else None
                    else:
                        df["tsne_1"] = None
                        df["tsne_2"] = None

                    # Add obs metadata columns
                    for col in adata.obs.columns:
                        df[col] = adata.obs[col].values

                    df.reset_index().to_csv(export_file, index=False)
                except Exception as exc:
                    logger.warning(
                        "Failed to download/process H5AD artifact %s for embeddings: %s. Creating minimal CSV.",
                        h5ad_artifact.id,
                        exc,
                    )
                    pd.DataFrame(columns=base_columns).to_csv(export_file, index=False)
            else:
                logger.info(
                    "No H5AD artifact found for run %s; creating minimal embeddings CSV.", run_id
                )
                pd.DataFrame(columns=base_columns).to_csv(export_file, index=False)

            self.s3_service.upload_file(
                file_path=export_file,
                bucket=self.s3_service.artifacts_bucket,
                s3_path=s3_path,
                content_type="text/csv",
            )

        logger.info(
            "Exported embeddings CSV for run %s to s3://%s/%s",
            run_id,
            self.s3_service.artifacts_bucket,
            s3_path,
        )
        return s3_path

    # ------------------------------------------------------------------
    # CSV cell-metadata export
    # ------------------------------------------------------------------

    async def export_csv(self, run_id: UUID, org_id: UUID) -> str:
        """Export cell metadata and annotations as a flat CSV.

        Args:
            run_id: Run UUID to export
            org_id: Organization UUID for S3 path scoping

        Returns:
            S3 path of the exported CSV file

        Raises:
            ValueError: If run not found or does not belong to organization
        """
        run = await self._get_run(run_id, org_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found or does not belong to organization {org_id}")

        artifacts = await self._get_artifacts(run_id)
        h5ad_artifact = next((a for a in artifacts if a.artifact_type == ArtifactType.H5AD), None)
        annotation_revisions = await self._get_annotation_revisions(run_id)

        s3_path = f"{org_id}/exports/{run_id}/cell_metadata.csv"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            export_file = tmp_path / "cell_metadata.csv"

            adata = await self._load_or_create_adata(h5ad_artifact, tmp_path)
            adata = self._add_annotations(adata, annotation_revisions)

            df = adata.obs.copy()
            df.index.name = "cell_id"
            df.reset_index().to_csv(export_file, index=False)

            self.s3_service.upload_file(
                file_path=export_file,
                bucket=self.s3_service.artifacts_bucket,
                s3_path=s3_path,
                content_type="text/csv",
            )

        logger.info(
            "Exported CSV for run %s to s3://%s/%s",
            run_id,
            self.s3_service.artifacts_bucket,
            s3_path,
        )
        return s3_path

    # ------------------------------------------------------------------
    # Seurat-compatible bundle export
    # ------------------------------------------------------------------

    async def export_seurat(self, run_id: UUID, org_id: UUID) -> str:
        """Export a Seurat-compatible bundle (JSON manifest + CSV files).

        The bundle contains:
        - counts.csv  — raw count matrix (cells x genes)
        - metadata.csv — cell metadata / annotations
        - reductions.csv — UMAP/tSNE coordinates
        - manifest.json — provenance and method versions

        Args:
            run_id: Run UUID to export
            org_id: Organization UUID for S3 path scoping

        Returns:
            S3 path prefix of the exported bundle

        Raises:
            ValueError: If run not found or does not belong to organization
        """
        run = await self._get_run(run_id, org_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found or does not belong to organization {org_id}")

        artifacts = await self._get_artifacts(run_id)
        h5ad_artifact = next((a for a in artifacts if a.artifact_type == ArtifactType.H5AD), None)
        annotation_revisions = await self._get_annotation_revisions(run_id)

        s3_prefix = f"{org_id}/exports/{run_id}/seurat"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            adata = await self._load_or_create_adata(h5ad_artifact, tmp_path)
            adata = self._add_annotations(adata, annotation_revisions)
            adata = self._add_run_metadata(adata, run, artifacts)

            # counts.csv
            counts_file = tmp_path / "counts.csv"
            if adata.X is not None and adata.n_obs > 0:
                x_dense = adata.X.toarray() if hasattr(adata.X, "toarray") else np.asarray(adata.X)
                counts_df = pd.DataFrame(x_dense, index=adata.obs_names, columns=adata.var_names)
                counts_df.index.name = "cell_id"
                counts_df.reset_index().to_csv(counts_file, index=False)
            else:
                pd.DataFrame(columns=["cell_id"]).to_csv(counts_file, index=False)

            # metadata.csv
            meta_file = tmp_path / "metadata.csv"
            meta_df = adata.obs.copy()
            meta_df.index.name = "cell_id"
            meta_df.reset_index().to_csv(meta_file, index=False)

            # reductions.csv
            reductions_file = tmp_path / "reductions.csv"
            red_df = pd.DataFrame(index=adata.obs_names)
            red_df.index.name = "cell_id"
            for key in ("X_umap", "X_tsne", "X_pca"):
                if key in adata.obsm:
                    emb = adata.obsm[key]
                    prefix = key.replace("X_", "")
                    for i in range(min(emb.shape[1], 50)):
                        red_df[f"{prefix}_{i + 1}"] = emb[:, i]
            red_df.reset_index().to_csv(reductions_file, index=False)

            # manifest.json
            manifest_file = tmp_path / "manifest.json"
            manifest = {
                "run_id": str(run.id),
                "org_id": str(run.organization_id),
                "dataset_version_id": str(run.source_dataset_version_id)
                if run.source_dataset_version_id is not None
                else None,
                "parameters": run.parameters or {},
                "software_versions": run.software_versions or {},
                "method_versions": run.software_versions or {},
                "random_seed": run.random_seed,
                "exported_at": datetime.now(UTC).isoformat(),
                "format": "seurat_bundle",
                "files": ["counts.csv", "metadata.csv", "reductions.csv", "manifest.json"],
            }
            manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            # Upload all files
            for f in (counts_file, meta_file, reductions_file, manifest_file):
                self.s3_service.upload_file(
                    file_path=f,
                    bucket=self.s3_service.artifacts_bucket,
                    s3_path=f"{s3_prefix}/{f.name}",
                    content_type="application/json" if f.suffix == ".json" else "text/csv",
                )

        logger.info(
            "Exported Seurat bundle for run %s to s3://%s/%s",
            run_id,
            self.s3_service.artifacts_bucket,
            s3_prefix,
        )
        return s3_prefix

    # ------------------------------------------------------------------
    # Plot export (PNG / SVG)
    # ------------------------------------------------------------------

    async def export_plots(
        self, run_id: UUID, org_id: UUID, fmt: Literal["png", "svg"] = "png"
    ) -> str:
        """Export all available plot artifacts in the requested format.

        Finds plot artifacts for the run and re-uploads them in the requested
        image format. If no plot artifacts exist, creates a placeholder manifest.

        Args:
            run_id: Run UUID to export
            org_id: Organization UUID for S3 path scoping
            fmt: Image format — "png" or "svg"

        Returns:
            S3 path prefix of the exported plots

        Raises:
            ValueError: If run not found, invalid format, or org mismatch
        """
        if fmt not in SUPPORTED_PLOT_FORMATS:
            raise ValueError(f"Unsupported plot format: {fmt}. Supported: {SUPPORTED_PLOT_FORMATS}")

        run = await self._get_run(run_id, org_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found or does not belong to organization {org_id}")

        artifacts = await self._get_artifacts(run_id)
        plot_artifacts = [
            a
            for a in artifacts
            if a.artifact_type in (ArtifactType.PLOT, getattr(ArtifactType, "FIGURE", None))
            or (
                hasattr(a, "s3_path")
                and any(a.s3_path.endswith(ext) for ext in (".png", ".svg", ".pdf"))
            )
        ]

        s3_prefix = f"{org_id}/exports/{run_id}/plots_{fmt}"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            manifest: dict[str, Any] = {
                "run_id": str(run_id),
                "format": fmt,
                "plot_count": len(plot_artifacts),
                "exported_at": datetime.now(UTC).isoformat(),
                "files": [],
            }

            for i, art in enumerate(plot_artifacts):
                try:
                    s3_path = art.s3_path
                    if s3_path.startswith("s3://"):
                        s3_path = s3_path[5:]
                    parts = s3_path.split("/", 1)
                    if len(parts) == 2:
                        bucket, key = parts
                    else:
                        bucket = self.s3_service.artifacts_bucket
                        key = s3_path

                    local_file = tmp_path / f"plot_{i}.{fmt}"
                    self.s3_service.s3_client.download_file(bucket, key, str(local_file))

                    dest_key = f"{s3_prefix}/plot_{i}.{fmt}"
                    content_type = "image/png" if fmt == "png" else "image/svg+xml"
                    self.s3_service.upload_file(
                        file_path=local_file,
                        bucket=self.s3_service.artifacts_bucket,
                        s3_path=dest_key,
                        content_type=content_type,
                    )
                    manifest["files"].append(f"plot_{i}.{fmt}")
                except Exception as exc:
                    logger.warning("Failed to export plot artifact %s: %s", art.id, exc)

            # Always write manifest
            manifest_file = tmp_path / "manifest.json"
            manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            self.s3_service.upload_file(
                file_path=manifest_file,
                bucket=self.s3_service.artifacts_bucket,
                s3_path=f"{s3_prefix}/manifest.json",
                content_type="application/json",
            )

        logger.info("Exported %d plots (%s) for run %s", len(plot_artifacts), fmt, run_id)
        return s3_prefix

    def verify_export_completeness(self, h5ad_path: str) -> bool:
        """Verify export completeness via round-trip load check.

        Loads the h5ad file and checks that required metadata keys are present.

        Args:
            h5ad_path: Local filesystem path to the h5ad file

        Returns:
            True if the file loads successfully and contains required metadata,
            False otherwise
        """
        try:
            adata = ad.read_h5ad(h5ad_path)

            # Must be a valid AnnData with cells
            if adata.n_obs == 0:
                logger.warning("Export verification failed: no cells in h5ad at %s", h5ad_path)
                return False

            # Must contain run metadata in uns
            if "zerna_run_metadata" not in adata.uns:
                logger.warning(
                    "Export verification failed: missing zerna_run_metadata in uns at %s", h5ad_path
                )
                return False

            run_meta = adata.uns["zerna_run_metadata"]
            required_keys = {"run_id", "org_id", "exported_at"}
            missing = required_keys - set(run_meta.keys())
            if missing:
                logger.warning(
                    "Export verification failed: missing keys %s in zerna_run_metadata at %s",
                    missing,
                    h5ad_path,
                )
                return False

            logger.info(
                "Export verification passed: %d cells, %d genes at %s",
                adata.n_obs,
                adata.n_vars,
                h5ad_path,
            )
            return True

        except Exception as exc:
            logger.error("Export verification failed with exception at %s: %s", h5ad_path, exc)
            return False

    def _ensure_object_dtype_indices(self, adata: ad.AnnData) -> ad.AnnData:
        """Convert obs/var indices to object dtype for h5ad write compatibility.

        Newer pandas versions may use Arrow-backed string arrays which anndata
        cannot serialise to HDF5. This converts them to plain object dtype.
        """
        if adata.obs.index.dtype != object:
            adata.obs.index = adata.obs.index.astype("object")
        if adata.var.index.dtype != object:
            adata.var.index = adata.var.index.astype("object")
        # Also convert any obs columns that are Arrow-backed or categorical with Arrow categories
        for col in adata.obs.columns:
            col_dtype_str = str(adata.obs[col].dtype)
            if col_dtype_str in ("string[pyarrow]", "string[pyarrow_numpy]", "str"):
                adata.obs[col] = adata.obs[col].astype("object")
            elif hasattr(adata.obs[col], "cat"):
                # Categorical column — convert categories if Arrow-backed
                cat = adata.obs[col].cat
                if str(cat.categories.dtype) in (
                    "string[pyarrow]",
                    "string[pyarrow_numpy]",
                    "str",
                ):
                    adata.obs[col] = adata.obs[col].astype(str).astype("category")
        return adata

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_run(self, run_id: UUID, org_id: UUID) -> Run | None:
        stmt = select(Run).where(Run.id == run_id, Run.organization_id == org_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_artifacts(self, run_id: UUID) -> list[Artifact]:
        stmt = select(Artifact).where(Artifact.run_id == run_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _get_annotation_revisions(self, run_id: UUID) -> list[AnnotationRevision]:
        stmt = (
            select(AnnotationRevision)
            .where(AnnotationRevision.run_id == run_id)
            .order_by(AnnotationRevision.revision_number)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Reproducibility report
    # ------------------------------------------------------------------

    async def generate_reproducibility_report(self, run_id: UUID, org_id: UUID) -> str:
        """Generate an HTML reproducibility report for a run and upload to S3.

        Args:
            run_id: Run UUID to report on
            org_id: Organization UUID for S3 path scoping

        Returns:
            S3 path of the uploaded HTML report

        Raises:
            ValueError: If run not found or does not belong to organization
        """
        run = await self._get_run(run_id, org_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found or does not belong to organization {org_id}")

        artifacts = await self._get_artifacts(run_id)
        annotation_revisions = await self._get_annotation_revisions(run_id)

        html_content = self._generate_html_report(run, artifacts, annotation_revisions)

        s3_path = f"{org_id}/exports/{run_id}/reproducibility_report.html"

        with tempfile.TemporaryDirectory() as tmp_dir:
            report_file = Path(tmp_dir) / "reproducibility_report.html"
            report_file.write_text(html_content, encoding="utf-8")
            self.s3_service.upload_file(
                file_path=report_file,
                bucket=self.s3_service.artifacts_bucket,
                s3_path=s3_path,
                content_type="text/html",
            )

        logger.info(
            "Generated reproducibility report for run %s at s3://%s/%s",
            run_id,
            self.s3_service.artifacts_bucket,
            s3_path,
        )
        return s3_path

    def _generate_html_report(
        self,
        run: Run,
        artifacts: list[Artifact],
        annotation_revisions: list[AnnotationRevision],
    ) -> str:
        """Generate an HTML reproducibility report string from run data.

        Pure function — no I/O, making it directly testable.

        Args:
            run: Run model instance
            artifacts: List of Artifact model instances
            annotation_revisions: List of AnnotationRevision model instances

        Returns:
            HTML string for the reproducibility report
        """
        run_id = str(run.id)
        status = run.status.value if hasattr(run.status, "value") else str(run.status)
        started_at = run.started_at.isoformat() if run.started_at else "N/A"
        completed_at = run.completed_at.isoformat() if run.completed_at else "N/A"

        if run.started_at and run.completed_at:
            duration_secs = (run.completed_at - run.started_at).total_seconds()
            duration = f"{duration_secs:.0f}s"
        else:
            duration = "N/A"

        # --- Pipeline parameters ---
        parameters = run.parameters or {}
        params_rows = (
            "".join(
                f"<tr><td>{_html_escape(str(k))}</td><td>{_html_escape(str(v))}</td></tr>"
                for k, v in parameters.items()
            )
            or "<tr><td colspan='2'><em>No parameters recorded</em></td></tr>"
        )

        # --- Software versions ---
        software_versions = run.software_versions or {}
        sw_rows = (
            "".join(
                f"<tr><td>{_html_escape(str(k))}</td><td>{_html_escape(str(v))}</td></tr>"
                for k, v in software_versions.items()
            )
            or "<tr><td colspan='2'><em>No software versions recorded</em></td></tr>"
        )

        # --- Random seeds ---
        seeds: dict = {}
        if run.random_seed is not None:
            seeds["global_random_seed"] = run.random_seed
        for k, v in parameters.items():
            if "seed" in str(k).lower():
                seeds[k] = v
        seed_rows = (
            "".join(
                f"<tr><td>{_html_escape(str(k))}</td><td>{_html_escape(str(v))}</td></tr>"
                for k, v in seeds.items()
            )
            or "<tr><td colspan='2'><em>No random seeds recorded</em></td></tr>"
        )

        # --- KnowledgePack versions ---
        kp_entries: list[dict] = []
        for rev in annotation_revisions:
            if rev.knowledge_pack_id is not None:
                kp = getattr(rev, "knowledge_pack", None)
                kp_entries.append(
                    {
                        "revision": rev.revision_number,
                        "knowledge_pack_id": str(rev.knowledge_pack_id),
                        "name": kp.name if kp else "N/A",
                        "version": kp.version if kp else "N/A",
                        "pack_type": (
                            kp.pack_type.value
                            if kp and hasattr(kp.pack_type, "value")
                            else str(kp.pack_type)
                            if kp
                            else "N/A"
                        ),
                    }
                )
        kp_rows = (
            "".join(
                f"<tr>"
                f"<td>{e['revision']}</td>"
                f"<td>{_html_escape(e['knowledge_pack_id'])}</td>"
                f"<td>{_html_escape(e['name'])}</td>"
                f"<td>{_html_escape(e['version'])}</td>"
                f"<td>{_html_escape(e['pack_type'])}</td>"
                f"</tr>"
                for e in kp_entries
            )
            or "<tr><td colspan='5'><em>No KnowledgePack versions recorded</em></td></tr>"
        )

        # --- Provenance / artifacts ---
        artifact_rows = (
            "".join(
                f"<tr>"
                f"<td>{_html_escape(str(a.id))}</td>"
                f"<td>{_html_escape(a.artifact_type.value if hasattr(a.artifact_type, 'value') else str(a.artifact_type))}</td>"
                f"<td>{_html_escape(a.s3_path)}</td>"
                f"<td>{a.size_bytes if a.size_bytes is not None else 'N/A'}</td>"
                f"</tr>"
                for a in artifacts
            )
            or "<tr><td colspan='4'><em>No artifacts recorded</em></td></tr>"
        )

        # --- Annotation history ---
        annotation_rows = (
            "".join(
                f"<tr>"
                f"<td>{rev.revision_number}</td>"
                f"<td>{_html_escape(rev.method or 'N/A')}</td>"
                f"<td>{rev.created_at.isoformat() if rev.created_at else 'N/A'}</td>"
                f"</tr>"
                for rev in annotation_revisions
            )
            or "<tr><td colspan='3'><em>No annotation revisions recorded</em></td></tr>"
        )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Reproducibility Report — Run {_html_escape(run_id)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2em; color: #222; }}
    h1 {{ color: #2c3e50; }}
    h2 {{ color: #34495e; border-bottom: 1px solid #ccc; padding-bottom: 4px; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5em; }}
    th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
    th {{ background: #f4f4f4; }}
    tr:nth-child(even) {{ background: #fafafa; }}
  </style>
</head>
<body>
  <h1>Reproducibility Report</h1>

  <h2>Run Summary</h2>
  <table>
    <tr><th>Field</th><th>Value</th></tr>
    <tr><td>Run ID</td><td>{_html_escape(run_id)}</td></tr>
    <tr><td>Status</td><td>{_html_escape(status)}</td></tr>
    <tr><td>Started At</td><td>{_html_escape(started_at)}</td></tr>
    <tr><td>Completed At</td><td>{_html_escape(completed_at)}</td></tr>
    <tr><td>Duration</td><td>{_html_escape(duration)}</td></tr>
  </table>

  <h2>Pipeline Parameters</h2>
  <table>
    <tr><th>Parameter</th><th>Value</th></tr>
    {params_rows}
  </table>

  <h2>Software Versions</h2>
  <table>
    <tr><th>Package</th><th>Version</th></tr>
    {sw_rows}
  </table>

  <h2>Random Seeds</h2>
  <table>
    <tr><th>Seed Name</th><th>Value</th></tr>
    {seed_rows}
  </table>

  <h2>KnowledgePack Versions</h2>
  <table>
    <tr><th>Revision</th><th>KnowledgePack ID</th><th>Name</th><th>Version</th><th>Type</th></tr>
    {kp_rows}
  </table>

  <h2>Provenance (Artifacts)</h2>
  <table>
    <tr><th>Artifact ID</th><th>Type</th><th>S3 Path</th><th>Size (bytes)</th></tr>
    {artifact_rows}
  </table>

  <h2>Annotation History</h2>
  <table>
    <tr><th>Revision</th><th>Method</th><th>Created At</th></tr>
    {annotation_rows}
  </table>
</body>
</html>"""
        return html

    async def _load_or_create_adata(
        self, h5ad_artifact: Artifact | None, tmp_dir: Path
    ) -> ad.AnnData:
        """Download and load the primary h5ad artifact, or create a minimal one."""
        if h5ad_artifact is None:
            logger.info("No h5ad artifact found; creating minimal AnnData with metadata only")
            # Use explicit object-dtype DataFrames to avoid Arrow-backed string index issues
            return ad.AnnData(
                obs=pd.DataFrame(index=pd.Index([], dtype="object")),
                var=pd.DataFrame(index=pd.Index([], dtype="object")),
            )

        try:
            local_path = tmp_dir / "source.h5ad"
            s3_path = h5ad_artifact.s3_path

            # Normalise s3:// prefix
            if s3_path.startswith("s3://"):
                s3_path = s3_path[5:]

            parts = s3_path.split("/", 1)
            if len(parts) == 2:
                bucket, key = parts
            else:
                bucket = self.s3_service.artifacts_bucket
                key = s3_path

            self.s3_service.s3_client.download_file(bucket, key, str(local_path))
            return ad.read_h5ad(local_path)

        except Exception as exc:
            logger.warning(
                "Failed to download/load h5ad artifact %s: %s. Falling back to minimal AnnData.",
                h5ad_artifact.id,
                exc,
            )
            return ad.AnnData()

    def _add_annotations(
        self, adata: ad.AnnData, revisions: list[AnnotationRevision]
    ) -> ad.AnnData:
        """Add annotation revisions to obs columns and uns."""
        if not revisions:
            return adata

        # Store all revisions in uns for provenance (as JSON string for h5ad compatibility)
        adata.uns["zerna_annotation_revisions"] = json.dumps(
            [
                {
                    "revision_id": str(rev.id),
                    "revision_number": rev.revision_number,
                    "method": rev.method or "",
                    "knowledge_pack_id": str(rev.knowledge_pack_id)
                    if rev.knowledge_pack_id
                    else "",
                    "approved_by": str(rev.approved_by) if rev.approved_by else "",
                    "approved_at": rev.approved_at.isoformat() if rev.approved_at else "",
                    "created_at": rev.created_at.isoformat(),
                }
                for rev in revisions
            ]
        )

        # Apply the latest revision's per-cell annotations to obs
        latest = revisions[-1]
        annotations: dict = latest.annotations or {}

        if not annotations:
            return adata

        # Determine if annotations are keyed by cell barcode or are column-level dicts
        # Expected format: {cell_id: {tissue, lineage, cell_type, confidence, ...}}
        # or flat column dicts: {column_name: {cell_id: value}}
        sample_value = next(iter(annotations.values()), None)

        if isinstance(sample_value, dict):
            # Per-cell dict format: {cell_id: {field: value}}
            annotation_df = pd.DataFrame.from_dict(annotations, orient="index")

            if adata.n_obs > 0:
                # Align to existing obs index where possible
                common_cells = annotation_df.index.intersection(adata.obs_names)
                if len(common_cells) > 0:
                    for col in annotation_df.columns:
                        col_name = f"zerna_{col}"
                        adata.obs[col_name] = annotation_df.loc[
                            adata.obs_names.intersection(annotation_df.index), col
                        ].reindex(adata.obs_names)
                else:
                    # No matching barcodes; store as uns only
                    adata.uns["zerna_annotations_latest"] = annotations
            else:
                # No cells in adata; store raw annotations in uns
                adata.uns["zerna_annotations_latest"] = annotations
        else:
            # Flat format: {column_name: value_per_cell_or_scalar}
            adata.uns["zerna_annotations_latest"] = annotations

        return adata

    def _add_run_metadata(
        self, adata: ad.AnnData, run: Run, artifacts: list[Artifact]
    ) -> ad.AnnData:
        """Add run metadata and artifact references to uns."""

        adata.uns["zerna_run_metadata"] = {
            "run_id": str(run.id),
            "org_id": str(run.organization_id),
            "dataset_version_id": str(run.source_dataset_version_id)
            if run.source_dataset_version_id is not None
            else None,
            "template_id": str(run.template_id),
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "parameters": run.parameters or {},
            "software_versions": run.software_versions or {},
            "random_seed": run.random_seed if run.random_seed is not None else -1,
            "started_at": run.started_at.isoformat() if run.started_at else "",
            "completed_at": run.completed_at.isoformat() if run.completed_at else "",
            "created_at": run.created_at.isoformat() if run.created_at else "",
            "exported_at": datetime.now(UTC).isoformat(),
        }

        adata.uns["zerna_artifacts"] = json.dumps(
            [
                {
                    "artifact_id": str(a.id),
                    "artifact_type": a.artifact_type.value
                    if hasattr(a.artifact_type, "value")
                    else str(a.artifact_type),
                    "s3_path": a.s3_path,
                    "size_bytes": a.size_bytes if a.size_bytes is not None else 0,
                }
                for a in artifacts
            ]
        )

        return adata
