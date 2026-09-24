"""Clustering methods (Leiden, Louvain) for single-cell RNA-seq data."""

import logging
import os
from typing import Literal

# Must run before `import scanpy` — Numba picks threading layer on first use.
_numba_tl = os.environ.get("NUMBA_THREADING_LAYER", "").strip().lower()
if _numba_tl in ("", "tbb"):
    os.environ["NUMBA_THREADING_LAYER"] = "workqueue"

import anndata as ad
import scanpy as sc
from zerna_contracts.enums import ComputePreference
from pydantic import BaseModel, Field

from methods.base import MethodDefinition
from methods.dimensionality_reduction.neighbors_graph import (
    NEIGHBORS_CONNECTIVITY_METHOD,
    NEIGHBORS_TRANSFORMER,
    ensure_neighbors_graph,
    scanpy_use_rep_argument,
)

logger = logging.getLogger(__name__)


class ClusteringInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    resolution: float = Field(default=1.0, gt=0.0)
    n_neighbors: int = Field(default=15, ge=2)
    use_rep: str = "X_pca"
    random_state: int = 0
    clustering_method_requested: str | None = Field(
        default=None,
        description="Pipeline parameter clustering_method (leiden|louvain) for provenance.",
    )


class ClusteringMetrics(BaseModel):
    n_clusters: int
    cluster_sizes: list[int]
    method: str
    method_requested: str
    method_executed: str
    representation_requested: str
    representation_used: str
    n_neighbors_requested: int
    n_neighbors_used: int
    neighbors_reused: bool
    neighbors_recomputed: bool
    cluster_key_written: str
    resolution: float
    leiden_flavor: str | None = None


class ClusteringOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    metrics: ClusteringMetrics


def _leiden_flavor() -> str:
    """Prefer leidenalg (avoids some igraph+Numba/TBB issues); fall back to igraph."""
    try:
        import leidenalg  # noqa: F401

        return "leidenalg"
    except ImportError:
        return "igraph"


def _method_requested_label(algorithm: str, input: ClusteringInput) -> str:
    raw = (input.clustering_method_requested or algorithm).strip().lower()
    return raw if raw in ("leiden", "louvain") else algorithm


def _zerna_clustering_block(
    *,
    algorithm: Literal["leiden", "louvain"],
    input: ClusteringInput,
    rep_used: str,
    neighbors_reused: bool,
    neighbors_recomputed: bool,
    cluster_key: str,
    n_clusters: int,
    cluster_sizes: list[int],
    leiden_flavor: str | None,
    nb_layer: str,
) -> dict:
    req = _method_requested_label(algorithm, input)
    return {
        "method": algorithm,
        "method_requested": req,
        "method_executed": algorithm,
        "representation_requested": input.use_rep,
        "representation_used": rep_used,
        "n_neighbors_requested": int(input.n_neighbors),
        "n_neighbors_used": int(input.n_neighbors),
        "neighbors_reused": neighbors_reused,
        "neighbors_recomputed": neighbors_recomputed,
        "cluster_key_written": cluster_key,
        "resolution": float(input.resolution),
        "n_clusters": int(n_clusters),
        "cluster_sizes": [int(x) for x in cluster_sizes],
        "leiden_flavor": leiden_flavor,
        "neighbors_transformer": NEIGHBORS_TRANSFORMER,
        "neighbors_connectivity": NEIGHBORS_CONNECTIVITY_METHOD,
        "numba_threading_layer": nb_layer or None,
        "use_rep": input.use_rep,
        "n_neighbors": int(input.n_neighbors),
    }


