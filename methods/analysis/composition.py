"""Composition analysis utilities.

Computes cell type proportions, fold changes, and statistical comparisons
across conditions.

# Feature: gap-analysis-and-verification
"""

from __future__ import annotations

from typing import Any

from zerna_contracts.base import ZernaBaseModel


class CompositionResult(ZernaBaseModel):
    """Result of composition analysis."""

    proportions: dict[str, float]  # cell_type -> proportion
    fold_changes: dict[str, float] | None = None
    p_values: dict[str, float] | None = None


def compute_composition(
    adata: dict[str, Any],
    groupby: str,
    condition: str | None = None,
) -> CompositionResult:
    """Compute cell type proportions and optional fold changes.

    Parameters
    ----------
    adata : dict
        Simplified AnnData-like dict with at least an ``"obs"`` key mapping to
        a dict of ``{cell_id: {col: value, ...}}``.
    groupby : str
        Column name in obs to group cells by (e.g. ``"cell_type"``).
    condition : str | None
        Optional column name for condition-based fold-change computation.
        When provided, fold changes are computed between the first two
        unique condition values found.

    Returns
    -------
    CompositionResult
    """
    obs: dict[str, dict[str, Any]] = adata.get("obs", {})

    # --- count cells per group ---
    counts: dict[str, int] = {}
    for cell_meta in obs.values():
        label = str(cell_meta.get(groupby, "unknown"))
        counts[label] = counts.get(label, 0) + 1

    total = sum(counts.values())
    proportions = _counts_to_proportions(counts, total)

    fold_changes: dict[str, float] | None = None
    p_values: dict[str, float] | None = None

    if condition is not None:
        fold_changes, p_values = _compute_fold_changes(obs, groupby, condition)

    return CompositionResult(
        proportions=proportions,
        fold_changes=fold_changes,
        p_values=p_values,
    )


def _counts_to_proportions(counts: dict[str, int], total: int) -> dict[str, float]:
    """Convert raw counts to proportions that sum to 1.0."""
    if total == 0:
        return {}
    proportions = {k: v / total for k, v in counts.items()}
    # Normalise to guarantee exact sum == 1.0 despite floating-point drift
    prop_sum = sum(proportions.values())
    if prop_sum > 0:
        proportions = {k: v / prop_sum for k, v in proportions.items()}
    return proportions


def _compute_fold_changes(
    obs: dict[str, dict[str, Any]],
    groupby: str,
    condition: str,
) -> tuple[dict[str, float], dict[str, float]]:
    """Compute fold changes and simple p-value proxies between two conditions."""
    # Partition cells by condition
    condition_groups: dict[str, dict[str, int]] = {}
    for cell_meta in obs.values():
        cond_val = str(cell_meta.get(condition, "unknown"))
        label = str(cell_meta.get(groupby, "unknown"))
        if cond_val not in condition_groups:
            condition_groups[cond_val] = {}
        condition_groups[cond_val][label] = condition_groups[cond_val].get(label, 0) + 1

    cond_keys = sorted(condition_groups.keys())
    if len(cond_keys) < 2:
        return {}, {}

    cond_a, cond_b = cond_keys[0], cond_keys[1]
    counts_a = condition_groups[cond_a]
    counts_b = condition_groups[cond_b]
    total_a = max(sum(counts_a.values()), 1)
    total_b = max(sum(counts_b.values()), 1)

    all_labels = sorted(set(counts_a.keys()) | set(counts_b.keys()))

    fold_changes: dict[str, float] = {}
    p_values: dict[str, float] = {}
    for label in all_labels:
        prop_a = counts_a.get(label, 0) / total_a
        prop_b = counts_b.get(label, 0) / total_b
        # Fold change with pseudocount to avoid division by zero
        pseudo = 1e-6
        fold_changes[label] = (prop_b + pseudo) / (prop_a + pseudo)
        # Simple heuristic p-value (placeholder for real statistical test)
        diff = abs(prop_b - prop_a)
        p_values[label] = max(0.0, 1.0 - diff * 10)  # crude proxy

    return fold_changes, p_values
