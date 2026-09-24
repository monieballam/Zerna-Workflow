"""Differential expression utility functions.

Provides volcano plot data generation, gene ranking, and covariate-aware
analysis helpers.

# Feature: gap-analysis-and-verification
"""

from __future__ import annotations

import math
from typing import Any

from zerna_contracts.base import ZernaBaseModel

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class VolcanoPoint(ZernaBaseModel):
    """Single gene point in a volcano plot."""

    gene: str
    log2_fold_change: float
    neg_log10_pvalue: float


class VolcanoData(ZernaBaseModel):
    """Complete volcano plot dataset."""

    points: list[VolcanoPoint]
    significance_threshold: float = 1.3  # -log10(0.05)
    fold_change_threshold: float = 1.0


class RankedGene(ZernaBaseModel):
    """A gene with its ranking score."""

    gene: str
    score: float


class RankedGenes(ZernaBaseModel):
    """Sorted list of ranked genes."""

    genes: list[RankedGene]


class DEResult(ZernaBaseModel):
    """Single differential expression result for one gene."""

    gene: str
    log2_fold_change: float
    p_value: float
    adjusted_p_value: float | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def volcano_data(
    de_results: list[DEResult] | list[dict[str, Any]],
    significance_threshold: float = 1.3,
    fold_change_threshold: float = 1.0,
) -> VolcanoData:
    """Build volcano plot data from DE results.

    Parameters
    ----------
    de_results : list[DEResult] | list[dict]
        Each entry must have ``gene``, ``log2_fold_change``, and ``p_value``.
    significance_threshold : float
        -log10(p-value) threshold for significance line.
    fold_change_threshold : float
        Absolute log2 fold-change threshold.

    Returns
    -------
    VolcanoData
    """
    points: list[VolcanoPoint] = []
    for entry in de_results:
        if isinstance(entry, dict):
            entry = DEResult(**entry)
        p_val = max(entry.p_value, 1e-300)  # avoid log(0)
        neg_log10 = -math.log10(p_val)
        points.append(
            VolcanoPoint(
                gene=entry.gene,
                log2_fold_change=entry.log2_fold_change,
                neg_log10_pvalue=neg_log10,
            )
        )
    return VolcanoData(
        points=points,
        significance_threshold=significance_threshold,
        fold_change_threshold=fold_change_threshold,
    )


def rank_genes(
    de_results: list[DEResult] | list[dict[str, Any]],
) -> RankedGenes:
    """Rank genes by a composite score (|log2FC| * -log10(p)).

    The returned list is sorted in descending order by score.

    Parameters
    ----------
    de_results : list[DEResult] | list[dict]
        Each entry must have ``gene``, ``log2_fold_change``, and ``p_value``.

    Returns
    -------
    RankedGenes
    """
    scored: list[RankedGene] = []
    for entry in de_results:
        if isinstance(entry, dict):
            entry = DEResult(**entry)
        p_val = max(entry.p_value, 1e-300)
        score = abs(entry.log2_fold_change) * (-math.log10(p_val))
        scored.append(RankedGene(gene=entry.gene, score=score))

    scored.sort(key=lambda g: g.score, reverse=True)
    return RankedGenes(genes=scored)
