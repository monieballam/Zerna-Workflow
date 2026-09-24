"""
Deployment smoke: explorer + annotation contract on one modern and one legacy H5AD.

Run locally or in CI::

    ./scripts/explorer_deployment_smoke.sh

Or::

    PYTHONPATH=. uv run --project apps/api pytest \\
      apps/api/tests/test_explorer_deployment_smoke.py -o addopts= -m deployment_smoke
"""

from __future__ import annotations

from pathlib import Path

import anndata as ad
import pytest
import pytest_asyncio

from apps.api.services.annotation_audit import (
    explorer_payload_audit_flags,
    load_canonical_vocabulary,
    modern_unresolved_cluster_label_parts,
)
from apps.api.services.run_explorer_service import (
    RunExplorerService,
    resolve_explorer_source_column,
)
from apps.api.tests.explorer_deployment_fixtures import (
    write_legacy_deployment_smoke_h5ad,
    write_modern_deployment_smoke_h5ad,
)
from apps.api.tests.test_run_explorer_service import (
    DummyS3Service,
    _make_run_with_artifact,
    _write_explorer_h5ad_with_p3_fine_t_cells,
    get_clean_session,
)

pytestmark = pytest.mark.deployment_smoke


@pytest_asyncio.fixture
async def clean_db(async_engine):
    session = await get_clean_session(async_engine)
    yield session
    await session.close()


@pytest.mark.asyncio
async def test_deployment_smoke_modern_artifact(clean_db, tmp_path: Path):
    """Modern: strict auto hierarchy, final_display vs rawAnnotationLabel, P2 lineage, globalCluster alias, unresolved L3."""
    source = tmp_path / "modern_smoke.h5ad"
    write_modern_deployment_smoke_h5ad(source)
    org, run = await _make_run_with_artifact(clean_db, "runs/test/modern_smoke.h5ad")
    svc = RunExplorerService(clean_db, s3_service=DummyS3Service(source))

    global_p = await svc.get_run_explorer(run.id, org.id, max_cells=50, explorer_view="global")
    assert global_p["explorer_view"] == "global"
    assert global_p["lineage_view_unavailable_reason"] is None
    assert "lineage" in global_p["available_fields"]
    assert "level2" in global_p["available_fields"]
    assert "level3" in global_p["available_fields"]
    assert "displayLabel" in global_p["available_fields"]
    assert "rawAnnotationLabel" in global_p["available_fields"]
    assert "Immune" in global_p["filter_values"]["lineage"]
    assert "Stromal" in global_p["filter_values"]["lineage"]
    axes = global_p["hierarchy_filter_axes"]
    assert axes.get("level2_by_lineage", {}).get("Immune")
    assert global_p["overview"]["top_cell_types"]

    # Representative cell: structural fields + display vs raw engine string
    meta0 = next(m for m in global_p["metadata"] if m.get("cellId") == "c0")
    assert meta0["lineage"] == "Immune"
    assert meta0["level2"] == "T cells"
    assert meta0["level3"] == "CD4"
    assert meta0["displayLabel"] == "Immune | T cells | CD4"
    assert meta0["cellType"] == "Immune | T cells | CD4"
    assert meta0["rawAnnotationLabel"] == "CD4 T"
    assert meta0["rawAnnotationLabel"] != meta0["displayLabel"]

    unresolved = next(
        (m for m in global_p["metadata"] if m.get("displayLabel") == "Immune | T cells"), None
    )
    assert unresolved is not None
    assert "level3" not in unresolved

    s2 = next(s for s in global_p["cluster_summaries"] if s["cluster_id"] == "2")
    assert s2["label"] == "Immune | T cells"
    assert modern_unresolved_cluster_label_parts(global_p, "2") == ["Immune", "T cells"]

    vocab = load_canonical_vocabulary()
    mflags = explorer_payload_audit_flags(global_p, vocab=vocab, has_auto_hierarchy=True)
    assert mflags["modern_segments_all_canonical"] is True
    assert mflags["has_zr_in_user_facing"] is False

    lineage_p = await svc.get_run_explorer(run.id, org.id, max_cells=50, explorer_view="immune")
    assert lineage_p["embedding_key"] == "X_umap_lineage_immune"
    assert lineage_p["lineage_embedding_fallback"] is False
    assert lineage_p["lineage_view_unavailable_reason"] is None
    imm = next(v for v in lineage_p["available_views"] if v["id"] == "immune")
    assert imm["embedding_ready"] is True
    assert imm["n_cells"] == 5
    assert all(m["cluster"].startswith("Immune:") for m in lineage_p["metadata"])
    assert all(m["globalCluster"] in {"0", "1", "2"} for m in lineage_p["metadata"])
    assert all(m["cluster"] != m["globalCluster"] for m in lineage_p["metadata"])

    ad_r = ad.read_h5ad(source, backed="r")
    obs_cols = list(ad_r.obs.columns)
    ad_r.file.close()
    assert resolve_explorer_source_column(obs_cols, "lineage") == "auto_level1"
    assert resolve_explorer_source_column(obs_cols, "level2") == "auto_level2"
    assert resolve_explorer_source_column(obs_cols, "level3") == "auto_level3"


