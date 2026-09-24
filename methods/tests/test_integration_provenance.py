"""Tests for batch integration provenance helpers."""

import numpy as np
import pytest
from anndata import AnnData

from methods.pipeline.integration_provenance import (
    finalize_zerna_integration_provenance,
    resolve_integration_engine,
)


def test_resolve_integration_engine_prefers_integration_mode():
    assert resolve_integration_engine({"integration_mode": "scvi"}) == "scvi"
    assert resolve_integration_engine({"integration_mode": "harmony"}) == "harmony"
    assert resolve_integration_engine({"batch_method": "scvi"}) == "scvi"
    assert resolve_integration_engine({"method": "harmony"}) == "harmony"
    assert resolve_integration_engine({}) == "harmony"


def test_finalize_harmony_execution_provenance():
    adata = AnnData(np.zeros((12, 20)))
    adata.obsm["X_pca_harmony"] = np.zeros((12, 8), dtype=np.float32)
    adata.uns["zerna_active_representation"] = "X_pca_harmony"
    finalize_zerna_integration_provenance(
        adata,
        executed_engine="harmony",
        parameters={"batch_key": "sample", "n_pcs": 50, "max_iter_harmony": 10},
        metrics={"batch_key": "sample", "n_batches": 3, "compute_backend": "cpu"},
        step_name="batch_correction_harmony",
    )
    u = adata.uns["zerna_integration"]
    assert u["method_requested"] == "harmony"
    assert u["method_executed"] == "harmony"
    assert u["fallback_applied"] is False
    assert u["fallback_reason"] is None
    assert u["batch_key_requested"] == "sample"
    assert u["batch_key_resolved"] == "sample"
    assert u["representation_input"] == "X_pca"
    assert u["representation_output"] == "X_pca_harmony"
    assert u["representation_obsm"] == "X_pca_harmony"
    assert u["x_preserved"] is True
    assert u["n_components"] == 8
    assert u["max_iter_harmony"] == 10
    assert u["downstream_use_obsm"] == "X_pca_harmony"
    assert u["clustering_and_embedding_should_use_obsm"] == "X_pca_harmony"


def test_finalize_scvi_execution_provenance():
    adata = AnnData(np.zeros((12, 20)))
    adata.obsm["X_scVI"] = np.zeros((12, 15), dtype=np.float32)
    adata.uns["zerna_active_representation"] = "X_scVI"
    finalize_zerna_integration_provenance(
        adata,
        executed_engine="scvi",
        parameters={
            "batch_key": "donor",
            "n_latent": 15,
            "n_layers": 2,
            "integration_mode": "scvi",
        },
        metrics={
            "batch_key": "donor",
            "n_batches": 2,
            "compute_backend": "cpu",
            "scvi_max_epochs_effective": 12,
        },
        step_name="batch_correction_scvi",
    )
    u = adata.uns["zerna_integration"]
    assert u["method_requested"] == "scvi"
    assert u["method_executed"] == "scvi"
    assert u["representation_output"] == "X_scVI"
    assert u["max_epochs_effective"] == 12
    assert u["n_latent"] == 15
    assert u["n_layers"] == 2


@pytest.mark.parametrize(
    "params,metrics,expect_fb",
    [
        (
            {"integration_mode": "scvi"},
            {"batch_key": "b", "n_batches": 2, "compute_backend": "cpu"},
            True,
        ),
        (
            {"batch_method": "scvi"},
            {"batch_key": "b", "n_batches": 2, "compute_backend": "cpu"},
            True,
        ),
        (
            {"integration_mode": "harmony"},
            {"batch_key": "b", "n_batches": 2, "compute_backend": "cpu"},
            False,
        ),
    ],
)
def test_finalize_scvi_requested_harmony_executed_fallback(params, metrics, expect_fb):
    adata = AnnData(np.zeros((10, 10)))
    adata.obsm["X_pca_harmony"] = np.zeros((10, 5), dtype=np.float32)
    adata.uns["zerna_active_representation"] = "X_pca_harmony"
    finalize_zerna_integration_provenance(
        adata,
        executed_engine="harmony",
        parameters=dict(params, batch_key="b"),
        metrics=metrics,
        step_name="batch_correction_harmony",
    )
    u = adata.uns["zerna_integration"]
    assert u["method_requested"] == ("scvi" if expect_fb else "harmony")
    assert u["method_executed"] == "harmony"
    assert u["fallback_applied"] is expect_fb
    if expect_fb:
        assert "unavailable" in (u.get("fallback_reason") or "")


def test_finalize_module_import_fallback_provenance():
    adata = AnnData(np.zeros((10, 10)))
    adata.obsm["X_pca_harmony"] = np.zeros((10, 4), dtype=np.float32)
    adata.uns["zerna_active_representation"] = "X_pca_harmony"
    metrics = {
        "batch_key": "batch",
        "n_batches": 2,
        "compute_backend": "cpu",
        "fallback_method": "harmony",
        "fallback_reason": "No module named 'scvi'",
    }
    finalize_zerna_integration_provenance(
        adata,
        executed_engine="harmony",
        parameters={"integration_mode": "scvi", "batch_key": "batch"},
        metrics=metrics,
        step_name="batch_correction_scvi",
    )
    u = adata.uns["zerna_integration"]
    assert u["method_requested"] == "scvi"
    assert u["method_executed"] == "harmony"
    assert u["fallback_applied"] is True
    assert u["fallback_reason"] == "No module named 'scvi'"
