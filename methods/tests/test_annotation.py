"""Unit and property-based tests for annotation and analysis methods.

Property 36: Differential Expression Completeness
  - Validates: Requirements 24.1, 24.2
  - For any AnnData with ≥2 clusters, DE results must contain an entry for
    every (cluster, gene) pair, with valid logfoldchange, pval, and pval_adj.

Property 37: Pathway Score Storage in H5AD
  - Validates: Requirements 25.3, 25.4
  - For any AnnData and pathway network, pathway scores must be stored in
    adata.obsm under the specified key with shape (n_cells, n_pathways).
"""

from __future__ import annotations

import json

import anndata as ad
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def make_adata(n_cells=80, n_genes=300, seed=42, sparse=True, n_clusters=3):
    """Create synthetic AnnData with cluster labels and log-normalised counts."""
    import scanpy as sc

    rng = np.random.default_rng(seed)
    X = rng.negative_binomial(5, 0.5, size=(n_cells, n_genes)).astype(np.float32)
    if sparse:
        X = sp.csr_matrix(X)
    adata = ad.AnnData(X=X)
    adata.obs_names = [f"cell_{i}" for i in range(n_cells)]
    adata.var_names = [f"gene_{i}" for i in range(n_genes)]

    # Assign cluster labels
    labels = [str(i % n_clusters) for i in range(n_cells)]
    adata.obs["leiden"] = labels

    # Log-normalise
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    return adata


def make_pathway_net(n_pathways=5, n_genes_per_pathway=10, gene_names=None):
    """Create a minimal pathway network DataFrame for decoupler."""
    rows = []
    for p in range(n_pathways):
        genes = (
            gene_names[p * n_genes_per_pathway : (p + 1) * n_genes_per_pathway]
            if gene_names
            else [f"gene_{p * n_genes_per_pathway + g}" for g in range(n_genes_per_pathway)]
        )
        for gene in genes:
            rows.append({"source": f"pathway_{p}", "target": gene, "weight": 1.0})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 11.1 CellTypist annotation tests
# ---------------------------------------------------------------------------