@pytest.mark.asyncio
async def test_deployment_smoke_modern_fine_partition_surface(clean_db, tmp_path: Path):
    """Modern P3 fine view: embedding selector, partition cluster id vs global, inspector headline."""
    source = tmp_path / "modern_p3_smoke.h5ad"
    _write_explorer_h5ad_with_p3_fine_t_cells(source)
    org, run = await _make_run_with_artifact(clean_db, "runs/test/modern_p3_smoke.h5ad")
    svc = RunExplorerService(clean_db, s3_service=DummyS3Service(source))

    payload = await svc.get_run_explorer(run.id, org.id, max_cells=50, explorer_view="fine_t_cells")
    assert payload["explorer_view"] == "fine_t_cells"
    assert payload["embedding_key"] == "X_umap_fine_t_cells"
    assert payload["lineage_embedding_fallback"] is False
    opt = next(v for v in payload["available_views"] if v["id"] == "fine_t_cells")
    assert opt["embedding_ready"] is True
    assert opt["n_cells"] == 5
    assert payload["metadata"][0]["cluster"].startswith("T_cells:")
    assert payload["metadata"][0]["globalCluster"] in {"0", "1"}
    assert payload["metadata"][0]["cluster"] != payload["metadata"][0]["globalCluster"]
    t0 = next(s for s in payload["cluster_summaries"] if s["cluster_id"] == "T_cells:0")
    assert t0["label"] == "CD4"
    fflags = explorer_payload_audit_flags(
        payload, vocab=load_canonical_vocabulary(), has_auto_hierarchy=True
    )
    assert fflags["modern_segments_all_canonical"] is True
    assert fflags["has_zr_in_user_facing"] is False


@pytest.mark.asyncio
async def test_deployment_smoke_legacy_artifact(clean_db, tmp_path: Path):
    """Legacy: no auto_level*; lineage/level2 from fallbacks; looser L3; lineage views disabled."""
    source = tmp_path / "legacy_smoke.h5ad"
    write_legacy_deployment_smoke_h5ad(source)
    org, run = await _make_run_with_artifact(clean_db, "runs/test/legacy_smoke.h5ad")
    svc = RunExplorerService(clean_db, s3_service=DummyS3Service(source))

    payload = await svc.get_run_explorer(run.id, org.id, max_cells=50, explorer_view="global")
    assert payload["explorer_view"] == "global"
    assert "lineage" in payload["available_fields"]
    assert "level2" in payload["available_fields"]
    assert "level3" in payload["available_fields"]
    assert "displayLabel" in payload["available_fields"]
    assert "rawAnnotationLabel" in payload["available_fields"]

    meta0 = next(m for m in payload["metadata"] if m.get("cellId") == "cell_0")
    assert meta0["lineage"] == "Immune"
    assert meta0["level2"] == "T cells"
    assert meta0["level3"] == "CD8"
    assert meta0["displayLabel"] == "Immune | T cells | CD8"
    assert meta0["cellType"] == "Immune | T cells | CD8"
    assert meta0["rawAnnotationLabel"] == "T cell"
    assert meta0["rawAnnotationLabel"] != meta0["cellType"]

    imm = next(v for v in payload["available_views"] if v["id"] == "immune")
    assert imm["embedding_ready"] is False
    assert imm["n_cells"] == 0

    lineage_p = await svc.get_run_explorer(run.id, org.id, max_cells=50, explorer_view="immune")
    assert lineage_p["lineage_embedding_fallback"] is True
    assert lineage_p["embedding_key"] == "X_umap"
    assert lineage_p["lineage_view_unavailable_reason"] is not None
    assert "auto_level1" in lineage_p["lineage_view_unavailable_reason"]

    adata = ad.read_h5ad(source, backed="r")
    obs_cols = list(adata.obs.columns)
    adata.file.close()
    assert "auto_level1" not in obs_cols
    assert resolve_explorer_source_column(obs_cols, "lineage") == "annotation_lineage"
    assert resolve_explorer_source_column(obs_cols, "level2") == "zr_level2"
    assert resolve_explorer_source_column(obs_cols, "cellType") == "final_display"
    assert resolve_explorer_source_column(obs_cols, "displayLabel") == "final_display"

    assert payload["hierarchy_filter_axes"] == {}
    s0 = next(s for s in payload["cluster_summaries"] if s["cluster_id"] == "0")
    assert s0["label"] == "Immune | T cells | CD8"
    assert payload["overview"]["top_cell_types"]

    lflags = explorer_payload_audit_flags(
        payload, vocab=load_canonical_vocabulary(), has_auto_hierarchy=False
    )
    assert lflags["legacy_mapped_display_canonical"] is True
    assert lflags["has_zr_in_user_facing"] is False
