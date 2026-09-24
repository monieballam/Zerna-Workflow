"""Embedding methods (UMAP, t-SNE) for single-cell RNA-seq data."""

import os

_numba_tl = os.environ.get("NUMBA_THREADING_LAYER", "").strip().lower()
if _numba_tl in ("", "tbb"):
    os.environ["NUMBA_THREADING_LAYER"] = "workqueue"

import anndata as ad
import scanpy as sc
from zerna_contracts.enums import ComputePreference
from pydantic import BaseModel, Field

from methods.base import MethodDefinition
from methods.dimensionality_reduction.neighbors_graph import (
    ensure_neighbors_graph,
    representation_used_label,
)


def _embedding_method_label(raw: str | None, fallback: str) -> str:
    x = (raw or fallback).strip().lower()
    return x if x in ("umap", "tsne") else fallback


class UMAPInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    n_components: int = Field(default=2, ge=2, le=3)
    n_neighbors: int = Field(default=15, ge=2)
    min_dist: float = Field(default=0.5, ge=0.0)
    use_rep: str = "X_pca"
    random_state: int = 0
    embedding_method_requested: str | None = Field(
        default=None,
        description="Pipeline embedding_method (umap|tsne) for provenance.",
    )


class EmbeddingMetrics(BaseModel):
    embedding_key: str
    method_requested: str
    method_executed: str
    representation_requested: str
    representation_used: str
    n_components: int
    min_dist: float | None = None
    perplexity: float | None = None
    n_neighbors_requested: int | None = None
    n_neighbors_used: int | None = None
    neighbors_reused: bool | None = None
    neighbors_recomputed: bool | None = None
    neighbor_graph_source: str | None = None


class EmbeddingOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    embedding_key: str
    metrics: EmbeddingMetrics


class TSNEInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    n_components: int = Field(default=2, ge=2, le=3)
    n_neighbors: int = Field(default=15, ge=2)
    perplexity: float = Field(default=30.0, gt=0.0)
    use_rep: str = "X_pca"
    random_state: int = 0
    embedding_method_requested: str | None = Field(
        default=None,
        description="Pipeline embedding_method (umap|tsne) for provenance.",
    )


class UMAPMethod(MethodDefinition):
    """UMAP 2D/3D embedding with reproducible random seed."""

    name = "umap_embedding"
    version = "1.1.0"
    compute_preference = ComputePreference.CPU_ONLY

    def input_schema(self):
        return UMAPInput

    def output_schema(self):
        return EmbeddingOutput

    def execute(self, input: UMAPInput, compute) -> EmbeddingOutput:
        adata = input.adata
        method_req = _embedding_method_label(input.embedding_method_requested, "umap")
        neighbors_reused, neighbors_recomputed, rep_used = ensure_neighbors_graph(
            adata,
            input.n_neighbors,
            input.use_rep,
            input.random_state,
            log_context="Embed step (UMAP)",
            pipeline_step="embedding_umap",
        )
        sc.tl.umap(
            adata,
            n_components=input.n_components,
            min_dist=input.min_dist,
            random_state=input.random_state,
        )
        neighbor_source = (
            "reused_compatible_gauss_graph" if neighbors_reused else "recomputed_gauss_graph"
        )
        adata.uns["zerna_embedding"] = {
            "method": "umap",
            "method_requested": method_req,
            "method_executed": "umap",
            "representation_requested": input.use_rep,
            "representation_used": rep_used,
            "n_components": int(input.n_components),
            "min_dist": float(input.min_dist),
            "n_neighbors_requested": int(input.n_neighbors),
            "n_neighbors_used": int(input.n_neighbors),
            "neighbors_reused": neighbors_reused,
            "neighbors_recomputed": neighbors_recomputed,
            "neighbor_graph_source": neighbor_source,
            "embedding_key_written": "X_umap",
            "use_rep": input.use_rep,
            "n_neighbors": int(input.n_neighbors),
        }
        metrics = EmbeddingMetrics(
            embedding_key="X_umap",
            method_requested=method_req,
            method_executed="umap",
            representation_requested=input.use_rep,
            representation_used=rep_used,
            n_components=int(input.n_components),
            min_dist=float(input.min_dist),
            n_neighbors_requested=int(input.n_neighbors),
            n_neighbors_used=int(input.n_neighbors),
            neighbors_reused=neighbors_reused,
            neighbors_recomputed=neighbors_recomputed,
            neighbor_graph_source=neighbor_source,
        )
        return EmbeddingOutput(adata=adata, embedding_key="X_umap", metrics=metrics)


class TSNEMethod(MethodDefinition):
    """t-SNE 2D/3D embedding with reproducible random seed."""

    name = "tsne_embedding"
    version = "1.1.0"
    compute_preference = ComputePreference.CPU_ONLY

    def input_schema(self):
        return TSNEInput

    def output_schema(self):
        return EmbeddingOutput

    def execute(self, input: TSNEInput, compute) -> EmbeddingOutput:
        adata = input.adata
        method_req = _embedding_method_label(input.embedding_method_requested, "tsne")
        rep = input.use_rep if input.use_rep in adata.obsm else None
        rep_used = representation_used_label(adata, input.use_rep)
        sc.tl.tsne(
            adata,
            n_pcs=None,
            use_rep=rep,
            perplexity=input.perplexity,
            n_jobs=1,
            random_state=input.random_state,
        )
        neighbor_source = "scanpy_tsne_use_rep_direct"
        adata.uns["zerna_embedding"] = {
            "method": "tsne",
            "method_requested": method_req,
            "method_executed": "tsne",
            "representation_requested": input.use_rep,
            "representation_used": rep_used,
            "n_components": int(input.n_components),
            "perplexity": float(input.perplexity),
            "embedding_key_written": "X_tsne",
            "neighbors_reused": False,
            "neighbors_recomputed": False,
            "n_neighbors_requested": int(input.n_neighbors),
            "n_neighbors_used": None,
            "neighbor_graph_source": neighbor_source,
            "use_rep": input.use_rep,
        }
        metrics = EmbeddingMetrics(
            embedding_key="X_tsne",
            method_requested=method_req,
            method_executed="tsne",
            representation_requested=input.use_rep,
            representation_used=rep_used,
            n_components=int(input.n_components),
            perplexity=float(input.perplexity),
            n_neighbors_requested=int(input.n_neighbors),
            n_neighbors_used=None,
            neighbors_reused=False,
            neighbors_recomputed=False,
            neighbor_graph_source=neighbor_source,
        )
        return EmbeddingOutput(adata=adata, embedding_key="X_tsne", metrics=metrics)
