"""Pathway activity scoring module.

Computes pathway activity scores using a simple gene-set-based approach
(mean expression of pathway member genes). In production this would delegate
to decoupler or equivalent backends.

# Feature: gap-analysis-and-verification
"""

from __future__ import annotations

from typing import Any

from zerna_contracts.base import ZernaBaseModel

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class PathwayScore(ZernaBaseModel):
    """Activity score for a single pathway."""

    pathway: str
    score: float
    member_genes: list[str]
    genes_found: list[str]


class PathwayScores(ZernaBaseModel):
    """Collection of pathway activity scores."""

    scores: list[PathwayScore]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_pathways(
    adata: dict[str, Any],
    pathway_db: dict[str, list[str]],
) -> PathwayScores:
    """Score pathway activities from expression data.

    Parameters
    ----------
    adata : dict
        Simplified AnnData-like dict.  Expected keys:

        * ``"X"`` – dict mapping ``cell_id`` to ``{gene: expression}``
        * Alternatively ``"var_names"`` (list[str]) and ``"X_matrix"``
          (list of lists) can be provided.
    pathway_db : dict[str, list[str]]
        Mapping of pathway name to member gene symbols.

    Returns
    -------
    PathwayScores
    """
    expression = _extract_expression(adata)
    results: list[PathwayScore] = []

    for pathway_name, member_genes in pathway_db.items():
        genes_found: list[str] = []
        total_score = 0.0
        n_cells = 0

        for _cell_id, cell_expr in expression.items():
            cell_sum = 0.0
            cell_count = 0
            for gene in member_genes:
                if gene in cell_expr:
                    cell_sum += cell_expr[gene]
                    cell_count += 1
                    if gene not in genes_found:
                        genes_found.append(gene)
            if cell_count > 0:
                total_score += cell_sum / cell_count
            n_cells += 1

        avg_score = total_score / max(n_cells, 1)
        results.append(
            PathwayScore(
                pathway=pathway_name,
                score=avg_score,
                member_genes=member_genes,
                genes_found=genes_found,
            )
        )

    return PathwayScores(scores=results)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_expression(adata: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Extract a cell_id -> {gene: value} mapping from the adata dict."""
    if "X" in adata and isinstance(adata["X"], dict):
        return adata["X"]

    # Fallback: var_names + X_matrix
    var_names: list[str] = adata.get("var_names", [])
    x_matrix: list[list[float]] = adata.get("X_matrix", [])
    obs_names: list[str] = adata.get("obs_names", [f"cell_{i}" for i in range(len(x_matrix))])

    result: dict[str, dict[str, float]] = {}
    for i, row in enumerate(x_matrix):
        cell_id = obs_names[i] if i < len(obs_names) else f"cell_{i}"
        result[cell_id] = {var_names[j]: row[j] for j in range(min(len(var_names), len(row)))}
    return result