class TestCellTypistMethod:
    """Unit tests for CellTypistMethod.

    Note: These tests mock CellTypist to avoid requiring model downloads in CI.
    """

    @staticmethod
    def _set_mock_annotate(monkeypatch, mock_pred):
        from methods.annotation import cell_type_annotation as annotation_module

        def mock_predict(*_args, **_kwargs):
            return mock_pred

        monkeypatch.setattr(
            annotation_module,
            "_resolve_celltypist_model",
            lambda _model_name: object(),
        )
        monkeypatch.setattr(
            annotation_module,
            "_predict_celltypist_in_chunks",
            mock_predict,
        )

    def _make_mock_predictions(self, adata, _model_name, labels=None):
        """Return a mock CellTypist predictions object."""
        import unittest.mock as mock

        n_cells = adata.n_obs
        if labels is None:
            cell_types = np.array([f"CellType_{i % 3}" for i in range(n_cells)])
        else:
            cell_types = np.asarray(labels, dtype=object)
        unique_labels = sorted({str(label) for label in cell_types})
        prob_matrix = pd.DataFrame(
            np.random.default_rng(0).random((n_cells, len(unique_labels))),
            index=adata.obs_names,
            columns=unique_labels,
        )
        # Normalise rows to sum to 1
        prob_matrix = prob_matrix.div(prob_matrix.sum(axis=1), axis=0)

        predicted_labels = pd.DataFrame(
            {"predicted_labels": cell_types},
            index=adata.obs_names,
        )

        mock_pred = mock.MagicMock()
        mock_pred.predicted_labels = predicted_labels
        mock_pred.probability_matrix = prob_matrix
        mock_pred.majority_voting = None
        return mock_pred

    def test_celltypist_input_default_annotation_engine_is_celltypist(self):
        from methods.annotation.cell_type_annotation import (
            CellTypistInput,
            _resolve_annotation_method,
        )

        adata = make_adata(n_cells=10, n_genes=50, n_clusters=2)
        inp = CellTypistInput(adata=adata)
        assert inp.annotation_method == "celltypist"
        assert _resolve_annotation_method(None) == "celltypist"
        assert _resolve_annotation_method("annotation_agent_v3") == "celltypist"

    def test_annotations_stored_in_obs(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = make_adata(n_cells=60, n_genes=200, n_clusters=3)
        method = CellTypistMethod()
        mock_pred = self._make_mock_predictions(adata, "Immune_All_Low.pkl")

        self._set_mock_annotate(monkeypatch, mock_pred)

        result = method.execute(
            CellTypistInput(adata=adata, annotation_method="hybrid", majority_voting=False),
            compute=None,
        )
        assert "celltypist_cell_type" in result.adata.obs.columns
        assert "celltypist_conf_score" in result.adata.obs.columns
        assert "celltypist_provenance" in result.adata.obs.columns
        assert len(result.adata.obs["celltypist_cell_type"]) == 60

    def test_confidence_scores_in_range(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = make_adata(n_cells=60, n_genes=200, n_clusters=3)
        method = CellTypistMethod()
        mock_pred = self._make_mock_predictions(adata, "Immune_All_Low.pkl")

        self._set_mock_annotate(monkeypatch, mock_pred)

        result = method.execute(
            CellTypistInput(adata=adata, annotation_method="hybrid", majority_voting=False),
            compute=None,
        )
        scores = result.adata.obs["celltypist_conf_score"].values
        assert (scores >= 0.0).all() and (scores <= 1.0).all()

    def test_prob_matrix_stored_in_obsm(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = make_adata(n_cells=60, n_genes=200, n_clusters=3)
        method = CellTypistMethod()
        mock_pred = self._make_mock_predictions(adata, "Immune_All_Low.pkl")

        self._set_mock_annotate(monkeypatch, mock_pred)

        result = method.execute(
            CellTypistInput(adata=adata, annotation_method="hybrid", majority_voting=False),
            compute=None,
        )
        assert "celltypist_prob_matrix" in result.adata.obsm
        assert result.adata.obsm["celltypist_prob_matrix"].shape[0] == 60

    def test_min_prob_threshold_marks_unknown(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = make_adata(n_cells=60, n_genes=200, n_clusters=3)
        method = CellTypistMethod()
        mock_pred = self._make_mock_predictions(adata, "Immune_All_Low.pkl")

        self._set_mock_annotate(monkeypatch, mock_pred)

        # Very high threshold → most cells should be "Unknown"
        result = method.execute(
            CellTypistInput(
                adata=adata,
                annotation_method="hybrid",
                majority_voting=False,
                min_prob=0.99,
            ),
            compute=None,
        )
        cell_types = result.adata.obs["celltypist_cell_type"].values
        assert "Unknown" in cell_types

    def test_provenance_contains_model_name(self, monkeypatch):
        import json

        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = make_adata(n_cells=40, n_genes=200, n_clusters=2)
        method = CellTypistMethod()
        mock_pred = self._make_mock_predictions(adata, "Immune_All_Low.pkl")

        self._set_mock_annotate(monkeypatch, mock_pred)

        result = method.execute(
            CellTypistInput(
                adata=adata,
                annotation_method="hybrid",
                majority_voting=False,
                model_name="Immune_All_Low.pkl",
                knowledge_pack_version="v1.2.3",
            ),
            compute=None,
        )
        prov = json.loads(result.adata.obs["celltypist_provenance"].iloc[0])
        assert prov["model"] == "Immune_All_Low.pkl"
        assert prov["knowledge_pack_version"] == "v1.2.3"

    def test_metrics_populated(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = make_adata(n_cells=60, n_genes=200, n_clusters=3)
        method = CellTypistMethod()
        mock_pred = self._make_mock_predictions(adata, "Immune_All_Low.pkl")

        self._set_mock_annotate(monkeypatch, mock_pred)

        result = method.execute(
            CellTypistInput(adata=adata, annotation_method="hybrid", majority_voting=False),
            compute=None,
        )
        assert result.metrics.n_cells_annotated == 60
        assert result.metrics.n_cell_types_predicted >= 1
        assert 0.0 <= result.metrics.mean_confidence <= 1.0

    def test_hierarchical_annotation_columns_are_populated(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = make_adata(n_cells=3, n_genes=50, n_clusters=1)
        adata.obs_names = ["cell_0", "cell_1", "cell_2"]
        labels = ["T lymphocyte", "Monocyte", "Fibroblast"]
        method = CellTypistMethod()
        mock_pred = self._make_mock_predictions(adata, "Immune_All_Low.pkl", labels=labels)

        self._set_mock_annotate(monkeypatch, mock_pred)

        result = method.execute(
            CellTypistInput(adata=adata, annotation_method="hybrid", majority_voting=False),
            compute=None,
        )

        assert list(result.adata.obs["annotation_cell_type"]) == [
            "T cell",
            "Monocyte",
            "Fibroblast",
        ]
        assert list(result.adata.obs["annotation_lineage"]) == ["Lymphoid", "Myeloid", "Stromal"]
        assert "annotation_ontology_id" in result.adata.obs.columns
        assert "annotation_hierarchy_path" in result.adata.obs.columns

    def test_resolve_celltypist_model_downloads_only_requested_model(self, monkeypatch, tmp_path):
        import celltypist.models as celltypist_models

        from methods.annotation.cell_type_annotation import _resolve_celltypist_model

        model_dir = tmp_path / "models"
        model_dir.mkdir()
        target_model = model_dir / "Immune_All_Low.pkl"
        target_model.write_bytes(b"mock")
        download_calls: list[str] = []

        monkeypatch.setattr(
            celltypist_models,
            "get_model_path",
            lambda name: str(model_dir / name),
        )
        monkeypatch.setattr(
            celltypist_models,
            "download_models",
            lambda *, model=None, force_update=False: download_calls.append(str(model)),
        )

        loaded_models: list[str] = []

        class _DummyModel:
            pass

        monkeypatch.setattr(
            celltypist_models.Model,
            "load",
            staticmethod(lambda name=None: loaded_models.append(str(name)) or _DummyModel()),
        )

        model = _resolve_celltypist_model("Immune_All_Low.pkl")

        assert isinstance(model, _DummyModel)
        assert download_calls == []
        assert loaded_models == [str(target_model)]

    def test_resolve_bundled_taxonomy_marker_database_path(self):
        from methods.annotation.cell_type_annotation import _resolve_marker_database_path

        resolved = _resolve_marker_database_path("legacy_zerna_taxonomy")

        assert resolved is not None
        assert resolved.endswith("zerna_hierarchical_taxonomy.yaml")

    def test_legacy_canonical_columns_are_populated(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = make_adata(n_cells=3, n_genes=50, n_clusters=1)
        adata.obs_names = ["cell_0", "cell_1", "cell_2"]
        labels = ["CD8 T cell", "Monocyte", "Fibroblast"]
        method = CellTypistMethod()
        mock_pred = self._make_mock_predictions(adata, "Immune_All_Low.pkl", labels=labels)

        self._set_mock_annotate(monkeypatch, mock_pred)

        result = method.execute(
            CellTypistInput(adata=adata, annotation_method="hybrid", majority_voting=False),
            compute=None,
        )

        assert list(result.adata.obs["zr_level1"]) == ["Immune", "Immune", "Stromal"]
        assert list(result.adata.obs["celltype_level3"]) == [
            "CD8-positive T cell",
            "Monocyte",
            "Fibroblast",
        ]
        assert (
            result.adata.obs.loc["cell_0", "zr_display"] == "Immune | T cell | CD8-positive T cell"
        )

    def test_generic_stromal_labels_are_refined_by_marker_expression(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = ad.AnnData(
            X=np.array(
                [
                    [100.0, 100.0, 100.0, 100.0, 100.0],
                    [10.0, 10.0, 10.0, 10.0, 10.0],
                ],
                dtype=np.float32,
            )
        )
        adata.obs_names = ["cell_0", "cell_1"]
        adata.var_names = ["RGS5", "PDGFRB", "CSPG4", "MCAM", "DES"]
        adata.obs["leiden"] = ["0", "0"]

        method = CellTypistMethod()
        mock_pred = self._make_mock_predictions(
            adata,
            "Immune_All_Low.pkl",
            labels=["Stromal", "Stromal"],
        )

        self._set_mock_annotate(monkeypatch, mock_pred)

        result = method.execute(
            CellTypistInput(adata=adata, annotation_method="hybrid", majority_voting=False),
            compute=None,
        )

        assert result.adata.obs.loc["cell_0", "annotation_cell_type"] == "Pericyte"
        assert result.adata.obs.loc["cell_0", "annotation_source"] == "stromal_resolution"
        assert result.metrics.n_stromal_resolved >= 1

    def test_cluster_outputs_are_populated(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = make_adata(n_cells=60, n_genes=200, n_clusters=3)
        method = CellTypistMethod()
        mock_pred = self._make_mock_predictions(adata, "Immune_All_Low.pkl")

        self._set_mock_annotate(monkeypatch, mock_pred)

        result = method.execute(
            CellTypistInput(adata=adata, annotation_method="hybrid", majority_voting=False),
            compute=None,
        )

        assert "annotation_label" in result.adata.obs.columns
        assert "annotation_confidence" in result.adata.obs.columns
        assert "zerna_cluster_annotations" in result.adata.uns
        assert "cluster_markers" in result.adata.uns
        assert result.metrics.n_clusters_annotated == 3

    def test_marker_pack_scoring_bootstraps_cluster_labels(self, monkeypatch, tmp_path):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        X = np.array(
            [
                [100.0, 90.0, 1.0, 1.0, 0.0, 0.0],
                [95.0, 105.0, 2.0, 0.0, 0.0, 0.0],
                [110.0, 85.0, 1.0, 2.0, 0.0, 0.0],
                [1.0, 1.0, 100.0, 95.0, 0.0, 0.0],
                [2.0, 0.0, 105.0, 100.0, 0.0, 0.0],
                [0.0, 2.0, 90.0, 110.0, 0.0, 0.0],
            ],
            dtype=np.float32,
        )
        adata = ad.AnnData(X=X)
        adata.obs_names = [f"cell_{i}" for i in range(6)]
        adata.var_names = ["G1", "G2", "G3", "G4", "G5", "G6"]
        adata.obs["leiden"] = ["0", "0", "0", "1", "1", "1"]

        method = CellTypistMethod()
        mock_pred = self._make_mock_predictions(
            adata,
            "Immune_All_Low.pkl",
            labels=["Unknown"] * adata.n_obs,
        )

        self._set_mock_annotate(monkeypatch, mock_pred)

        marker_pack = {
            "markers": {
                "Type A": ["G1", "G2"],
                "Type B": ["G3", "G4"],
            }
        }
        export_path = tmp_path / "cluster_markers.csv"
        result = method.execute(
            CellTypistInput(
                adata=adata,
                annotation_method="hybrid",
                majority_voting=False,
                marker_pack=marker_pack,
                cluster_markers_export_path=str(export_path),
            ),
            compute=None,
        )

        assert set(result.adata.obs.loc[result.adata.obs["leiden"] == "0", "annotation_label"]) == {
            "Type A"
        }
        assert set(result.adata.obs.loc[result.adata.obs["leiden"] == "1", "annotation_label"]) == {
            "Type B"
        }
        assert result.adata.uns["zerna_cluster_annotations"]["0"]["mode"] == "marker_pack"
        assert result.adata.uns["cluster_markers_path"] == str(export_path)
        assert export_path.exists()

    def test_marker_pack_only_annotation_mode_skips_celltypist(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = ad.AnnData(
            X=np.asarray(
                [
                    [8.0, 7.0, 0.0, 0.0, 0.0, 0.0],
                    [7.0, 8.0, 0.0, 0.0, 0.0, 0.0],
                    [8.0, 6.0, 0.0, 0.0, 0.0, 0.0],
                    [0.0, 0.0, 8.0, 7.0, 8.0, 7.0],
                    [0.0, 0.0, 7.0, 8.0, 7.0, 8.0],
                    [0.0, 0.0, 9.0, 7.0, 8.0, 6.0],
                ],
                dtype=np.float32,
            )
        )
        adata.obs_names = [f"cell_{i}" for i in range(6)]
        adata.var_names = ["CD3D", "CD3E", "COL1A1", "COL1A2", "DCN", "LUM"]
        adata.obs["leiden"] = ["0", "0", "0", "1", "1", "1"]

        def fail_resolve_model(*_args, **_kwargs):
            raise AssertionError("CellTypist should not run in marker_pack mode")

        monkeypatch.setattr(
            "methods.annotation.cell_type_annotation._resolve_celltypist_model",
            fail_resolve_model,
        )

        marker_pack = {
            "markers": {
                "T cell": ["CD3D", "CD3E"],
                "Fibroblast": ["COL1A1", "COL1A2", "DCN", "LUM"],
            }
        }

        method = CellTypistMethod()
        result = method.execute(
            CellTypistInput(
                adata=adata,
                annotation_method="marker_pack",
                majority_voting=False,
                cluster_key="leiden",
                marker_pack=marker_pack,
            ),
            compute=None,
        )

        assert result.metrics.annotation_method_used == "marker_pack"
        assert set(result.adata.obs["annotation_label"]) == {"T cell", "Fibroblast"}
        assert "celltypist_prob_matrix" in result.adata.obsm

    def test_legacy_yaml_marker_pack_is_loaded(self, tmp_path):
        from methods.annotation.cell_type_annotation import _load_marker_pack

        marker_pack_path = tmp_path / "legacy_markers.yaml"
        marker_pack_path.write_text(
            """
Lineage:
  Immune:
    include: [PTPRC]
    exclude: [EPCAM]
Subtypes:
  Immune:
    CD8_T:
      genes: [CD8A, CD8B]
      not_genes_soft: [MS4A1]
""".strip(),
            encoding="utf-8",
        )

        marker_pack = _load_marker_pack(None, str(marker_pack_path))

        assert marker_pack is not None
        assert marker_pack["Immune"]["core"] == ["PTPRC"]
        assert marker_pack["Immune"]["exclude"] == ["EPCAM"]
        assert marker_pack["CD8 T"]["high"] == ["CD8A", "CD8B"]
        assert marker_pack["CD8 T"]["soft_exclude"] == ["MS4A1"]

    def test_auto_model_uses_inferred_species_default(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = make_adata(n_cells=20, n_genes=50, n_clusters=2)
        adata.var_names = [
            "Cxcl13",
            "Cxcr5",
            "Col1a1",
            "Actb",
            "Gapdh",
        ] + [f"Gene_{i}" for i in range(45)]

        method = CellTypistMethod()
        mock_pred = self._make_mock_predictions(adata, "Adult_Mouse_Gut.pkl")
        captured: dict[str, str] = {}

        def record_model(model_name: str):
            captured["model_name"] = str(model_name)
            return object()

        monkeypatch.setattr(
            "methods.annotation.cell_type_annotation._resolve_celltypist_model",
            record_model,
        )
        monkeypatch.setattr(
            "methods.annotation.cell_type_annotation._predict_celltypist_in_chunks",
            lambda *_args, **_kwargs: mock_pred,
        )

        result = method.execute(
            CellTypistInput(
                adata=adata,
                annotation_method="hybrid",
                majority_voting=False,
                model_name="auto",
                species="auto",
            ),
            compute=None,
        )

        assert captured["model_name"] == "Adult_Mouse_Gut.pkl"
        assert result.metrics.model_used == "Adult_Mouse_Gut.pkl"

    def test_hybrid_annotation_reports_hybrid_mode(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = ad.AnnData(
            X=np.asarray(
                [
                    [8.0, 7.0, 0.0, 0.0, 0.0, 0.0],
                    [7.0, 8.0, 0.0, 0.0, 0.0, 0.0],
                    [8.0, 6.0, 0.0, 0.0, 0.0, 0.0],
                    [0.0, 0.0, 8.0, 7.0, 8.0, 7.0],
                    [0.0, 0.0, 7.0, 8.0, 7.0, 8.0],
                    [0.0, 0.0, 9.0, 7.0, 8.0, 6.0],
                ],
                dtype=np.float32,
            )
        )
        adata.obs_names = [f"cell_{i}" for i in range(6)]
        adata.var_names = ["CD3D", "CD3E", "COL1A1", "COL1A2", "DCN", "LUM"]
        adata.obs["leiden"] = ["0", "0", "0", "1", "1", "1"]

        mock_pred = self._make_mock_predictions(
            adata,
            "Immune_All_Low.pkl",
            labels=["T cell", "T cell", "T cell", "Fibroblast", "Fibroblast", "Fibroblast"],
        )
        self._set_mock_annotate(monkeypatch, mock_pred)

        marker_pack = {
            "markers": {
                "T cell": ["CD3D", "CD3E"],
                "Fibroblast": ["COL1A1", "COL1A2", "DCN", "LUM"],
            }
        }

        method = CellTypistMethod()
        result = method.execute(
            CellTypistInput(
                adata=adata,
                annotation_method="hybrid",
                majority_voting=False,
                cluster_key="leiden",
                marker_pack=marker_pack,
            ),
            compute=None,
        )

        assert result.metrics.annotation_method_used == "hybrid"
        assert result.metrics.cluster_annotation_mode == "hybrid_marker_pack"

    def test_cluster_prior_breaks_marker_pack_ties(self, monkeypatch, tmp_path):
        pytest.importorskip("sklearn")
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        X = np.array(
            [
                [100.0, 90.0, 1.0, 1.0],
                [95.0, 105.0, 1.0, 0.0],
                [110.0, 85.0, 0.0, 2.0],
                [1.0, 1.0, 100.0, 95.0],
                [2.0, 0.0, 105.0, 100.0],
                [0.0, 2.0, 90.0, 110.0],
            ],
            dtype=np.float32,
        )
        adata = ad.AnnData(X=X)
        adata.obs_names = [f"cell_{i}" for i in range(6)]
        adata.var_names = ["G1", "G2", "G3", "G4"]
        adata.obs["leiden"] = ["0", "0", "0", "1", "1", "1"]

        method = CellTypistMethod()
        mock_pred = self._make_mock_predictions(
            adata,
            "Immune_All_Low.pkl",
            labels=["Unknown"] * adata.n_obs,
        )

        self._set_mock_annotate(monkeypatch, mock_pred)

        prior_path = tmp_path / "cluster_prior.jsonl"
        prior_path.write_text(
            json.dumps(
                {
                    "cluster_id": "prior_1",
                    "top_degs": ["G1", "G2"],
                    "tissue": "",
                    "cancer": "",
                    "level3_label": "Type B",
                    "source_dataset": "fixture",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        marker_pack = {
            "markers": {
                "Type A": ["G1", "G2"],
                "Type B": ["G1", "G2"],
                "Type C": ["G3", "G4"],
            }
        }
        result = method.execute(
            CellTypistInput(
                adata=adata,
                annotation_method="hybrid",
                majority_voting=False,
                marker_pack=marker_pack,
                cluster_prior_path=str(prior_path),
            ),
            compute=None,
        )

        assert set(result.adata.obs.loc[result.adata.obs["leiden"] == "0", "annotation_label"]) == {
            "Type B"
        }
        assert (
            result.adata.uns["zerna_cluster_annotations"]["0"]["retrieval_tiebreak_applied"] is True
        )
        assert result.metrics.retrieval_prior_used is True

    def test_conservative_annotation_abstains_on_cross_lineage_tie(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = ad.AnnData(
            X=np.asarray(
                [
                    [10.0, 9.0, 10.0, 9.0],
                    [9.0, 10.0, 9.0, 10.0],
                    [10.0, 10.0, 10.0, 10.0],
                    [9.0, 9.0, 9.0, 9.0],
                    [0.0, 0.0, 0.0, 0.0],
                    [0.0, 0.0, 0.0, 0.0],
                ],
                dtype=np.float32,
            )
        )
        adata.obs_names = [f"cell_{i}" for i in range(6)]
        adata.var_names = ["CD3D", "CD3E", "COL1A1", "COL1A2"]
        adata.obs["leiden"] = ["0", "0", "0", "0", "1", "1"]

        mock_pred = self._make_mock_predictions(
            adata,
            "Immune_All_Low.pkl",
            labels=["T cell", "Fibroblast", "T cell", "Fibroblast", "Unknown", "Unknown"],
        )
        self._set_mock_annotate(monkeypatch, mock_pred)

        marker_pack = {
            "markers": {
                "T cell": ["CD3D", "CD3E"],
                "Fibroblast": ["COL1A1", "COL1A2"],
            }
        }

        method = CellTypistMethod()
        result = method.execute(
            CellTypistInput(
                adata=adata,
                annotation_method="conservative",
                majority_voting=False,
                cluster_key="leiden",
                marker_pack=marker_pack,
            ),
            compute=None,
        )

        assert set(result.adata.obs.loc[result.adata.obs["leiden"] == "0", "annotation_label"]) == {
            "Unknown"
        }
        assert set(
            result.adata.obs.loc[result.adata.obs["leiden"] == "0", "annotation_status"]
        ) == {"ambiguous"}
        assert result.adata.uns["zerna_cluster_annotations"]["0"]["mode"] == "conservative"
        assert result.metrics.n_clusters_abstained == 0

    def test_conservative_annotation_falls_back_to_lineage(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = ad.AnnData(
            X=np.asarray(
                [
                    [10.0, 9.0, 10.0, 9.0],
                    [9.0, 10.0, 9.0, 10.0],
                    [10.0, 10.0, 10.0, 10.0],
                    [9.0, 9.0, 9.0, 9.0],
                    [0.0, 0.0, 0.0, 0.0],
                    [0.0, 0.0, 0.0, 0.0],
                ],
                dtype=np.float32,
            )
        )
        adata.obs_names = [f"cell_{i}" for i in range(6)]
        adata.var_names = ["CD3D", "CD3E", "MS4A1", "CD79A"]
        adata.obs["leiden"] = ["0", "0", "0", "0", "1", "1"]

        mock_pred = self._make_mock_predictions(
            adata,
            "Immune_All_Low.pkl",
            labels=["T cell", "B cell", "T cell", "B cell", "Unknown", "Unknown"],
        )
        self._set_mock_annotate(monkeypatch, mock_pred)

        marker_pack = {
            "markers": {
                "T cell": ["CD3D", "CD3E"],
                "B cell": ["MS4A1", "CD79A"],
            }
        }

        method = CellTypistMethod()
        result = method.execute(
            CellTypistInput(
                adata=adata,
                annotation_method="conservative",
                majority_voting=False,
                cluster_key="leiden",
                marker_pack=marker_pack,
            ),
            compute=None,
        )

        assert set(result.adata.obs.loc[result.adata.obs["leiden"] == "0", "annotation_label"]) == {
            "Lymphoid"
        }
        assert set(
            result.adata.obs.loc[result.adata.obs["leiden"] == "0", "annotation_resolution"]
        ) == {"lineage"}
        assert result.metrics.n_lineage_only_clusters >= 1

    def test_conservative_annotation_emits_benchmark_report(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = ad.AnnData(
            X=np.asarray(
                [
                    [10.0, 9.0, 0.0, 0.0],
                    [9.0, 10.0, 0.0, 0.0],
                    [10.0, 10.0, 0.0, 0.0],
                    [0.0, 0.0, 10.0, 9.0],
                    [0.0, 0.0, 9.0, 10.0],
                    [0.0, 0.0, 10.0, 10.0],
                ],
                dtype=np.float32,
            )
        )
        adata.obs_names = [f"cell_{i}" for i in range(6)]
        adata.var_names = ["CD3D", "CD3E", "COL1A1", "COL1A2"]
        adata.obs["leiden"] = ["0", "0", "0", "1", "1", "1"]
        adata.obs["reference_label"] = [
            "T cell",
            "T cell",
            "T cell",
            "Fibroblast",
            "Fibroblast",
            "Fibroblast",
        ]

        mock_pred = self._make_mock_predictions(
            adata,
            "Immune_All_Low.pkl",
            labels=["T cell", "T cell", "T cell", "Fibroblast", "Fibroblast", "Fibroblast"],
        )
        self._set_mock_annotate(monkeypatch, mock_pred)

        marker_pack = {
            "markers": {
                "T cell": ["CD3D", "CD3E"],
                "Fibroblast": ["COL1A1", "COL1A2"],
            }
        }

        method = CellTypistMethod()
        result = method.execute(
            CellTypistInput(
                adata=adata,
                annotation_method="conservative",
                majority_voting=False,
                cluster_key="leiden",
                marker_pack=marker_pack,
                benchmark_reference_key="reference_label",
            ),
            compute=None,
        )

        report = result.adata.uns["annotation_benchmark"]
        assert report["reference_key"] == "reference_label"
        assert report["coverage"] == pytest.approx(1.0)
        assert report["accuracy_on_covered"] == pytest.approx(1.0)
        assert report["overall_accuracy"] == pytest.approx(1.0)
        assert report["lineage_consistent_accuracy"] == pytest.approx(1.0)
        assert result.metrics.benchmark_reference_key == "reference_label"
        assert result.metrics.benchmark_coverage == pytest.approx(1.0)

    def test_benchmark_report_tracks_lineage_consistency_for_fallback_calls(self, monkeypatch):
        from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

        adata = ad.AnnData(
            X=np.asarray(
                [
                    [10.0, 9.0, 10.0, 9.0],
                    [9.0, 10.0, 9.0, 10.0],
                    [10.0, 10.0, 10.0, 10.0],
                    [9.0, 9.0, 9.0, 9.0],
                    [0.0, 0.0, 0.0, 0.0],
                    [0.0, 0.0, 0.0, 0.0],
                ],
                dtype=np.float32,
            )
        )
        adata.obs_names = [f"cell_{i}" for i in range(6)]
        adata.var_names = ["CD3D", "CD3E", "MS4A1", "CD79A"]
        adata.obs["leiden"] = ["0", "0", "0", "0", "1", "1"]
        adata.obs["reference_label"] = ["T cell", "B cell", "T cell", "B cell", "", ""]

        mock_pred = self._make_mock_predictions(
            adata,
            "Immune_All_Low.pkl",
            labels=["T cell", "B cell", "T cell", "B cell", "Unknown", "Unknown"],
        )
        self._set_mock_annotate(monkeypatch, mock_pred)

        marker_pack = {
            "markers": {
                "T cell": ["CD3D", "CD3E"],
                "B cell": ["MS4A1", "CD79A"],
            }
        }

        result = CellTypistMethod().execute(
            CellTypistInput(
                adata=adata,
                annotation_method="conservative",
                majority_voting=False,
                cluster_key="leiden",
                marker_pack=marker_pack,
                benchmark_reference_key="reference_label",
            ),
            compute=None,
        )

        report = result.adata.uns["annotation_benchmark"]
        assert set(result.adata.obs.loc[result.adata.obs["leiden"] == "0", "annotation_label"]) == {
            "Lymphoid"
        }
        assert report["coverage"] == pytest.approx(1.0)
        assert report["accuracy_on_covered"] == pytest.approx(0.0)
        assert report["lineage_consistent_accuracy"] == pytest.approx(1.0)
        assert report["lineage_consistent_accuracy_on_covered"] == pytest.approx(1.0)
        assert result.metrics.benchmark_lineage_consistent_accuracy == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 11.2 Differential expression tests
# ---------------------------------------------------------------------------


class TestDifferentialExpressionMethod:
    def test_results_df_has_required_columns(self):
        from methods.annotation.differential_expression import (
            DifferentialExpressionInput,
            DifferentialExpressionMethod,
        )

        adata = make_adata(n_cells=80, n_genes=200, n_clusters=3)
        method = DifferentialExpressionMethod()
        result = method.execute(
            DifferentialExpressionInput(adata=adata, cluster_key="leiden"),
            compute=None,
        )
        required_cols = {"cluster", "gene", "logfoldchange", "pval", "pval_adj", "score"}
        assert required_cols.issubset(set(result.results_df.columns))

    def test_all_clusters_represented(self):
        from methods.annotation.differential_expression import (
            DifferentialExpressionInput,
            DifferentialExpressionMethod,
        )

        adata = make_adata(n_cells=90, n_genes=200, n_clusters=3)
        method = DifferentialExpressionMethod()
        result = method.execute(
            DifferentialExpressionInput(adata=adata, cluster_key="leiden"),
            compute=None,
        )
        clusters_in_results = set(result.results_df["cluster"].unique())
        expected_clusters = {"0", "1", "2"}
        assert clusters_in_results == expected_clusters

    def test_pval_adj_in_range(self):
        from methods.annotation.differential_expression import (
            DifferentialExpressionInput,
            DifferentialExpressionMethod,
        )

        adata = make_adata(n_cells=80, n_genes=200, n_clusters=3)
        method = DifferentialExpressionMethod()
        result = method.execute(
            DifferentialExpressionInput(adata=adata, cluster_key="leiden"),
            compute=None,
        )
        pvals = result.results_df["pval_adj"].values
        assert (pvals >= 0.0).all() and (pvals <= 1.0).all()

    def test_results_sorted_by_pval_adj(self):
        from methods.annotation.differential_expression import (
            DifferentialExpressionInput,
            DifferentialExpressionMethod,
        )

        adata = make_adata(n_cells=80, n_genes=200, n_clusters=3)
        method = DifferentialExpressionMethod()
        result = method.execute(
            DifferentialExpressionInput(adata=adata, cluster_key="leiden"),
            compute=None,
        )
        for cluster in result.results_df["cluster"].unique():
            sub = result.results_df[result.results_df["cluster"] == cluster]
            assert (sub["pval_adj"].values == np.sort(sub["pval_adj"].values)).all()

    def test_invalid_cluster_key_raises(self):
        from methods.annotation.differential_expression import (
            DifferentialExpressionInput,
            DifferentialExpressionMethod,
        )

        adata = make_adata(n_cells=60, n_genes=200, n_clusters=2)
        del adata.obs["leiden"]
        method = DifferentialExpressionMethod()
        with pytest.raises(ValueError, match="not found"):
            method.execute(
                DifferentialExpressionInput(adata=adata, cluster_key="nonexistent"),
                compute=None,
            )

    def test_missing_requested_cluster_key_falls_back_to_detected_column(self):
        from methods.annotation.differential_expression import (
            DifferentialExpressionInput,
            DifferentialExpressionMethod,
        )

        adata = make_adata(n_cells=60, n_genes=200, n_clusters=2)
        adata.obs["cluster"] = adata.obs["leiden"].astype(str)
        del adata.obs["leiden"]

        method = DifferentialExpressionMethod()
        result = method.execute(
            DifferentialExpressionInput(adata=adata, cluster_key="leiden"),
            compute=None,
        )

        assert result.metrics.cluster_key == "cluster"

    def test_rank_genes_groups_stored_in_uns(self):
        from methods.annotation.differential_expression import (
            DifferentialExpressionInput,
            DifferentialExpressionMethod,
        )

        adata = make_adata(n_cells=80, n_genes=200, n_clusters=2)
        method = DifferentialExpressionMethod()
        result = method.execute(
            DifferentialExpressionInput(adata=adata, cluster_key="leiden"),
            compute=None,
        )
        assert "rank_genes_groups" in result.adata.uns

    def test_results_to_csv_produces_bytes(self):
        from methods.annotation.differential_expression import (
            DifferentialExpressionInput,
            DifferentialExpressionMethod,
            results_to_csv,
        )

        adata = make_adata(n_cells=60, n_genes=200, n_clusters=2)
        method = DifferentialExpressionMethod()
        result = method.execute(
            DifferentialExpressionInput(adata=adata, cluster_key="leiden"),
            compute=None,
        )
        csv_bytes = results_to_csv(result.results_df)
        assert isinstance(csv_bytes, bytes)
        assert len(csv_bytes) > 0
        # Verify it's valid CSV
        import io

        df_roundtrip = pd.read_csv(io.BytesIO(csv_bytes))
        assert set(df_roundtrip.columns) == set(result.results_df.columns)

    def test_metrics_populated(self):
        from methods.annotation.differential_expression import (
            DifferentialExpressionInput,
            DifferentialExpressionMethod,
        )

        adata = make_adata(n_cells=90, n_genes=200, n_clusters=3)
        method = DifferentialExpressionMethod()
        result = method.execute(
            DifferentialExpressionInput(adata=adata, cluster_key="leiden"),
            compute=None,
        )
        assert result.metrics.n_clusters == 3
        assert result.metrics.n_genes_tested == 200


# ---------------------------------------------------------------------------
# Property 36: Differential Expression Completeness
# Validates: Requirements 24.1, 24.2
# ---------------------------------------------------------------------------


@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    n_cells=st.integers(min_value=30, max_value=120),
    n_genes=st.integers(min_value=50, max_value=300),
    n_clusters=st.integers(min_value=2, max_value=5),
    seed=st.integers(min_value=0, max_value=999),
)
def test_property_36_de_completeness(n_cells, n_genes, n_clusters, seed):
    """Property 36: DE results must cover all clusters with valid statistics.

    For any AnnData with ≥2 clusters:
    1. Every cluster must appear in results_df
    2. Every row must have finite logfoldchange, pval in [0,1], pval_adj in [0,1]
    3. Results must be sorted by pval_adj within each cluster
    """
    from methods.annotation.differential_expression import (
        DifferentialExpressionInput,
        DifferentialExpressionMethod,
    )

    adata = make_adata(n_cells=n_cells, n_genes=n_genes, n_clusters=n_clusters, seed=seed)
    method = DifferentialExpressionMethod()
    result = method.execute(
        DifferentialExpressionInput(adata=adata, cluster_key="leiden"),
        compute=None,
    )

    df = result.results_df
    expected_clusters = {str(i) for i in range(n_clusters)}

    # Property: all clusters represented
    assert set(df["cluster"].unique()) == expected_clusters, (
        f"Missing clusters in DE results: {expected_clusters - set(df['cluster'].unique())}"
    )

    # Property: valid statistics
    assert np.isfinite(df["logfoldchange"].values).all(), "logfoldchange contains non-finite values"
    assert (df["pval"].values >= 0).all() and (df["pval"].values <= 1).all(), "pval out of [0,1]"
    assert (df["pval_adj"].values >= 0).all() and (df["pval_adj"].values <= 1).all(), (
        "pval_adj out of [0,1]"
    )

    # Property: sorted by pval_adj within each cluster
    for cluster in df["cluster"].unique():
        sub = df[df["cluster"] == cluster]["pval_adj"].values
        assert (sub == np.sort(sub)).all(), f"Results not sorted by pval_adj for cluster {cluster}"


# ---------------------------------------------------------------------------
# 11.3 Pathway scoring tests
# ---------------------------------------------------------------------------


class TestPathwayScoringMethod:
    def test_scores_stored_in_obsm(self):
        from methods.annotation.pathway_scoring import PathwayScoringInput, PathwayScoringMethod

        adata = make_adata(n_cells=60, n_genes=300, n_clusters=2)
        net = make_pathway_net(n_pathways=3, n_genes_per_pathway=10)
        method = PathwayScoringMethod()
        result = method.execute(
            PathwayScoringInput(adata=adata, net=net, methods=["ulm"]),
            compute=None,
        )
        assert "pathway_scores" in result.adata.obsm

    def test_scores_shape_matches_cells(self):
        from methods.annotation.pathway_scoring import PathwayScoringInput, PathwayScoringMethod

        adata = make_adata(n_cells=60, n_genes=300, n_clusters=2)
        net = make_pathway_net(n_pathways=3, n_genes_per_pathway=10)
        method = PathwayScoringMethod()
        result = method.execute(
            PathwayScoringInput(adata=adata, net=net, methods=["ulm"]),
            compute=None,
        )
        scores = result.adata.obsm["pathway_scores"]
        assert scores.shape[0] == 60

    def test_provenance_stored_in_uns(self):
        from methods.annotation.pathway_scoring import PathwayScoringInput, PathwayScoringMethod

        adata = make_adata(n_cells=60, n_genes=300, n_clusters=2)
        net = make_pathway_net(n_pathways=3, n_genes_per_pathway=10)
        method = PathwayScoringMethod()
        result = method.execute(
            PathwayScoringInput(
                adata=adata,
                net=net,
                methods=["ulm"],
                pathway_database="MSigDB",
                knowledge_pack_version="v2024.1",
            ),
            compute=None,
        )
        meta = result.adata.uns["pathway_scoring_meta"]
        assert meta["pathway_database"] == "MSigDB"
        assert meta["knowledge_pack_version"] == "v2024.1"
        assert meta["pathway_names"] == ["pathway_0", "pathway_1", "pathway_2"]
        assert meta.get("expression_source_used") == "adata_X"
        assert meta.get("used_log1p_layer") is False
        assert meta.get("fallback_to_adata_x") is True
        bio = result.adata.uns["zerna_pathway"]
        assert bio["pathway_mode"] == "cell_level_activity_scoring"
        assert bio["pathway_database_requested"] == "MSigDB"
        assert bio["per_cell"] is True
        assert bio["condition_aware"] is False
        assert bio["replicate_aware"] is False
        assert bio["pathway_method_requested"] == ["ulm"]

    def test_custom_obsm_key(self):
        from methods.annotation.pathway_scoring import PathwayScoringInput, PathwayScoringMethod

        adata = make_adata(n_cells=60, n_genes=300, n_clusters=2)
        net = make_pathway_net(n_pathways=3, n_genes_per_pathway=10)
        method = PathwayScoringMethod()
        result = method.execute(
            PathwayScoringInput(adata=adata, net=net, methods=["ulm"], obsm_key="my_scores"),
            compute=None,
        )
        assert "my_scores" in result.adata.obsm

    def test_missing_weight_column_handled(self):
        from methods.annotation.pathway_scoring import PathwayScoringInput, PathwayScoringMethod

        adata = make_adata(n_cells=60, n_genes=300, n_clusters=2)
        net = make_pathway_net(n_pathways=3, n_genes_per_pathway=10)
        net_no_weight = net.drop(columns=["weight"])
        method = PathwayScoringMethod()
        # Should not raise — weight defaults to 1.0
        result = method.execute(
            PathwayScoringInput(adata=adata, net=net_no_weight, methods=["ulm"]),
            compute=None,
        )
        assert "pathway_scores" in result.adata.obsm

    def test_metrics_populated(self):
        from methods.annotation.pathway_scoring import PathwayScoringInput, PathwayScoringMethod

        adata = make_adata(n_cells=60, n_genes=300, n_clusters=2)
        net = make_pathway_net(n_pathways=4, n_genes_per_pathway=10)
        method = PathwayScoringMethod()
        result = method.execute(
            PathwayScoringInput(adata=adata, net=net, methods=["ulm"]),
            compute=None,
        )
        assert result.metrics.n_cells == 60
        assert result.metrics.n_pathways_scored >= 0

    def test_wsum_falls_back_when_decoupler_method_missing(self, monkeypatch):
        import decoupler as dc

        from methods.annotation.pathway_scoring import PathwayScoringInput, PathwayScoringMethod

        monkeypatch.delattr(dc.mt, "wsum", raising=False)

        adata = make_adata(n_cells=40, n_genes=200, n_clusters=2)
        net = make_pathway_net(n_pathways=3, n_genes_per_pathway=8)
        result = PathwayScoringMethod().execute(
            PathwayScoringInput(adata=adata, net=net, methods=["wsum"]),
            compute=None,
        )

        assert "pathway_scores" in result.adata.obsm
        assert result.metrics.methods_used == ["wsum_weighted"]
        assert result.adata.uns["pathway_scoring_meta"]["methods_used"] == ["wsum_weighted"]
        assert result.adata.uns["zerna_pathway"]["pathway_methods_executed"] == ["wsum_weighted"]

    def test_prefers_layers_log1p_when_present(self):
        from methods.annotation.pathway_scoring import PathwayScoringInput, PathwayScoringMethod

        n_cells, n_genes = 20, 100
        X = sp.csr_matrix(np.zeros((n_cells, n_genes), dtype=np.float32))
        adata = ad.AnnData(X=X)
        adata.obs_names = [f"cell_{i}" for i in range(n_cells)]
        adata.var_names = [f"gene_{i}" for i in range(n_genes)]
        rng = np.random.default_rng(0)
        adata.layers["log1p"] = sp.csr_matrix(
            rng.random((n_cells, n_genes)).astype(np.float32) * 2.0
        )
        net = make_pathway_net(n_pathways=2, n_genes_per_pathway=5)
        method = PathwayScoringMethod()
        result = method.execute(
            PathwayScoringInput(
                adata=adata,
                net=net,
                methods=["ulm"],
                pathway_database="PROGENy",
            ),
            compute=None,
        )
        scores = result.adata.obsm["pathway_scores"]
        assert np.abs(np.asarray(scores)).sum() > 1e-6
        bio = result.adata.uns["zerna_pathway"]
        assert bio["used_log1p_layer"] is True
        assert bio["fallback_to_adata_x"] is False
        assert bio["expression_source_used"] == "layers_log1p"

    def test_records_fallback_to_x_when_no_log1p_layer(self):
        from methods.annotation.pathway_scoring import PathwayScoringInput, PathwayScoringMethod

        adata = make_adata(n_cells=40, n_genes=200, n_clusters=2)
        assert "log1p" not in adata.layers
        net = make_pathway_net(n_pathways=3, n_genes_per_pathway=8)
        method = PathwayScoringMethod()
        result = method.execute(
            PathwayScoringInput(adata=adata, net=net, methods=["ulm"]),
            compute=None,
        )
        bio = result.adata.uns["zerna_pathway"]
        assert bio["used_log1p_layer"] is False
        assert bio["fallback_to_adata_x"] is True
        assert bio["expression_source_used"] == "adata_X"


# ---------------------------------------------------------------------------
# Property 37: Pathway Score Storage in H5AD
# Validates: Requirements 25.3, 25.4
# ---------------------------------------------------------------------------


@settings(max_examples=15, suppress_health_check=[HealthCheck.too_slow])
@given(
    n_cells=st.integers(min_value=30, max_value=100),
    n_pathways=st.integers(min_value=2, max_value=8),
    n_genes_per_pathway=st.integers(min_value=5, max_value=20),
    seed=st.integers(min_value=0, max_value=999),
)
def test_property_37_pathway_score_storage(n_cells, n_pathways, n_genes_per_pathway, seed):
    """Property 37: Pathway scores must be stored in adata.obsm with correct shape.

    For any AnnData and pathway network:
    1. adata.obsm[obsm_key] must exist after scoring
    2. Shape must be (n_cells, n_pathways_scored)
    3. Provenance metadata must be stored in adata.uns
    """
    from methods.annotation.pathway_scoring import PathwayScoringInput, PathwayScoringMethod

    n_genes = n_pathways * n_genes_per_pathway + 50  # ensure enough genes
    adata = make_adata(n_cells=n_cells, n_genes=n_genes, n_clusters=2, seed=seed)
    net = make_pathway_net(
        n_pathways=n_pathways,
        n_genes_per_pathway=n_genes_per_pathway,
        gene_names=list(adata.var_names),
    )

    method = PathwayScoringMethod()
    result = method.execute(
        PathwayScoringInput(
            adata=adata,
            net=net,
            methods=["ulm"],
            pathway_database="TestDB",
            knowledge_pack_version="v1.0",
        ),
        compute=None,
    )

    # Property: obsm key must exist
    assert "pathway_scores" in result.adata.obsm, "pathway_scores not found in adata.obsm"

    # Property: row count matches n_cells
    scores = result.adata.obsm["pathway_scores"]
    assert scores.shape[0] == n_cells, (
        f"Expected {n_cells} rows in pathway_scores, got {scores.shape[0]}"
    )

    # Property: provenance metadata stored
    assert "pathway_scoring_meta" in result.adata.uns, "pathway_scoring_meta not in adata.uns"
    meta = result.adata.uns["pathway_scoring_meta"]
    assert meta["pathway_database"] == "TestDB"
    assert meta["knowledge_pack_version"] == "v1.0"
    assert "zerna_pathway" in result.adata.uns
    assert result.adata.uns["zerna_pathway"]["pathway_mode"] == "cell_level_activity_scoring"


# ---------------------------------------------------------------------------
# 11.4 Ligand-receptor tests
# ---------------------------------------------------------------------------


class TestLigandReceptorMethod:
    """Unit tests for LigandReceptorMethod.

    Note: These tests mock LIANA to avoid requiring network resources in CI.
    """

    def _mock_liana_results(self, adata, cluster_key):
        """Return a mock LIANA results DataFrame."""
        clusters = adata.obs[cluster_key].unique().tolist()
        rows = []
        for i, src in enumerate(clusters):
            for j, tgt in enumerate(clusters):
                if src != tgt:
                    rows.append(
                        {
                            "source": src,
                            "target": tgt,
                            "ligand_complex": f"LIG_{i}",
                            "receptor_complex": f"REC_{j}",
                            "liana_rank": float(i * len(clusters) + j) / (len(clusters) ** 2),
                            "magnitude_rank": 0.5,
                            "specificity_rank": 0.5,
                        }
                    )
        return pd.DataFrame(rows)

    def test_results_df_has_required_columns(self, monkeypatch):
        import liana

        from methods.annotation.ligand_receptor import LigandReceptorInput, LigandReceptorMethod

        adata = make_adata(n_cells=80, n_genes=200, n_clusters=3)
        method = LigandReceptorMethod()
        mock_df = self._mock_liana_results(adata, "leiden")

        def mock_rank_aggregate(adata, **_kwargs):
            adata.uns["liana_res"] = mock_df

        monkeypatch.setattr(liana.mt, "rank_aggregate", mock_rank_aggregate)

        result = method.execute(
            LigandReceptorInput(adata=adata, cluster_key="leiden", n_perms=0),
            compute=None,
        )
        required_cols = {"source", "target", "ligand_complex", "receptor_complex", "liana_rank"}
        assert required_cols.issubset(set(result.results_df.columns))
        assert "source_display" in result.results_df.columns
        assert "target_display" in result.results_df.columns

    def test_results_sorted_by_liana_rank(self, monkeypatch):
        import liana

        from methods.annotation.ligand_receptor import LigandReceptorInput, LigandReceptorMethod

        adata = make_adata(n_cells=80, n_genes=200, n_clusters=3)
        method = LigandReceptorMethod()
        mock_df = self._mock_liana_results(adata, "leiden")

        def mock_rank_aggregate(adata, **_kwargs):
            adata.uns["liana_res"] = mock_df

        monkeypatch.setattr(liana.mt, "rank_aggregate", mock_rank_aggregate)

        result = method.execute(
            LigandReceptorInput(adata=adata, cluster_key="leiden", n_perms=0),
            compute=None,
        )
        ranks = result.results_df["liana_rank"].values
        assert (ranks == np.sort(ranks)).all()

    def test_metrics_populated(self, monkeypatch):
        import liana

        from methods.annotation.ligand_receptor import LigandReceptorInput, LigandReceptorMethod

        adata = make_adata(n_cells=80, n_genes=200, n_clusters=3)
        method = LigandReceptorMethod()
        mock_df = self._mock_liana_results(adata, "leiden")

        def mock_rank_aggregate(adata, **_kwargs):
            adata.uns["liana_res"] = mock_df

        monkeypatch.setattr(liana.mt, "rank_aggregate", mock_rank_aggregate)

        result = method.execute(
            LigandReceptorInput(adata=adata, cluster_key="leiden", n_perms=0),
            compute=None,
        )
        assert result.metrics.n_clusters == 3
        assert result.metrics.n_interactions > 0
        assert result.metrics.cluster_key == "leiden"

    def test_zerna_ligand_receptor_provenance(self, monkeypatch):
        import liana

        from methods.annotation.ligand_receptor import LigandReceptorInput, LigandReceptorMethod

        adata = make_adata(n_cells=80, n_genes=200, n_clusters=3)
        method = LigandReceptorMethod()
        mock_df = self._mock_liana_results(adata, "leiden")

        def mock_rank_aggregate(adata, **_kwargs):
            adata.uns["liana_res"] = mock_df

        monkeypatch.setattr(liana.mt, "rank_aggregate", mock_rank_aggregate)

        result = method.execute(
            LigandReceptorInput(
                adata=adata,
                cluster_key="leiden",
                n_perms=0,
                communication_grouping="cluster",
            ),
            compute=None,
        )
        bio = result.adata.uns.get("zerna_ligand_receptor")
        assert isinstance(bio, dict)
        assert bio["lr_method"] == "liana_rank_aggregate"
        assert bio["grouping_resolved"] == "leiden"
        assert bio["grouping_source_type"] == "cluster"
        assert bio["annotation_dependency_required"] is False
        assert bio["fallback_applied"] is False
        assert bio["resource_name"] == "consensus"
        assert isinstance(bio["resource_gene_overlap_count"], int)
        assert bio["n_interactions"] == result.metrics.n_interactions

    def test_invalid_cluster_key_raises(self):
        from methods.annotation.ligand_receptor import LigandReceptorInput, LigandReceptorMethod

        adata = make_adata(n_cells=60, n_genes=200, n_clusters=2)
        del adata.obs["leiden"]
        method = LigandReceptorMethod()
        with pytest.raises(ValueError, match="resolvable cluster"):
            method.execute(
                LigandReceptorInput(
                    adata=adata,
                    cluster_key="nonexistent",
                    communication_grouping="cluster",
                ),
                compute=None,
            )

    def test_missing_requested_cluster_key_falls_back_to_detected_column(self, monkeypatch):
        import liana

        from methods.annotation.ligand_receptor import LigandReceptorInput, LigandReceptorMethod

        adata = make_adata(n_cells=80, n_genes=200, n_clusters=3)
        adata.obs["cluster"] = adata.obs["leiden"].astype(str)
        del adata.obs["leiden"]
        method = LigandReceptorMethod()
        mock_df = self._mock_liana_results(adata, "cluster")

        def mock_rank_aggregate(adata, **_kwargs):
            adata.uns["liana_res"] = mock_df

        monkeypatch.setattr(liana.mt, "rank_aggregate", mock_rank_aggregate)

        result = method.execute(
            LigandReceptorInput(adata=adata, cluster_key="leiden", n_perms=0),
            compute=None,
        )

        assert result.metrics.cluster_key == "cluster"

    def test_too_few_cells_per_cluster_raises(self):
        from methods.annotation.ligand_receptor import LigandReceptorInput, LigandReceptorMethod

        adata = make_adata(n_cells=10, n_genes=200, n_clusters=2)
        method = LigandReceptorMethod()
        with pytest.raises(ValueError, match="at least 2 groups"):
            method.execute(
                LigandReceptorInput(adata=adata, cluster_key="leiden", min_cells=100),
                compute=None,
            )

    def test_results_to_csv_produces_bytes(self, monkeypatch):
        import liana

        from methods.annotation.ligand_receptor import (
            LigandReceptorInput,
            LigandReceptorMethod,
            results_to_csv,
        )

        adata = make_adata(n_cells=80, n_genes=200, n_clusters=3)
        method = LigandReceptorMethod()
        mock_df = self._mock_liana_results(adata, "leiden")

        def mock_rank_aggregate(adata, **_kwargs):
            adata.uns["liana_res"] = mock_df

        monkeypatch.setattr(liana.mt, "rank_aggregate", mock_rank_aggregate)

        result = method.execute(
            LigandReceptorInput(adata=adata, cluster_key="leiden", n_perms=0),
            compute=None,
        )
        csv_bytes = results_to_csv(result.results_df)
        assert isinstance(csv_bytes, bytes)
        assert len(csv_bytes) > 0

    def test_mouse_species_translates_resource_symbols(self, monkeypatch):
        import liana

        from methods.annotation.ligand_receptor import LigandReceptorInput, LigandReceptorMethod

        adata = make_adata(n_cells=60, n_genes=10, n_clusters=3)
        adata.var_names = [
            "Cxcl13",
            "Cxcr5",
            "Col1a1",
            "Itga6",
            "Itgb4",
            "Actb",
            "Gapdh",
            "Lyz2",
            "Pecam1",
            "Kdr",
        ]
        method = LigandReceptorMethod()
        mock_df = self._mock_liana_results(adata, "leiden")

        monkeypatch.setattr(
            liana.resource,
            "select_resource",
            lambda _resource_name: pd.DataFrame(
                [
                    {"ligand": "CXCL13", "receptor": "CXCR5"},
                    {"ligand": "COL1A1", "receptor": "ITGA6_ITGB4"},
                    {"ligand": "MISSING", "receptor": "CXCR5"},
                ]
            ),
        )

        def mock_rank_aggregate(adata, **kwargs):
            resource = kwargs["resource"]
            assert resource is not None
            assert ("Cxcl13", "Cxcr5") in set(
                resource[["ligand", "receptor"]].itertuples(index=False, name=None)
            )
            assert ("Col1a1", "Itga6_Itgb4") in set(
                resource[["ligand", "receptor"]].itertuples(index=False, name=None)
            )
            assert ("Missing", "Cxcr5") not in set(
                resource[["ligand", "receptor"]].itertuples(index=False, name=None)
            )
            adata.uns["liana_res"] = mock_df

        monkeypatch.setattr(liana.mt, "rank_aggregate", mock_rank_aggregate)

        result = method.execute(
            LigandReceptorInput(
                adata=adata,
                cluster_key="leiden",
                n_perms=0,
                species="mouse",
            ),
            compute=None,
        )

        assert result.metrics.n_interactions > 0

    def test_default_species_infers_mouse_from_gene_symbols(self, monkeypatch):
        import liana

        from methods.annotation.ligand_receptor import LigandReceptorInput, LigandReceptorMethod

        adata = make_adata(n_cells=60, n_genes=10, n_clusters=3)
        adata.var_names = [
            "Cxcl13",
            "Cxcr5",
            "Col1a1",
            "Itga6",
            "Itgb4",
            "Actb",
            "Gapdh",
            "Lyz2",
            "Pecam1",
            "Kdr",
        ]
        method = LigandReceptorMethod()
        mock_df = self._mock_liana_results(adata, "leiden")

        monkeypatch.setattr(
            liana.resource,
            "select_resource",
            lambda _resource_name: pd.DataFrame(
                [
                    {"ligand": "CXCL13", "receptor": "CXCR5"},
                    {"ligand": "COL1A1", "receptor": "ITGA6_ITGB4"},
                ]
            ),
        )

        def mock_rank_aggregate(adata, **kwargs):
            resource = kwargs["resource"]
            assert resource is not None
            assert ("Cxcl13", "Cxcr5") in set(
                resource[["ligand", "receptor"]].itertuples(index=False, name=None)
            )
            assert ("Col1a1", "Itga6_Itgb4") in set(
                resource[["ligand", "receptor"]].itertuples(index=False, name=None)
            )
            adata.uns["liana_res"] = mock_df

        monkeypatch.setattr(liana.mt, "rank_aggregate", mock_rank_aggregate)

        result = method.execute(
            LigandReceptorInput(
                adata=adata,
                cluster_key="leiden",
                n_perms=0,
            ),
            compute=None,
        )

        assert result.metrics.n_interactions > 0

    def test_liana_runs_on_slimmed_input(self, monkeypatch):
        import liana

        from methods.annotation.ligand_receptor import LigandReceptorInput, LigandReceptorMethod

        adata = make_adata(n_cells=60, n_genes=200, n_clusters=3)
        adata.var_names = [f"Gene{i}" for i in range(200)]
        method = LigandReceptorMethod()
        mock_df = self._mock_liana_results(adata, "leiden")
        selected_genes = {"Gene0", "Gene1", "Gene2", "Gene3"}

        monkeypatch.setattr(
            liana.resource,
            "select_resource",
            lambda _resource_name: pd.DataFrame(
                [
                    {"ligand": "GENE0_GENE1", "receptor": "GENE2"},
                    {"ligand": "GENE3", "receptor": "GENE2"},
                ]
            ),
        )

        def mock_rank_aggregate(adata, **_kwargs):
            assert list(adata.obs.columns) == ["leiden"]
            assert set(map(str, adata.var_names)) == selected_genes
            adata.uns["liana_res"] = mock_df

        monkeypatch.setattr(liana.mt, "rank_aggregate", mock_rank_aggregate)

        result = method.execute(
            LigandReceptorInput(
                adata=adata,
                cluster_key="leiden",
                n_perms=0,
                species="mouse",
            ),
            compute=None,
        )

        assert result.metrics.n_interactions > 0
        assert "liana_res" in result.adata.uns
