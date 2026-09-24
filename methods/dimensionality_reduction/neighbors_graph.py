"""Shared sklearn + Gaussian neighbor graph construction for clustering and UMAP.

Clustering (Leiden/Louvain) and UMAP embedding both call ``ensure_neighbors_graph`` so:

- **Validity** is a single implementation: ``existing_neighbors_compatible`` (gauss method,
  ``n_neighbors``, Scanpy ``use_rep``, ``random_state`` when stored).
- **Provenance** uses one ``adata.uns["zerna_neighbors"]`` schema; each call refreshes it so the
  next step sees accurate reuse/recompute flags for *its* requested parameters.
"""

from __future__ import annotations

import logging

import anndata as ad
import scanpy as sc

logger = logging.getLogger(__name__)

NEIGHBORS_TRANSFORMER = "sklearn"
NEIGHBORS_CONNECTIVITY_METHOD = "gauss"

# Bumped only if zerna_neighbors keys or compatibility semantics change.
NEIGHBOR_GRAPH_PROVENANCE_SCHEMA_VERSION = 1

# Identifier for the validation rules in existing_neighbors_compatible (documentation + tooling).
NEIGHBOR_GRAPH_VALIDATION_CONTRACT_ID = "gauss_sklearn_knn_v1"


def scanpy_use_rep_argument(adata: ad.AnnData, requested: str) -> str | None:
    """Argument for sc.pp.neighbors(use_rep=...): obsm key or None to use adata.X."""
    return requested if requested in adata.obsm else None


def representation_used_label(adata: ad.AnnData, requested: str) -> str:
    """Human-readable representation used for the kNN graph."""
    return requested if requested in adata.obsm else "X"


def existing_neighbors_compatible(
    adata: ad.AnnData,
    *,
    n_neighbors: int,
    use_rep_arg: str | None,
    random_state: int,
) -> bool:
    """True if uns['neighbors'] matches gauss connectivity and the same kNN settings."""
    nb = adata.uns.get("neighbors")
    if not isinstance(nb, dict):
        return False
    p = nb.get("params")
    if not isinstance(p, dict):
        return False
    if int(p.get("n_neighbors", -1)) != int(n_neighbors):
        return False
    if p.get("method") != NEIGHBORS_CONNECTIVITY_METHOD:
        return False
    rs = p.get("random_state")
    if rs is not None and int(rs) != int(random_state):
        return False
    stored = p.get("use_rep")
    if use_rep_arg is None:
        return stored is None
    return stored == use_rep_arg


def write_zerna_neighbors(
    adata: ad.AnnData,
    *,
    representation_requested: str,
    representation_used: str,
    n_neighbors: int,
    graph_reused: bool,
    graph_recomputed: bool,
    last_modified_by_pipeline_step: str,
) -> None:
    adata.uns["zerna_neighbors"] = {
        "neighbor_graph_provenance_schema_version": NEIGHBOR_GRAPH_PROVENANCE_SCHEMA_VERSION,
        "neighbor_graph_validation_contract_id": NEIGHBOR_GRAPH_VALIDATION_CONTRACT_ID,
        "last_modified_by_pipeline_step": last_modified_by_pipeline_step,
        "representation_requested_for_neighbors": representation_requested,
        "representation_used_for_neighbors": representation_used,
        "n_neighbors_used_for_neighbors": int(n_neighbors),
        "transformer": NEIGHBORS_TRANSFORMER,
        "connectivity_method": NEIGHBORS_CONNECTIVITY_METHOD,
        "graph_reused": graph_reused,
        "graph_recomputed": graph_recomputed,
    }


def ensure_neighbors_graph(
    adata: ad.AnnData,
    n_neighbors: int,
    use_rep_requested: str,
    random_state: int,
    *,
    log_context: str = "Neighbors",
    pipeline_step: str = "unspecified",
) -> tuple[bool, bool, str]:
    """
    Build or reuse the neighbor graph (sklearn kNN + gaussian connectivities).

    ``pipeline_step`` should be ``\"clustering\"`` or ``\"embedding_umap\"`` so ``zerna_neighbors``
    records which step last validated/refreshed provenance (single contract for both).

    Returns (neighbors_reused, neighbors_recomputed, representation_used).
    """
    use_rep_arg = scanpy_use_rep_argument(adata, use_rep_requested)
    rep_used = representation_used_label(adata, use_rep_requested)

    if existing_neighbors_compatible(
        adata,
        n_neighbors=n_neighbors,
        use_rep_arg=use_rep_arg,
        random_state=random_state,
    ):
        write_zerna_neighbors(
            adata,
            representation_requested=use_rep_requested,
            representation_used=rep_used,
            n_neighbors=n_neighbors,
            graph_reused=True,
            graph_recomputed=False,
            last_modified_by_pipeline_step=pipeline_step,
        )
        logger.info(
            "%s: reusing existing neighbors graph (n_neighbors=%s use_rep=%s rep_used=%s)",
            log_context,
            n_neighbors,
            use_rep_arg,
            rep_used,
        )
        return True, False, rep_used

    sc.pp.neighbors(
        adata,
        n_neighbors=n_neighbors,
        use_rep=use_rep_arg,
        random_state=random_state,
        transformer=NEIGHBORS_TRANSFORMER,
        method=NEIGHBORS_CONNECTIVITY_METHOD,
    )
    write_zerna_neighbors(
        adata,
        representation_requested=use_rep_requested,
        representation_used=rep_used,
        n_neighbors=n_neighbors,
        graph_reused=False,
        graph_recomputed=True,
        last_modified_by_pipeline_step=pipeline_step,
    )
    logger.info(
        "%s: recomputed neighbors graph (n_neighbors=%s use_rep=%s rep_used=%s)",
        log_context,
        n_neighbors,
        use_rep_arg,
        rep_used,
    )
    return False, True, rep_used