class LeidenMethod(MethodDefinition):
    """Leiden community detection clustering."""

    name = "leiden_clustering"
    version = "1.1.0"
    compute_preference = ComputePreference.CPU_ONLY

    def input_schema(self):
        return ClusteringInput

    def output_schema(self):
        return ClusteringOutput

    def execute(self, input: ClusteringInput, compute) -> ClusteringOutput:
        adata = input.adata
        flavor = _leiden_flavor()
        rep_eff_arg = scanpy_use_rep_argument(adata, input.use_rep)
        nb_layer = os.environ.get("NUMBA_THREADING_LAYER", "")
        logger.info(
            "Cluster step: algorithm=leiden flavor=%s resolution=%s use_rep=%s effective_rep=%s "
            "n_neighbors=%s random_state=%s neighbors_knn=sklearn neighbors_connectivity=gauss "
            "NUMBA_THREADING_LAYER=%s",
            flavor,
            input.resolution,
            input.use_rep,
            rep_eff_arg,
            input.n_neighbors,
            input.random_state,
            nb_layer or "(unset)",
        )
        try:
            neighbors_reused, neighbors_recomputed, rep_used = ensure_neighbors_graph(
                adata,
                input.n_neighbors,
                input.use_rep,
                input.random_state,
                log_context="Cluster step",
                pipeline_step="clustering",
            )
            sc.tl.leiden(
                adata,
                resolution=input.resolution,
                random_state=input.random_state,
                flavor=flavor,
                n_iterations=2,
                directed=False,
            )
        except Exception:
            logger.exception(
                "Cluster step failed: algorithm=leiden flavor=%s resolution=%s use_rep=%s "
                "n_neighbors=%s NUMBA_THREADING_LAYER=%s",
                flavor,
                input.resolution,
                input.use_rep,
                input.n_neighbors,
                nb_layer or "(unset)",
            )
            raise
        cluster_col = adata.obs["leiden"]
        sizes = cluster_col.value_counts().sort_index().tolist()
        n_clust = int(cluster_col.nunique())
        adata.uns["zerna_clustering"] = _zerna_clustering_block(
            algorithm="leiden",
            input=input,
            rep_used=rep_used,
            neighbors_reused=neighbors_reused,
            neighbors_recomputed=neighbors_recomputed,
            cluster_key="leiden",
            n_clusters=n_clust,
            cluster_sizes=sizes,
            leiden_flavor=flavor,
            nb_layer=nb_layer,
        )
        req_m = _method_requested_label("leiden", input)
        return ClusteringOutput(
            adata=adata,
            metrics=ClusteringMetrics(
                n_clusters=n_clust,
                cluster_sizes=sizes,
                method="leiden",
                method_requested=req_m,
                method_executed="leiden",
                representation_requested=input.use_rep,
                representation_used=rep_used,
                n_neighbors_requested=int(input.n_neighbors),
                n_neighbors_used=int(input.n_neighbors),
                neighbors_reused=neighbors_reused,
                neighbors_recomputed=neighbors_recomputed,
                cluster_key_written="leiden",
                resolution=float(input.resolution),
                leiden_flavor=flavor,
            ),
        )


class LouvainMethod(MethodDefinition):
    """Louvain community detection clustering."""

    name = "louvain_clustering"
    version = "1.1.0"
    compute_preference = ComputePreference.CPU_ONLY

    def input_schema(self):
        return ClusteringInput

    def output_schema(self):
        return ClusteringOutput

    def execute(self, input: ClusteringInput, compute) -> ClusteringOutput:
        adata = input.adata
        rep_eff_arg = scanpy_use_rep_argument(adata, input.use_rep)
        nb_layer = os.environ.get("NUMBA_THREADING_LAYER", "")
        logger.info(
            "Cluster step: algorithm=louvain resolution=%s use_rep=%s effective_rep=%s "
            "n_neighbors=%s random_state=%s neighbors_knn=sklearn neighbors_connectivity=gauss "
            "NUMBA_THREADING_LAYER=%s",
            input.resolution,
            input.use_rep,
            rep_eff_arg,
            input.n_neighbors,
            input.random_state,
            nb_layer or "(unset)",
        )
        try:
            neighbors_reused, neighbors_recomputed, rep_used = ensure_neighbors_graph(
                adata,
                input.n_neighbors,
                input.use_rep,
                input.random_state,
                log_context="Cluster step",
                pipeline_step="clustering",
            )
            sc.tl.louvain(
                adata, resolution=input.resolution, random_state=input.random_state, flavor="igraph"
            )
        except Exception:
            logger.exception(
                "Cluster step failed: algorithm=louvain resolution=%s use_rep=%s n_neighbors=%s "
                "NUMBA_THREADING_LAYER=%s",
                input.resolution,
                input.use_rep,
                input.n_neighbors,
                nb_layer or "(unset)",
            )
            raise
        cluster_col = adata.obs["louvain"]
        sizes = cluster_col.value_counts().sort_index().tolist()
        n_clust = int(cluster_col.nunique())
        adata.uns["zerna_clustering"] = _zerna_clustering_block(
            algorithm="louvain",
            input=input,
            rep_used=rep_used,
            neighbors_reused=neighbors_reused,
            neighbors_recomputed=neighbors_recomputed,
            cluster_key="louvain",
            n_clusters=n_clust,
            cluster_sizes=sizes,
            leiden_flavor=None,
            nb_layer=nb_layer,
        )
        req_m = _method_requested_label("louvain", input)
        return ClusteringOutput(
            adata=adata,
            metrics=ClusteringMetrics(
                n_clusters=n_clust,
                cluster_sizes=sizes,
                method="louvain",
                method_requested=req_m,
                method_executed="louvain",
                representation_requested=input.use_rep,
                representation_used=rep_used,
                n_neighbors_requested=int(input.n_neighbors),
                n_neighbors_used=int(input.n_neighbors),
                neighbors_reused=neighbors_reused,
                neighbors_recomputed=neighbors_recomputed,
                cluster_key_written="louvain",
                resolution=float(input.resolution),
                leiden_flavor=None,
            ),
        )
