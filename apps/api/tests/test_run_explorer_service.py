"""Tests for rebuilding completed-run explorer payloads from run artifacts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import anndata as ad
import numpy as np
import pytest
import pytest_asyncio
from zerna_contracts.enums import ArtifactType, RunStatus
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.models import (
    Artifact,
    Base,
    Dataset,
    DatasetVersion,
    Organization,
    PipelineTemplate,
    Run,
)
from apps.api.services.run_explorer_service import (
    RunExplorerService,
    resolve_explorer_source_column,
)


@pytest_asyncio.fixture(scope="module")
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


async def get_clean_session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(delete(table))
        await session.commit()
        return session


class DummyS3Client:
    def __init__(self, source_path: Path) -> None:
        self.source_path = source_path
        self.download_count = 0

    def download_file(self, bucket: str, key: str, destination: str) -> None:
        del bucket, key
        self.download_count += 1
        shutil.copyfile(self.source_path, destination)


class DummyS3Service:
    def __init__(self, source_path: Path) -> None:
        self.s3_client = DummyS3Client(source_path)
        self.artifacts_bucket = "zerna-artifacts-dev"


async def _make_run_with_artifact(
    session: AsyncSession,
    artifact_path: str,
) -> tuple[Organization, Run]:
    org = Organization(id=uuid4(), name="Org", storage_quota_gb=100, compute_quota_runs=10)
    session.add(org)
    await session.flush()

    dataset = Dataset(id=uuid4(), organization_id=org.id, name="DS")
    session.add(dataset)
    await session.flush()

    version = DatasetVersion(
        id=uuid4(),
        dataset_id=dataset.id,
        version="v1",
        s3_path="s3://datasets/source.h5ad",
    )
    session.add(version)
    await session.flush()

    template = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name="robust",
        version="v1",
        definition={},
    )
    session.add(template)
    await session.flush()

    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=version.id,
        template_id=template.id,
        status=RunStatus.COMPLETED,
        parameters={},
    )
    session.add(run)
    await session.flush()

    artifact = Artifact(
        id=uuid4(),
        run_id=run.id,
        artifact_type=ArtifactType.H5AD,
        s3_path=artifact_path,
        size_bytes=123,
        extra_metadata={},
    )
    session.add(artifact)
    await session.commit()
    return org, run


def _write_explorer_h5ad(path: Path) -> None:
    adata = ad.AnnData(X=np.ones((4, 3), dtype=np.float32))
    adata.obs_names = [f"cell_{idx}" for idx in range(4)]
    adata.var_names = ["CD3D", "MS4A1", "LYZ"]
    adata.obs["leiden"] = ["0", "0", "1", "1"]
    adata.obs["annotation_label"] = ["T cell", "T cell", "B cell", "B cell"]
    adata.obs["annotation_lineage"] = ["Lymphoid", "Lymphoid", "Lymphoid", "Lymphoid"]
    adata.obs["annotation_confidence"] = ["high", "high", "medium", "medium"]
    adata.obs["sample"] = ["S1", "S1", "S2", "S2"]
    adata.obs["condition"] = ["Tumor", "Tumor", "Normal", "Normal"]
    adata.obsm["X_umap"] = np.array(
        [[0.0, 0.1], [0.2, 0.3], [1.0, 1.1], [1.2, 1.3]],
        dtype=np.float32,
    )
    adata.uns["cluster_markers"] = {
        "0": ["CD3D", "TRBC1"],
        "1": ["MS4A1", "CD79A"],
    }
    adata.uns["zerna_cluster_annotations"] = json.dumps(
        {
            "0": {
                "summary": "T cell cluster",
                "normalized_label": "T cell",
                "confidence": "high",
                "mode": "celltypist_consensus",
                "supporting_markers": {"T cell": ["CD3D", "TRBC1"]},
                "top_cell_types": [
                    {"cell_type": "T cell", "score": 0.91, "n_markers": 6},
                    {"cell_type": "NK cell", "score": 0.12, "n_markers": 1},
                ],
                "cluster_markers": ["CD3D", "TRBC1"],
            },
            "1": {
                "summary": "B cell cluster",
                "normalized_label": "B cell",
                "confidence": "medium",
                "top_cell_types": [
                    {"cell_type": "B cell", "score": 0.73, "n_markers": 4},
                ],
                "cluster_markers": ["MS4A1", "CD79A"],
            },
        }
    )
    adata.uns["cluster_retrieval_evidence"] = json.dumps(
        {
            "0": {
                "evidence": [
                    {"cluster_id": "prior_0", "level3_label": "T cell", "score": 0.88},
                ]
            },
            "1": {
                "evidence": [
                    {"cluster_id": "prior_1", "level3_label": "B cell", "score": 0.61},
                ]
            },
        }
    )
    adata.write_h5ad(path)


def _write_explorer_h5ad_with_hierarchy(path: Path) -> None:
    """Artifact with canonical ``final_display`` + ``auto_level*`` (new runtime) and raw ``annotation_label``."""
    adata = ad.AnnData(X=np.ones((2, 2), dtype=np.float32))
    adata.obs_names = ["cell_a", "cell_b"]
    adata.obs["leiden"] = ["0", "0"]
    adata.obs["final_display"] = ["Immune | T cells | CD8", "Immune | T cells | CD8"]
    adata.obs["annotation_label"] = ["CD8 T cell", "CD8 T cell"]
    adata.obs["annotation_lineage"] = ["Immune", "Immune"]
    adata.obs["auto_level1"] = ["Immune", "Immune"]
    adata.obs["auto_level2"] = ["T cells", "T cells"]
    adata.obs["auto_level3"] = ["CD8", "CD8"]
    adata.obs["annotation_confidence"] = ["high", "high"]
    adata.obsm["X_umap"] = np.array([[0.0, 0.1], [0.2, 0.3]], dtype=np.float32)
    adata.write_h5ad(path)


def _write_explorer_h5ad_with_stale_auto_level3(path: Path) -> None:
    """Artifact where final_display carries a finer subtype than stale auto/zr columns."""
    adata = ad.AnnData(X=np.ones((2, 2), dtype=np.float32))
    adata.obs_names = ["cell_a", "cell_b"]
    adata.obs["leiden"] = ["0", "0"]
    adata.obs["auto_level1"] = ["Stromal", "Immune"]
    adata.obs["auto_level2"] = ["Fibroblasts", "T cells"]
    adata.obs["auto_level3"] = ["Fibroblasts", "T cells"]
    adata.obs["level3_final_safe"] = ["myCAF", "CD8"]
    adata.obs["final_display"] = [
        "Stromal | Fibroblasts | myCAF",
        "Immune | T cells | CD8",
    ]
    adata.obs["zr_display"] = [
        "Stromal|Fibroblasts|Fibroblasts",
        "Immune|T cells|T cells",
    ]
    adata.obs["annotation_label"] = ["myCAF", "CD8 T cell"]
    adata.obs["annotation_lineage"] = ["Stromal", "Immune"]
    adata.obs["annotation_confidence"] = ["high", "high"]
    adata.obsm["X_umap"] = np.array([[0.0, 0.1], [0.2, 0.3]], dtype=np.float32)
    adata.write_h5ad(path)


def _write_explorer_h5ad_with_p2_lineage(path: Path) -> None:
    n = 6
    adata = ad.AnnData(X=np.ones((n, 2), dtype=np.float32))
    adata.obs_names = [f"c{i}" for i in range(n)]
    adata.obs["leiden"] = [str(i % 2) for i in range(n)]
    adata.obs["global_cluster"] = list(adata.obs["leiden"])
    adata.obs["auto_level1"] = ["Immune"] * 4 + ["Stromal"] * 2
    adata.obs["auto_level2"] = ["T cells"] * 4 + ["Fibroblasts"] * 2
    adata.obs["auto_level3"] = ["CD4", "CD4", "CD8", "CD8", "iCAF", "iCAF"]
    adata.obs["final_display"] = ["Immune | T cells | CD4"] * 4 + [
        "Stromal | Fibroblasts | iCAF"
    ] * 2
    adata.obs["lineage_subcluster"] = ["Immune:0", "Immune:0", "Immune:1", "Immune:1", "", ""]
    adata.obs["annotation_label"] = ["CD4 T", "CD4 T", "CD8 T", "CD8 T", "FB", "FB"]
    adata.obs["annotation_lineage"] = ["Immune"] * 4 + ["Stromal"] * 2
    adata.obsm["X_umap"] = np.array(
        [[float(i), float(i) * 0.1] for i in range(n)], dtype=np.float32
    )
    lu = np.full((n, 2), np.nan, dtype=np.float32)
    lu[:4, :] = np.array([[0.1 * i, 0.2 * i] for i in range(4)], dtype=np.float32)
    adata.obsm["X_umap_lineage_immune"] = lu
    adata.uns["zerna_cluster_annotations"] = json.dumps(
        {
            "0": {
                "normalized_label": "CD4 T",
                "summary": "CD4 helper",
                "confidence": "high",
                "supporting_markers": {"CD4 T": ["CD4", "IL7R"]},
                "top_cell_types": [
                    {"cell_type": "CD4 T", "score": 0.9, "n_markers": 3},
                    {"cell_type": "CD8 T", "score": 0.15, "n_markers": 1},
                ],
            },
            "1": {
                "normalized_label": "CD8 T",
                "summary": "CD8 cytotoxic",
                "confidence": "high",
                "supporting_markers": {"CD8 T": ["CD8A", "GZMB"]},
                "top_cell_types": [
                    {"cell_type": "CD8 T", "score": 0.85, "n_markers": 2},
                ],
            },
        }
    )
    adata.uns["cluster_retrieval_evidence"] = json.dumps(
        {
            "0": {"evidence": [{"level3_label": "CD4 T", "score": 0.8}]},
            "1": {"evidence": [{"level3_label": "CD8 T", "score": 0.7}]},
        }
    )
    adata.uns["cluster_markers"] = {"0": ["G0A", "G0B"], "1": ["G1A", "G1B"]}
    adata.uns["explorer_partition_inspector_v1"] = json.dumps(
        {
            "version": 1,
            "lineage_subcluster": {
                "Immune:0": {
                    "normalized_label": "CD4 T",
                    "summary": "CD4 helper",
                    "confidence": "high",
                    "cluster_markers": ["LINEAGE_CD4_A", "LINEAGE_CD4_B"],
                    "supporting_markers": {"CD4 T": ["CD4", "IL7R"]},
                    "top_cell_types": [
                        {"cell_type": "CD4 T", "score": 0.9, "n_markers": 3},
                        {"cell_type": "CD8 T", "score": 0.15, "n_markers": 1},
                    ],
                    "_retrieval_source_cluster": "0",
                    "partition_annotation_support_markers": ["LINEAGE_CD4_A", "CD4"],
                },
                "Immune:1": {
                    "normalized_label": "CD8 T",
                    "summary": "CD8 cytotoxic",
                    "confidence": "high",
                    "cluster_markers": ["LINEAGE_CD8_A", "LINEAGE_CD8_B"],
                    "supporting_markers": {"CD8 T": ["CD8A", "GZMB"]},
                    "top_cell_types": [
                        {"cell_type": "CD8 T", "score": 0.85, "n_markers": 2},
                    ],
                    "_retrieval_source_cluster": "1",
                },
            },
            "fine_subcluster": {},
        }
    )
    adata.write_h5ad(path)


def _write_explorer_h5ad_with_p2_lineage_epithelial(path: Path) -> None:
    """Artifact with P2 epithelial lineage UMAP + partition inspector (one non-epi cell for overview)."""
    n = 5
    adata = ad.AnnData(X=np.ones((n, 2), dtype=np.float32))
    adata.obs_names = [f"c{i}" for i in range(n)]
    adata.obs["leiden"] = [str(i % 2) for i in range(n)]
    adata.obs["global_cluster"] = list(adata.obs["leiden"])
    adata.obs["auto_level1"] = ["Immune"] + ["Epithelial"] * 4
    adata.obs["auto_level2"] = ["T cells"] + ["Luminal epithelial"] * 4
    adata.obs["auto_level3"] = ["CD4"] + ["Luminal"] * 4
    adata.obs["final_display"] = ["Immune | T cells | CD4"] + [
        "Epithelial | Luminal epithelial | Luminal"
    ] * 4
    adata.obs["lineage_subcluster"] = [
        "",
        "Epithelial:0",
        "Epithelial:0",
        "Epithelial:1",
        "Epithelial:1",
    ]
    adata.obs["annotation_label"] = ["CD4 T"] + ["Luminal"] * 4
    adata.obs["annotation_lineage"] = ["Immune"] + ["Epithelial"] * 4
    adata.obs["annotation_confidence"] = ["high"] * n
    adata.obsm["X_umap"] = np.array(
        [[float(i), float(i) * 0.1] for i in range(n)], dtype=np.float32
    )
    lu = np.full((n, 2), np.nan, dtype=np.float32)
    lu[1:5, :] = np.array([[0.1 * i, 0.2 * i] for i in range(4)], dtype=np.float32)
    adata.obsm["X_umap_lineage_epithelial"] = lu
    adata.uns["zerna_cluster_annotations"] = json.dumps(
        {
            "0": {
                "normalized_label": "Luminal mature",
                "summary": "luminal",
                "confidence": "high",
                "supporting_markers": {"Luminal epithelial": ["KRT8", "KRT18"]},
                "top_cell_types": [
                    {"cell_type": "Luminal mature", "score": 0.9, "n_markers": 2},
                ],
            },
            "1": {
                "normalized_label": "Luminal stress",
                "summary": "stress",
                "confidence": "medium",
                "supporting_markers": {"Luminal epithelial": ["ATF3", "HSPA1A"]},
                "top_cell_types": [
                    {"cell_type": "Luminal stress", "score": 0.7, "n_markers": 1},
                ],
            },
        }
    )
    adata.uns["cluster_retrieval_evidence"] = json.dumps(
        {
            "0": {"evidence": [{"level3_label": "Luminal mature", "score": 0.8}]},
            "1": {"evidence": [{"level3_label": "Luminal stress", "score": 0.65}]},
        }
    )
    adata.uns["cluster_markers"] = {"0": ["E0A", "E0B"], "1": ["E1A", "E1B"]}
    adata.uns["explorer_partition_inspector_v1"] = json.dumps(
        {
            "version": 1,
            "lineage_subcluster": {
                "Epithelial:0": {
                    "normalized_label": "Luminal mature",
                    "summary": "luminal",
                    "confidence": "high",
                    "cluster_markers": ["EPI_L0_A", "EPI_L0_B"],
                    "supporting_markers": {"Luminal epithelial": ["KRT8", "KRT18"]},
                    "top_cell_types": [
                        {"cell_type": "Luminal mature", "score": 0.9, "n_markers": 2},
                    ],
                    "_retrieval_source_cluster": "0",
                    "partition_annotation_support_markers": ["EPI_L0_A", "KRT8"],
                },
                "Epithelial:1": {
                    "normalized_label": "Luminal stress",
                    "summary": "stress",
                    "confidence": "medium",
                    "cluster_markers": ["EPI_L1_A", "EPI_L1_B"],
                    "supporting_markers": {"Luminal epithelial": ["ATF3", "HSPA1A"]},
                    "top_cell_types": [
                        {"cell_type": "Luminal stress", "score": 0.7, "n_markers": 1},
                    ],
                    "_retrieval_source_cluster": "1",
                    "partition_annotation_support_markers": ["EPI_L1_A", "ATF3"],
                },
            },
            "fine_subcluster": {},
        }
    )
    adata.write_h5ad(path)


def _write_explorer_h5ad_with_p3_fine_t_cells(path: Path) -> None:
    n = 5
    adata = ad.AnnData(X=np.ones((n, 2), dtype=np.float32))
    adata.obs_names = [f"c{i}" for i in range(n)]
    adata.obs["leiden"] = [str(i % 2) for i in range(n)]
    adata.obs["global_cluster"] = list(adata.obs["leiden"])
    adata.obs["auto_level1"] = ["Immune"] * n
    adata.obs["auto_level2"] = ["T cells"] * n
    adata.obs["auto_level3"] = ["CD4"] * n
    adata.obs["final_display"] = ["Immune | T cells | CD4"] * n
    adata.obs["annotation_label"] = ["CD4 T"] * n
    adata.obs["annotation_confidence"] = ["high"] * n
    adata.obs["fine_subcluster"] = ["T_cells:0", "T_cells:0", "T_cells:1", "T_cells:1", "T_cells:0"]
    adata.obsm["X_umap"] = np.array(
        [[float(i), float(i) * 0.1] for i in range(n)], dtype=np.float32
    )
    fu = np.zeros((n, 2), dtype=np.float32)
    for i in range(n):
        fu[i, :] = [0.5 * i, 0.3 * i]
    adata.obsm["X_umap_fine_t_cells"] = fu
    adata.uns["zerna_cluster_annotations"] = json.dumps(
        {
            "0": {
                "normalized_label": "CD4 T naive",
                "summary": "naive cd4",
                "confidence": "high",
                "supporting_markers": {"CD4 T naive": ["CCR7", "LEF1"]},
                "top_cell_types": [
                    {"cell_type": "CD4 T naive", "score": 0.88, "n_markers": 2},
                    {"cell_type": "CD4 T cm", "score": 0.2, "n_markers": 1},
                ],
            },
            "1": {
                "normalized_label": "CD4 T em",
                "summary": "em cd4",
                "confidence": "medium",
                "supporting_markers": {"CD4 T em": ["GZMK"]},
                "top_cell_types": [
                    {"cell_type": "CD4 T em", "score": 0.75, "n_markers": 2},
                ],
            },
        }
    )
    adata.uns["cluster_retrieval_evidence"] = json.dumps(
        {
            "0": {"evidence": [{"level3_label": "CD4 T naive", "score": 0.72}]},
            "1": {"evidence": [{"level3_label": "CD4 T em", "score": 0.65}]},
        }
    )
    adata.uns["cluster_markers"] = {"0": ["X0"], "1": ["X1"]}
    adata.uns["explorer_partition_inspector_v1"] = json.dumps(
        {
            "version": 1,
            "lineage_subcluster": {},
            "fine_subcluster": {
                "T_cells:0": {
                    "normalized_label": "CD4 T naive",
                    "summary": "naive cd4",
                    "confidence": "high",
                    "cluster_markers": ["FINE_NAIVE_A", "FINE_NAIVE_B"],
                    "supporting_markers": {"CD4 T naive": ["CCR7", "LEF1"]},
                    "top_cell_types": [
                        {"cell_type": "CD4 T naive", "score": 0.88, "n_markers": 2},
                        {"cell_type": "CD4 T cm", "score": 0.2, "n_markers": 1},
                    ],
                    "_retrieval_source_cluster": "0",
                    "partition_annotation_support_markers": ["FINE_NAIVE_A", "CCR7"],
                },
                "T_cells:1": {
                    "normalized_label": "CD4 T em",
                    "summary": "em cd4",
                    "confidence": "medium",
                    "cluster_markers": ["FINE_EM_A"],
                    "supporting_markers": {"CD4 T em": ["GZMK"]},
                    "top_cell_types": [
                        {"cell_type": "CD4 T em", "score": 0.75, "n_markers": 2},
                    ],
                    "_retrieval_source_cluster": "1",
                },
            },
        }
    )
    adata.write_h5ad(path)


@pytest.mark.asyncio
async def test_run_explorer_global_exposes_structural_level3_cohort_filters_on_modern_artifacts(
    async_engine, tmp_path: Path
):
    source = tmp_path / "explorer_p2_global_axes.h5ad"
    _write_explorer_h5ad_with_p2_lineage(source)

    session = await get_clean_session(async_engine)
    org, run = await _make_run_with_artifact(session, "runs/test/p2_global_axes.h5ad")

    svc = RunExplorerService(session, s3_service=DummyS3Service(source))
    payload = await svc.get_run_explorer(run.id, org.id, max_cells=50, explorer_view="global")

    assert "lineageSubcluster" not in payload["filter_fields"]
    assert "fineSubcluster" not in payload["filter_fields"]
    assert "level2" not in payload["filter_fields"]
    assert "level3" not in payload["filter_fields"]
    assert "level2" in payload["advanced_filter_fields"]
    assert "level3" in payload["advanced_filter_fields"]
    assert "level2" in payload["filter_values"]
    assert "level3" in payload["filter_values"]
    assert set(payload["filter_values"]["level2"]) == {"T cells", "Fibroblasts"}
    assert set(payload["filter_values"]["level3"]) == {"CD4", "CD8", "iCAF"}
    assert "lineageSubcluster" in payload["advanced_filter_fields"]
    assert "cluster" in payload["advanced_filter_fields"]
    axes = payload["hierarchy_filter_axes"]
    assert axes["level2_by_lineage"]["Immune"] == ["T cells"]
    assert axes["level2_by_lineage"]["Stromal"] == ["Fibroblasts"]
    assert axes["level3_by_lineage_major"]["Immune|T cells"] == ["CD4", "CD8"]
    assert axes["level3_by_lineage_major"]["Stromal|Fibroblasts"] == ["iCAF"]
    await session.close()


@pytest.mark.asyncio
async def test_run_explorer_legacy_artifact_omits_level3_from_cohort_filter_values(
    async_engine, tmp_path: Path
):
    """Non-canonical artifacts: no structural L3 filter chips (avoids rawAnnotationLabel-driven buckets)."""
    source = tmp_path / "explorer_legacy_l3_filters.h5ad"
    _write_explorer_h5ad(source)
    session = await get_clean_session(async_engine)
    org, run = await _make_run_with_artifact(session, "runs/test/legacy_l3.h5ad")
    svc = RunExplorerService(session, s3_service=DummyS3Service(source))
    payload = await svc.get_run_explorer(run.id, org.id, max_cells=50, explorer_view="global")
    assert "level3" not in payload.get("filter_values", {})
    await session.close()


def _write_explorer_h5ad_modern_mast_plasma(path: Path) -> None:
    """Canonical modern artifact: immune mast + plasma rows with singleton structural L3."""
    n = 4
    adata = ad.AnnData(X=np.ones((n, 2), dtype=np.float32))
    adata.obs_names = [f"c{i}" for i in range(n)]
    adata.obs["leiden"] = ["0", "0", "1", "1"]
    adata.obs["global_cluster"] = list(adata.obs["leiden"])
    adata.obs["auto_level1"] = ["Immune"] * n
    adata.obs["auto_level2"] = ["Mast cells", "Mast cells", "Plasma cells", "Plasma cells"]
    adata.obs["auto_level3"] = ["Mast cells", "Mast cells", "Plasma cells", "Plasma cells"]
    adata.obs["final_display"] = [
        "Immune | Mast cells | Mast cells",
        "Immune | Mast cells | Mast cells",
        "Immune | Plasma cells | Plasma cells",
        "Immune | Plasma cells | Plasma cells",
    ]
    adata.obs["annotation_label"] = ["Mast", "Mast", "Plasma", "Plasma"]
    adata.obs["annotation_lineage"] = ["Immune"] * n
    adata.obs["annotation_confidence"] = ["high"] * n
    adata.obs["sample"] = ["S1", "S1", "S2", "S2"]
    adata.obs["condition"] = ["Tumor"] * n
    adata.obsm["X_umap"] = np.array([[float(i), 0.1 * i] for i in range(n)], dtype=np.float32)
    adata.write_h5ad(path)


@pytest.mark.asyncio
async def test_run_explorer_mast_plasma_singleton_structural_l3_in_filters_and_axes(
    async_engine, tmp_path: Path
):
    source = tmp_path / "explorer_mast_plasma.h5ad"
    _write_explorer_h5ad_modern_mast_plasma(source)
    session = await get_clean_session(async_engine)
    org, run = await _make_run_with_artifact(session, "runs/test/mast_plasma.h5ad")
    svc = RunExplorerService(session, s3_service=DummyS3Service(source))
    payload = await svc.get_run_explorer(run.id, org.id, max_cells=50, explorer_view="global")
    axes = payload["hierarchy_filter_axes"]
    assert set(axes["level2_by_lineage"]["Immune"]) >= {"Mast cells", "Plasma cells"}
    assert axes["level3_by_lineage_major"]["Immune|Mast cells"] == ["Mast cells"]
    assert axes["level3_by_lineage_major"]["Immune|Plasma cells"] == ["Plasma cells"]
    assert set(payload["filter_values"]["level3"]) == {"Mast cells", "Plasma cells"}
    for row in payload["metadata"]:
        assert row["level3"] in ("Mast cells", "Plasma cells")
    await session.close()


@pytest.mark.asyncio
async def test_run_explorer_prefers_final_display_and_exposes_hierarchy(
    async_engine, tmp_path: Path
):
    source = tmp_path / "explorer_hier.h5ad"
    _write_explorer_h5ad_with_hierarchy(source)

    session = await get_clean_session(async_engine)
    org, run = await _make_run_with_artifact(session, "runs/test/processed.h5ad")

    svc = RunExplorerService(session, s3_service=DummyS3Service(source))
    payload = await svc.get_run_explorer(run.id, org.id, max_cells=10)

    assert payload["metadata"][0]["cellType"] == "Immune | T cells | CD8"
    assert payload["metadata"][0]["lineage"] == "Immune"
    assert payload["metadata"][0]["level2"] == "T cells"
    assert payload["metadata"][0]["level3"] == "CD8"
    fields = payload["available_fields"]
    assert "cellType" in fields
    assert "lineage" in fields
    assert "level2" in fields
    assert "level3" in fields
    assert "rawAnnotationLabel" in fields
    assert len(payload["cluster_summaries"]) == 1
    assert payload["cluster_summaries"][0]["label"] == "Immune | T cells | CD8"
    await session.close()


def test_cluster_summaries_lineage_partition_falls_back_to_dominant_global():
    """Without ``explorer_partition_inspector_v1``, lineage summaries use dominant ``global_cluster``."""
    svc = RunExplorerService.__new__(RunExplorerService)
    adata = ad.AnnData(X=np.ones((4, 2), dtype=np.float32))
    adata.obs["lineage_subcluster"] = ["Immune:0", "Immune:0", "Immune:1", "Immune:1"]
    adata.obs["global_cluster"] = ["0", "0", "1", "1"]
    adata.obs["annotation_label"] = ["a", "a", "b", "b"]
    adata.obs["annotation_confidence"] = ["high"] * 4
    adata.uns["zerna_cluster_annotations"] = {
        "0": {
            "normalized_label": "TypeA",
            "top_cell_types": [
                {"cell_type": "TypeA", "score": 0.9, "n_markers": 1},
                {"cell_type": "Other", "score": 0.1, "n_markers": 1},
            ],
            "supporting_markers": {"TypeA": ["gA"]},
        },
        "1": {
            "normalized_label": "TypeB",
            "top_cell_types": [{"cell_type": "TypeB", "score": 0.85, "n_markers": 1}],
            "supporting_markers": {"TypeB": ["gB"]},
        },
    }
    adata.uns["cluster_markers"] = {"0": ["m0a", "m0b"], "1": ["m1a"]}
    adata.uns["cluster_retrieval_evidence"] = {
        "0": {"evidence": [{"level3_label": "TypeA", "score": 0.5}]},
        "1": {"evidence": [{"level3_label": "TypeB", "score": 0.4}]},
    }
    summaries = svc._build_cluster_summaries(
        adata=adata,
        cluster_series=adata.obs["lineage_subcluster"],
        cell_type_series=adata.obs["annotation_label"],
        confidence_bucket_series=adata.obs["annotation_confidence"],
        partition_kind="lineage_subcluster",
        global_cluster_series=adata.obs["global_cluster"],
    )
    imm0 = next(s for s in summaries if s["cluster_id"] == "Immune:0")
    assert imm0["top_markers"][:2] == ["m0a", "m0b"]
    assert imm0["runner_up_labels"] and imm0["runner_up_labels"][0]["cell_type"] == "Other"
    assert imm0["evidence_hits"][0]["label"] == "TypeA"


def test_cluster_summaries_tuple_top_cell_types_yield_runner_ups():
    """Agent-shaped ``(cell_type, score, n_markers)`` tuples must map to runner-up evidence."""
    svc = RunExplorerService.__new__(RunExplorerService)
    adata = ad.AnnData(X=np.ones((2, 2), dtype=np.float32))
    adata.obs["leiden"] = ["0", "0"]
    adata.obs["annotation_label"] = ["T cell", "T cell"]
    adata.obs["annotation_confidence"] = ["high", "high"]
    adata.uns["cluster_markers"] = {"0": ["G1", "G2"]}
    adata.uns["zerna_cluster_annotations"] = {
        "0": {
            "normalized_label": "T cell",
            "top_cell_types": [
                ("ct_best", 0.91, 6),
                ("ct_runner", 0.12, 1),
            ],
            "supporting_markers": {"T cell": ["CD3D"]},
        }
    }
    adata.uns["cluster_retrieval_evidence"] = {}
    summaries = svc._build_cluster_summaries(
        adata=adata,
        cluster_series=adata.obs["leiden"],
        cell_type_series=adata.obs["annotation_label"],
        confidence_bucket_series=adata.obs["annotation_confidence"],
    )
    s0 = next(s for s in summaries if s["cluster_id"] == "0")
    assert len(s0["runner_up_labels"]) == 1
    assert s0["runner_up_labels"][0]["cell_type"] == "ct_runner"
    assert s0["top_cell_types"][0]["cell_type"] == "ct_best"
    assert s0["annotation_support_markers"] == ["CD3D"]
    assert s0["annotation_support_source_label"] == "T cell"
    assert s0["annotation_support_aligned_with_primary_headline"] is True
    assert s0["annotation_support_partition_de_overlap"] is False


def test_cluster_summaries_support_markers_prefer_finest_headline_segment():
    """``supporting_markers`` keys often match L3; hierarchy headline is L1|L2|L3."""
    svc = RunExplorerService.__new__(RunExplorerService)
    adata = ad.AnnData(X=np.ones((2, 2), dtype=np.float32))
    adata.obs["leiden"] = ["0", "0"]
    adata.obs["annotation_label"] = ["CD8 T", "CD8 T"]
    adata.obs["auto_level1"] = ["Immune", "Immune"]
    adata.obs["auto_level2"] = ["T cells", "T cells"]
    adata.obs["auto_level3"] = ["CD8", "CD8"]
    adata.obs["annotation_confidence"] = ["high", "high"]
    adata.uns["zerna_cluster_annotations"] = {
        "0": {
            "normalized_label": "CD8 cytotoxic T",
            "supporting_markers": {
                "CD8": ["GZMB"],
                "CD8 cytotoxic T": ["PRF1", "PRF2"],
            },
            "top_cell_types": [],
        }
    }
    adata.uns["cluster_markers"] = {"0": ["G1"]}
    summaries = svc._build_cluster_summaries(
        adata=adata,
        cluster_series=adata.obs["leiden"],
        cell_type_series=adata.obs["annotation_label"],
        confidence_bucket_series=adata.obs["annotation_confidence"],
        lineage_series=adata.obs["auto_level1"],
        level2_series=adata.obs["auto_level2"],
        level3_series=adata.obs["auto_level3"],
    )
    s0 = next(s for s in summaries if s["cluster_id"] == "0")
    assert s0["annotation_support_source_label"] == "CD8"
    assert s0["annotation_support_markers"] == ["GZMB"]
    assert s0["annotation_support_aligned_with_primary_headline"] is True


def test_cluster_summaries_raw_annotation_label_mode_when_differs_from_structural_headline():
    """Raw ``annotation_label`` cluster mode is exposed for debug when it disagrees with structural L1|L2|L3."""
    svc = RunExplorerService.__new__(RunExplorerService)
    adata = ad.AnnData(X=np.ones((2, 2), dtype=np.float32))
    adata.obs["leiden"] = ["0", "0"]
    adata.obs["annotation_label"] = [
        "Natural killer T (NKT) cell",
        "Natural killer T (NKT) cell",
    ]
    adata.obs["auto_level1"] = ["Immune", "Immune"]
    adata.obs["auto_level2"] = ["T cells", "T cells"]
    adata.obs["auto_level3"] = ["CD8", "CD8"]
    adata.obs["final_display"] = ["Immune | T cells | CD8", "Immune | T cells | CD8"]
    adata.obs["annotation_confidence"] = ["high", "high"]
    adata.uns["zerna_cluster_annotations"] = {}
    adata.uns["cluster_markers"] = {}
    adata.uns["cluster_retrieval_evidence"] = {}
    summaries = svc._build_cluster_summaries(
        adata=adata,
        cluster_series=adata.obs["leiden"],
        cell_type_series=adata.obs["final_display"],
        confidence_bucket_series=adata.obs["annotation_confidence"],
        lineage_series=adata.obs["auto_level1"],
        level2_series=adata.obs["auto_level2"],
        level3_series=adata.obs["auto_level3"],
    )
    s0 = next(s for s in summaries if s["cluster_id"] == "0")
    assert s0["label"] == "Immune | T cells | CD8"
    assert s0["raw_annotation_label_mode"] == "Natural killer T (NKT) cell"


def test_cluster_summaries_no_misleading_support_marker_fallback():
    svc = RunExplorerService.__new__(RunExplorerService)
    adata = ad.AnnData(X=np.ones((2, 2), dtype=np.float32))
    adata.obs["leiden"] = ["0", "0"]
    adata.obs["annotation_label"] = ["x", "x"]
    adata.obs["auto_level1"] = ["Immune", "Immune"]
    adata.obs["auto_level2"] = ["T cells", "T cells"]
    adata.obs["auto_level3"] = ["CD8", "CD8"]
    adata.obs["annotation_confidence"] = ["high", "high"]
    adata.uns["zerna_cluster_annotations"] = {
        "0": {
            "normalized_label": "orphan",
            "supporting_markers": {"Unrelated_type": ["X1", "X2"]},
            "top_cell_types": [],
        }
    }
    adata.uns["cluster_markers"] = {"0": ["G1"]}
    summaries = svc._build_cluster_summaries(
        adata=adata,
        cluster_series=adata.obs["leiden"],
        cell_type_series=adata.obs["annotation_label"],
        confidence_bucket_series=adata.obs["annotation_confidence"],
        lineage_series=adata.obs["auto_level1"],
        level2_series=adata.obs["auto_level2"],
        level3_series=adata.obs["auto_level3"],
    )
    s0 = next(s for s in summaries if s["cluster_id"] == "0")
    assert s0["annotation_support_markers"] == []
    assert s0["annotation_support_source_label"] is None


def test_resolve_explorer_source_column_matches_cell_type_priority():
    cols = ["annotation_label", "final_display", "leiden"]
    assert resolve_explorer_source_column(cols, "cellType") == "final_display"
    cols_legacy = ["annotation_label", "leiden"]
    assert resolve_explorer_source_column(cols_legacy, "cellType") == "annotation_label"
    cols_display = ["zr_display", "final_display", "leiden"]
    assert resolve_explorer_source_column(cols_display, "displayLabel") == "final_display"
    cols_level3 = ["zr_level3", "level3_final_safe", "leiden"]
    assert resolve_explorer_source_column(cols_level3, "level3") == "level3_final_safe"
    cols_level3_zr_only = ["zr_level3", "leiden"]
    assert resolve_explorer_source_column(cols_level3_zr_only, "level3") is None


@pytest.mark.asyncio
async def test_run_explorer_modern_artifact_level3_structural_auto_then_final_safe(
    async_engine, tmp_path: Path
):
    """Stale auto_level3 is ignored when empty after normalization; L3 comes from level3_final_safe."""
    source = tmp_path / "explorer_stale_l3.h5ad"
    _write_explorer_h5ad_with_stale_auto_level3(source)

    session = await get_clean_session(async_engine)
    org, run = await _make_run_with_artifact(session, "runs/test/stale_l3.h5ad")

    svc = RunExplorerService(session, s3_service=DummyS3Service(source))
    payload = await svc.get_run_explorer(run.id, org.id, max_cells=10)

    assert payload["metadata"][0]["level3"] == "myCAF"
    assert payload["metadata"][1]["level3"] == "CD8"
    assert payload["metadata"][0]["displayLabel"] == "Stromal | Fibroblasts | myCAF"
    assert payload["metadata"][1]["displayLabel"] == "Immune | T cells | CD8"
    await session.close()


def _write_explorer_h5ad_modern_raw_zerna_not_used_for_level3(path: Path) -> None:
    """Modern auto_* columns: empty structural L3; rich annotation_label must not populate explorer level3."""
    adata = ad.AnnData(X=np.ones((1, 2), dtype=np.float32))
    adata.obs_names = ["c0"]
    adata.obs["leiden"] = ["0"]
    adata.obs["auto_level1"] = ["Immune"]
    adata.obs["auto_level2"] = ["T cells"]
    adata.obs["auto_level3"] = [""]
    adata.obs["level3_final_safe"] = [""]
    adata.obs["final_display"] = ["Immune | T cells"]
    adata.obs["annotation_label"] = ["Natural killer T (NKT) cell"]
    adata.obs["zr_level3"] = ["Natural killer T (NKT) cell"]
    adata.obs["annotation_confidence"] = ["high"]
    adata.obsm["X_umap"] = np.array([[0.0, 0.1]], dtype=np.float32)
    adata.write_h5ad(path)


@pytest.mark.asyncio
async def test_run_explorer_modern_does_not_fill_level3_from_zerna_or_zr(
    async_engine, tmp_path: Path
):
    source = tmp_path / "explorer_modern_nkt.h5ad"
    _write_explorer_h5ad_modern_raw_zerna_not_used_for_level3(source)

    session = await get_clean_session(async_engine)
    org, run = await _make_run_with_artifact(session, "runs/test/modern_nkt.h5ad")

    svc = RunExplorerService(session, s3_service=DummyS3Service(source))
    payload = await svc.get_run_explorer(run.id, org.id, max_cells=10)

    assert "level3" not in payload["metadata"][0]
    assert payload["metadata"][0]["displayLabel"] == "Immune | T cells"
    assert payload["metadata"][0]["rawAnnotationLabel"] == "Natural killer T (NKT) cell"
    await session.close()


@pytest.mark.asyncio
async def test_run_explorer_service_builds_payload(async_engine, tmp_path: Path):
    source = tmp_path / "explorer.h5ad"
    _write_explorer_h5ad(source)

    session = await get_clean_session(async_engine)
    org, run = await _make_run_with_artifact(session, "runs/test/processed.h5ad")

    svc = RunExplorerService(
        session,
        s3_service=DummyS3Service(source),
    )
    payload = await svc.get_run_explorer(run.id, org.id, max_cells=3)

    assert payload["run_id"] == str(run.id)
    assert payload["embedding_key"] == "X_umap"
    assert payload["explorer_view"] == "global"
    assert payload["overview"]["n_cells"] == 4
    assert payload["overview"]["artifact_total_cells"] == 4
    assert payload["overview"]["n_clusters"] == 2
    assert payload["sampled"] is True
    assert any(v["id"] == "global" for v in payload["available_views"])
    assert payload["available_fields"][:3] == ["cluster", "cellType", "lineage"]
    # Lineage is a primary filter key when it has >1 value; this fixture is single-value Lymphoid.
    assert {"sample", "condition", "confidenceBucket"}.issubset(set(payload["filter_fields"]))
    assert "cluster" in payload["advanced_filter_fields"]
    assert "cellType" in payload["advanced_filter_fields"]
    assert len(payload["embedding"]["cells"]) == 3
    assert payload["cluster_summaries"][0]["label"] in {"T cell", "B cell"}
    assert payload["cluster_summaries"][0]["top_markers"]
    assert payload["cluster_summaries"][0]["evidence_count"] >= 1
    assert payload["cluster_summaries"][0]["evidence_hits"]
    first = next(c for c in payload["cluster_summaries"] if c["cluster_id"] == "0")
    assert first["annotation_support_markers"] == ["CD3D", "TRBC1"]
    assert first["annotation_support_source_label"] == "T cell"
    assert first["annotation_support_aligned_with_primary_headline"] is True
    assert first["annotation_support_partition_de_overlap"] is False
    assert len(first["runner_up_labels"]) == 1
    assert first["runner_up_labels"][0]["cell_type"] == "NK cell"
    await session.close()


@pytest.mark.asyncio
async def test_run_explorer_service_loads_gene_overlay(async_engine, tmp_path: Path):
    source = tmp_path / "explorer.h5ad"
    _write_explorer_h5ad(source)

    session = await get_clean_session(async_engine)
    org, run = await _make_run_with_artifact(session, "runs/test/processed.h5ad")

    svc = RunExplorerService(
        session,
        s3_service=DummyS3Service(source),
    )
    payload = await svc.get_gene_overlay(run.id, org.id, gene="cd3d", max_cells=4)

    assert payload["run_id"] == str(run.id)
    assert payload["gene"] == "CD3D"
    assert payload["sampled"] is False
    assert payload["total_cells"] == 4
    assert payload["values"]["cell_0"] == pytest.approx(1.0)
    assert payload["max"] >= payload["min"]
    await session.close()


@pytest.mark.asyncio
async def test_run_explorer_service_reuses_cached_download(
    async_engine,
    tmp_path: Path,
    monkeypatch,
):
    source = tmp_path / "explorer.h5ad"
    cache_dir = tmp_path / "cache"
    _write_explorer_h5ad(source)
    monkeypatch.setenv("ZERNA_EXPLORER_CACHE_DIR", str(cache_dir))

    session = await get_clean_session(async_engine)
    org, run = await _make_run_with_artifact(session, "runs/test/processed.h5ad")

    svc = RunExplorerService(
        session,
        s3_service=DummyS3Service(source),
    )
    await svc.get_run_explorer(run.id, org.id, max_cells=3)
    await svc.get_gene_overlay(run.id, org.id, gene="CD3D", max_cells=3)

    assert svc.s3_service.s3_client.download_count == 1
    await session.close()


@pytest.mark.asyncio
async def test_run_explorer_lineage_immune_uses_p2_embedding_and_subclusters(
    async_engine, tmp_path: Path
):
    source = tmp_path / "explorer_p2.h5ad"
    _write_explorer_h5ad_with_p2_lineage(source)
    session = await get_clean_session(async_engine)
    org, run = await _make_run_with_artifact(session, "runs/test/p2.h5ad")
    svc = RunExplorerService(session, s3_service=DummyS3Service(source))

    payload = await svc.get_run_explorer(run.id, org.id, max_cells=50, explorer_view="immune")

    assert payload["explorer_view"] == "immune"
    assert payload["embedding_key"] == "X_umap_lineage_immune"
    assert payload["lineage_embedding_fallback"] is False
    assert payload["total_cells"] == 4
    assert len(payload["embedding"]["cells"]) == 4
    assert payload["overview"]["artifact_total_cells"] == 6
    assert payload["metadata"][0]["cluster"] in {"Immune:0", "Immune:1"}
    assert "globalCluster" in payload["metadata"][0]
    imm_opt = next(v for v in payload["available_views"] if v["id"] == "immune")
    assert imm_opt["n_cells"] == 4
    assert imm_opt["embedding_ready"] is True
    imm0 = next(c for c in payload["cluster_summaries"] if c["cluster_id"] == "Immune:0")
    assert imm0["top_markers"][:2] == ["LINEAGE_CD4_A", "LINEAGE_CD4_B"]
    assert imm0["annotation_support_markers"][:2] == ["LINEAGE_CD4_A", "CD4"]
    assert imm0["annotation_support_source_label"] == "CD4 T"
    assert imm0["annotation_support_partition_de_overlap"] is True
    assert imm0["evidence_hits"] and imm0["evidence_hits"][0]["label"] == "CD4 T"
    imm1 = next(c for c in payload["cluster_summaries"] if c["cluster_id"] == "Immune:1")
    assert imm1["top_markers"][:2] == ["LINEAGE_CD8_A", "LINEAGE_CD8_B"]
    assert imm1["runner_up_labels"] == []
    await session.close()


@pytest.mark.asyncio
async def test_run_explorer_lineage_epithelial_uses_p2_embedding_and_subclusters(
    async_engine, tmp_path: Path
):
    source = tmp_path / "explorer_p2_epi.h5ad"
    _write_explorer_h5ad_with_p2_lineage_epithelial(source)
    session = await get_clean_session(async_engine)
    org, run = await _make_run_with_artifact(session, "runs/test/p2_epi.h5ad")
    svc = RunExplorerService(session, s3_service=DummyS3Service(source))

    payload = await svc.get_run_explorer(run.id, org.id, max_cells=50, explorer_view="epithelial")

    assert payload["explorer_view"] == "epithelial"
    assert payload["embedding_key"] == "X_umap_lineage_epithelial"
    assert payload["lineage_embedding_fallback"] is False
    assert payload["total_cells"] == 4
    assert payload["overview"]["artifact_total_cells"] == 5
    assert all("Epithelial:" in str(m["cluster"]) for m in payload["metadata"])
    epi_opt = next(v for v in payload["available_views"] if v["id"] == "epithelial")
    assert epi_opt["n_cells"] == 4
    assert epi_opt["embedding_ready"] is True
    e0 = next(c for c in payload["cluster_summaries"] if c["cluster_id"] == "Epithelial:0")
    assert e0["top_markers"][:2] == ["EPI_L0_A", "EPI_L0_B"]
    assert e0["annotation_support_markers"][:2] == ["EPI_L0_A", "KRT8"]
    assert e0["annotation_support_source_label"] == "Luminal epithelial"
    assert e0["annotation_support_partition_de_overlap"] is True
    e1 = next(c for c in payload["cluster_summaries"] if c["cluster_id"] == "Epithelial:1")
    assert e1["top_markers"][0] == "EPI_L1_A"
    await session.close()


@pytest.mark.asyncio
async def test_run_explorer_lineage_falls_back_to_global_coords_when_p2_missing(
    async_engine, tmp_path: Path
):
    source = tmp_path / "explorer_p2fb.h5ad"
    _write_explorer_h5ad_with_p2_lineage(source)
    adata = ad.read_h5ad(source)
    del adata.obsm["X_umap_lineage_immune"]
    adata.write_h5ad(source)

    session = await get_clean_session(async_engine)
    org, run = await _make_run_with_artifact(session, "runs/test/p2fb.h5ad")
    svc = RunExplorerService(session, s3_service=DummyS3Service(source))
    payload = await svc.get_run_explorer(run.id, org.id, max_cells=50, explorer_view="immune")

    assert payload["embedding_key"] == "X_umap"
    assert payload["lineage_embedding_fallback"] is True
    assert payload["total_cells"] == 4
    await session.close()


@pytest.mark.asyncio
async def test_run_explorer_fine_t_cells_uses_p3_embedding_and_subclusters(
    async_engine, tmp_path: Path
):
    source = tmp_path / "explorer_p3.h5ad"
    _write_explorer_h5ad_with_p3_fine_t_cells(source)
    session = await get_clean_session(async_engine)
    org, run = await _make_run_with_artifact(session, "runs/test/p3.h5ad")
    svc = RunExplorerService(session, s3_service=DummyS3Service(source))

    payload = await svc.get_run_explorer(run.id, org.id, max_cells=50, explorer_view="fine_t_cells")

    assert payload["explorer_view"] == "fine_t_cells"
    assert payload["embedding_key"] == "X_umap_fine_t_cells"
    assert payload["lineage_embedding_fallback"] is False
    assert payload["total_cells"] == 5
    assert len(payload["embedding"]["cells"]) == 5
    assert payload["metadata"][0]["cluster"] in {"T_cells:0", "T_cells:1"}
    fine_opt = next(v for v in payload["available_views"] if v["id"] == "fine_t_cells")
    assert fine_opt["n_cells"] == 5
    assert fine_opt["embedding_ready"] is True
    # In fine views ``cluster`` maps to ``fine_subcluster``; that column is deduped from ``fineSubcluster``.
    assert payload["metadata"][0]["cluster"].startswith("T_cells:")
    t0 = next(c for c in payload["cluster_summaries"] if c["cluster_id"] == "T_cells:0")
    assert t0["top_markers"][:2] == ["FINE_NAIVE_A", "FINE_NAIVE_B"]
    assert t0["annotation_support_markers"][:2] == ["FINE_NAIVE_A", "CCR7"]
    assert t0["annotation_support_source_label"] == "CD4 T naive"
    assert t0["annotation_support_partition_de_overlap"] is True
    assert t0["evidence_hits"] and t0["evidence_hits"][0]["label"] == "CD4 T naive"
    t1 = next(c for c in payload["cluster_summaries"] if c["cluster_id"] == "T_cells:1")
    assert t1["top_markers"][0] == "FINE_EM_A"
    await session.close()
