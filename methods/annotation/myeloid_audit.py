"""Myeloid calibration output and subtyping audit.

# Feature: gap-analysis-and-verification

Generates per-subtype confidence distributions and threshold recommendations.
Compares assigned subtypes against reference panels.
Produces structured report with precision, recall, confusion metrics.

**Validates: Requirements 20.1, 20.2, 20.3**
"""

from __future__ import annotations

import logging
from typing import Any

from zerna_contracts.base import ZernaBaseModel
from pydantic import Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class SubtypeMetrics(ZernaBaseModel):
    """Per-subtype precision, recall, F1, and confusion counts."""

    precision: float = Field(ge=0.0, le=1.0, description="Precision for this subtype")
    recall: float = Field(ge=0.0, le=1.0, description="Recall for this subtype")
    f1: float = Field(ge=0.0, le=1.0, description="F1 score for this subtype")
    confusion_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Confusion counts: {predicted_label: count}",
    )


class MyeloidAuditReport(ZernaBaseModel):
    """Full myeloid audit report with metrics, distributions, and thresholds."""

    subtype_metrics: dict[str, SubtypeMetrics] = Field(
        description="Per-subtype precision/recall/F1/confusion"
    )
    confidence_distributions: dict[str, list[float]] = Field(
        description="Per-subtype confidence score distributions"
    )
    threshold_recommendations: dict[str, float] = Field(
        description="Per-subtype recommended confidence thresholds"
    )


# ---------------------------------------------------------------------------
# Calibration helpers
# ---------------------------------------------------------------------------


def _compute_confidence_distributions(
    annotations: dict[str, dict[str, Any]],
) -> dict[str, list[float]]:
    """Build per-subtype confidence score distributions.

    Args:
        annotations: cell_id -> {"subtype": str, "confidence": float, ...}

    Returns:
        subtype -> sorted list of confidence scores.
    """
    distributions: dict[str, list[float]] = {}
    for cell_data in annotations.values():
        subtype = cell_data.get("subtype", "")
        confidence = float(cell_data.get("confidence", 0.0))
        distributions.setdefault(subtype, []).append(confidence)

    # Sort each distribution for easier downstream analysis
    for subtype in distributions:
        distributions[subtype].sort()

    return distributions


def _compute_threshold_recommendations(
    distributions: dict[str, list[float]],
    percentile: float = 0.5,
) -> dict[str, float]:
    """Recommend a confidence threshold per subtype.

    Uses the given percentile of the confidence distribution as the
    recommended threshold. Defaults to the median (0.5).
    """
    thresholds: dict[str, float] = {}
    for subtype, scores in distributions.items():
        if not scores:
            thresholds[subtype] = 0.0
            continue
        idx = int(percentile * (len(scores) - 1))
        idx = max(0, min(idx, len(scores) - 1))
        thresholds[subtype] = scores[idx]
    return thresholds


def calibrate(
    annotations: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[float]], dict[str, float]]:
    """Generate calibration output: confidence distributions + threshold recommendations.

    Args:
        annotations: cell_id -> {"subtype": str, "confidence": float, ...}

    Returns:
        Tuple of (confidence_distributions, threshold_recommendations).
    """
    distributions = _compute_confidence_distributions(annotations)
    thresholds = _compute_threshold_recommendations(distributions)
    return distributions, thresholds


# ---------------------------------------------------------------------------
# Audit logic
# ---------------------------------------------------------------------------


def _compute_subtype_metrics(
    annotations: dict[str, dict[str, Any]],
    reference_panel: dict[str, str],
) -> dict[str, SubtypeMetrics]:
    """Compute precision, recall, F1, and confusion counts per subtype.

    Args:
        annotations: cell_id -> {"subtype": str, ...}
        reference_panel: cell_id -> reference_subtype (ground truth).

    Returns:
        subtype -> SubtypeMetrics for every subtype present in annotations
        or reference_panel.
    """
    # Collect all subtypes from both annotations and reference
    all_subtypes: set[str] = set()
    predicted: dict[str, str] = {}
    for cell_id, cell_data in annotations.items():
        st = cell_data.get("subtype", "unknown")
        predicted[cell_id] = st
        all_subtypes.add(st)

    for st in reference_panel.values():
        all_subtypes.add(st)

    # Compute per-subtype TP, FP, FN and confusion counts
    tp: dict[str, int] = dict.fromkeys(all_subtypes, 0)
    fp: dict[str, int] = dict.fromkeys(all_subtypes, 0)
    fn: dict[str, int] = dict.fromkeys(all_subtypes, 0)
    confusion: dict[str, dict[str, int]] = {s: {} for s in all_subtypes}

    # Only evaluate cells present in both predicted and reference
    common_cells = set(predicted.keys()) & set(reference_panel.keys())

    for cell_id in common_cells:
        pred = predicted[cell_id]
        ref = reference_panel[cell_id]

        if pred == ref:
            tp[pred] = tp.get(pred, 0) + 1
        else:
            fp[pred] = fp.get(pred, 0) + 1
            fn[ref] = fn.get(ref, 0) + 1
            # Record confusion: for the reference subtype, count what it was predicted as
            confusion[ref][pred] = confusion[ref].get(pred, 0) + 1

    metrics: dict[str, SubtypeMetrics] = {}
    for subtype in all_subtypes:
        t = tp.get(subtype, 0)
        f_p = fp.get(subtype, 0)
        f_n = fn.get(subtype, 0)

        precision = t / (t + f_p) if (t + f_p) > 0 else 0.0
        recall = t / (t + f_n) if (t + f_n) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        metrics[subtype] = SubtypeMetrics(
            precision=precision,
            recall=recall,
            f1=f1,
            confusion_counts=confusion.get(subtype, {}),
        )

    return metrics


def audit(
    annotations: dict[str, dict[str, Any]],
    reference_panel: dict[str, str],
) -> MyeloidAuditReport:
    """Run a full myeloid subtyping audit.

    Compares assigned subtypes against a reference panel and produces a
    structured report with per-subtype precision, recall, confusion metrics,
    confidence distributions, and threshold recommendations.

    Args:
        annotations: cell_id -> {"subtype": str, "confidence": float, ...}
        reference_panel: cell_id -> reference_subtype (ground truth).

    Returns:
        MyeloidAuditReport with metrics, distributions, and thresholds.
    """
    distributions, thresholds = calibrate(annotations)
    subtype_metrics = _compute_subtype_metrics(annotations, reference_panel)

    # Ensure every subtype from annotations has entries in all output dicts
    annotation_subtypes = {
        cell_data.get("subtype", "unknown") for cell_data in annotations.values()
    }
    for st in annotation_subtypes:
        if st not in distributions:
            distributions[st] = []
        if st not in thresholds:
            thresholds[st] = 0.0
        if st not in subtype_metrics:
            subtype_metrics[st] = SubtypeMetrics(
                precision=0.0, recall=0.0, f1=0.0, confusion_counts={}
            )

    return MyeloidAuditReport(
        subtype_metrics=subtype_metrics,
        confidence_distributions=distributions,
        threshold_recommendations=thresholds,
    )
