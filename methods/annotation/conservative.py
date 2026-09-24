"""Conservative, auditable cluster annotation utilities.

Builds cluster-level calls from marker evidence plus optional reference-model
consensus, with explicit abstention and ambiguity handling. Also provides a
benchmark helper for comparing predicted labels against a reference column.
"""

from __future__ import annotations

from typing import Any, Literal

from zerna_contracts.base import ZernaBaseModel
from pydantic import Field

from methods.annotation.guardrails import normalize_label
from methods.annotation.zerna_index import lookup as lookup_zerna

_POSITIVE_TIER_WEIGHTS: dict[str, float] = {
    "core": 1.0,
    "high": 0.75,
    "medium": 0.5,
    "all": 0.25,
}
_NEGATIVE_TIER_WEIGHTS: dict[str, float] = {
    "exclude": 1.0,
    "soft_exclude": 0.5,
}
_ABSTAIN_LABELS = {"unknown", "ambiguous", "unassigned", "unresolved"}


class ConservativeThresholds(ZernaBaseModel):
    """Threshold bundle used by the conservative decision rule."""

    min_marker_overlap: int = Field(default=2, ge=1)
    min_marker_score: float = Field(default=0.45, ge=0.0, le=1.0)
    min_consensus_fraction: float = Field(default=0.5, ge=0.0, le=1.0)
    min_mean_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    min_composite_score: float = Field(default=0.55, ge=0.0, le=1.0)
    min_winning_margin: float = Field(default=0.1, ge=0.0, le=1.0)
    lineage_min_score: float = Field(default=0.45, ge=0.0, le=1.0)
    lineage_min_margin: float = Field(default=0.08, ge=0.0, le=1.0)
    max_negative_markers: int = Field(default=1, ge=0)
    allow_lineage_fallback: bool = True


class ConservativeCandidateEvidence(ZernaBaseModel):
    """Structured evidence for one candidate label within a cluster."""

    label: str
    normalized_label: str
    lineage: str
    positive_markers: list[str] = Field(default_factory=list)
    negative_markers: list[str] = Field(default_factory=list)
    marker_overlap: int = Field(default=0, ge=0)
    negative_overlap: int = Field(default=0, ge=0)
    marker_score: float = Field(default=0.0, ge=0.0, le=1.0)
    consensus_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    consensus_mean_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    consensus_score: float = Field(default=0.0, ge=0.0, le=1.0)
    lineage_consensus_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    prior_score: float = Field(default=0.0, ge=0.0, le=1.0)
    composite_score: float = Field(default=0.0, ge=0.0, le=1.0)
    passes_marker_gate: bool = False
    passes_acceptance_gate: bool = False


class ConservativeClusterCall(ZernaBaseModel):
    """Final cluster-level decision and full audit context."""

    cluster_id: str
    n_cells: int = Field(default=0, ge=0)
    status: Literal["accepted", "lineage_only", "ambiguous", "abstained"]
    final_label: str
    final_level: Literal["cell_type", "lineage", "unknown"]
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    uncertainty: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence_bucket: Literal["low", "medium", "high"]
    reason: str
    thresholds: ConservativeThresholds
    cluster_markers: list[str] = Field(default_factory=list)
    candidates: list[ConservativeCandidateEvidence] = Field(default_factory=list)
    lineage_scores: dict[str, float] = Field(default_factory=dict)
    consensus_summary: dict[str, Any] = Field(default_factory=dict)
    prior_summary: dict[str, Any] = Field(default_factory=dict)


class BenchmarkLabelMetrics(ZernaBaseModel):
    """Per-reference-label benchmark metrics."""

    support: int = Field(default=0, ge=0)
    covered: int = Field(default=0, ge=0)
    abstained: int = Field(default=0, ge=0)
    precision: float = Field(default=0.0, ge=0.0, le=1.0)
    recall: float = Field(default=0.0, ge=0.0, le=1.0)
    f1: float = Field(default=0.0, ge=0.0, le=1.0)
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)


class AnnotationBenchmarkReport(ZernaBaseModel):
    """Overall benchmark report for an annotation run."""

    reference_key: str
    total_cells: int = Field(default=0, ge=0)
    evaluated_cells: int = Field(default=0, ge=0)
    covered_cells: int = Field(default=0, ge=0)
    abstained_cells: int = Field(default=0, ge=0)
    lineage_consistent_cells: int = Field(default=0, ge=0)
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    overall_accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    accuracy_on_covered: float = Field(default=0.0, ge=0.0, le=1.0)
    lineage_consistent_accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    lineage_consistent_accuracy_on_covered: float = Field(default=0.0, ge=0.0, le=1.0)
    macro_f1: float = Field(default=0.0, ge=0.0, le=1.0)
    balanced_accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    per_label: dict[str, BenchmarkLabelMetrics] = Field(default_factory=dict)
    confusion_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _bucket(confidence: float) -> Literal["low", "medium", "high"]:
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"


def _normalize_gene_set(genes: list[str] | None) -> set[str]:
    if not genes:
        return set()
    return {str(gene).strip().upper() for gene in genes if str(gene).strip()}


def _normalize_label_key(label: str) -> str:
    return "".join(ch for ch in str(label).lower() if ch.isalnum())


def _infer_lineage(label: str) -> str:
    normalized = normalize_label(str(label).strip() or "Unknown")
    entry = lookup_zerna(normalized) or lookup_zerna(str(label))
    if entry is not None:
        path = entry.hierarchy_path
        if "Lymphocyte" in path:
            return "Lymphoid"
        if "Myeloid cell" in path:
            return "Myeloid"
        if "Stromal cell" in path:
            return "Stromal"
        if "Epithelial cell" in path:
            return "Epithelial"
    lowered = normalized.lower()
    if lowered in _ABSTAIN_LABELS:
        return "Unknown"
    if lowered in {"lymphoid", "myeloid", "stromal", "epithelial", "immune"}:
        return normalize_label(normalized)
    if any(token in lowered for token in ("t cell", "b cell", "nk cell", "lymph", "plasma")):
        return "Lymphoid"
    if any(
        token in lowered
        for token in ("monocyte", "macrophage", "dendritic", "neutrophil", "mast", "myeloid")
    ):
        return "Myeloid"
    if any(
        token in lowered
        for token in ("fibroblast", "stromal", "pericyte", "smooth muscle", "endothelial")
    ):
        return "Stromal"
    if "epithelial" in lowered:
        return "Epithelial"
    return "Unknown"


def _resolve_prior_score(label: str, prior: dict[str, float]) -> float:
    candidate_key = _normalize_label_key(label)
    best = 0.0
    for prior_label, raw_score in prior.items():
        prior_key = _normalize_label_key(prior_label)
        if not prior_key:
            continue
        if candidate_key == prior_key or candidate_key in prior_key or prior_key in candidate_key:
            best = max(best, _clamp(float(raw_score)))
    return best


def _summarize_reference_consensus(
    cluster_labels: list[str],
    cluster_confidences: list[float],
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    total = len(cluster_labels)
    if total == 0:
        return {}, {}

    label_counts: dict[str, int] = {}
    label_confidence_sums: dict[str, float] = {}
    lineage_counts: dict[str, int] = {}
    for raw_label, confidence in zip(cluster_labels, cluster_confidences, strict=False):
        normalized = normalize_label(str(raw_label).strip() or "Unknown")
        label_counts[normalized] = label_counts.get(normalized, 0) + 1
        label_confidence_sums[normalized] = label_confidence_sums.get(normalized, 0.0) + _clamp(
            float(confidence)
        )
        lineage = _infer_lineage(normalized)
        lineage_counts[lineage] = lineage_counts.get(lineage, 0) + 1

    summary: dict[str, dict[str, float]] = {}
    for label, count in label_counts.items():
        summary[label] = {
            "fraction": count / total,
            "mean_confidence": (label_confidence_sums[label] / count if count > 0 else 0.0),
        }

    lineage_summary = {
        lineage: count / total for lineage, count in lineage_counts.items() if lineage != "Unknown"
    }
    return summary, lineage_summary


def _candidate_from_marker_pack(
    label: str,
    tier_map: dict[str, list[str]],
    *,
    cluster_markers: list[str],
    consensus_summary: dict[str, dict[str, float]],
    lineage_consensus: dict[str, float],
    prior: dict[str, float],
    thresholds: ConservativeThresholds,
) -> ConservativeCandidateEvidence:
    cluster_marker_set = _normalize_gene_set(cluster_markers)
    positive_hits: set[str] = set()
    negative_hits: set[str] = set()
    positive_weighted = 0.0
    negative_weighted = 0.0

    for tier, weight in _POSITIVE_TIER_WEIGHTS.items():
        overlap = cluster_marker_set & _normalize_gene_set(tier_map.get(tier, []))
        if overlap:
            positive_hits.update(overlap)
            positive_weighted += len(overlap) * weight

    for tier, penalty in _NEGATIVE_TIER_WEIGHTS.items():
        overlap = cluster_marker_set & _normalize_gene_set(tier_map.get(tier, []))
        if overlap:
            negative_hits.update(overlap)
            negative_weighted += len(overlap) * penalty

    marker_overlap = len(positive_hits)
    negative_overlap = len(negative_hits)
    support = 0.0
    if marker_overlap > 0:
        support = min(
            1.0,
            positive_weighted / max(float(thresholds.min_marker_overlap), 1.0),
        )
    specificity = 1.0
    if positive_weighted > 0 or negative_weighted > 0:
        specificity = max(
            0.0,
            1.0 - (negative_weighted / max(positive_weighted + negative_weighted, 1.0)),
        )
    marker_score = _clamp(0.65 * support + 0.35 * specificity if marker_overlap > 0 else 0.0)

    normalized_label = normalize_label(label)
    consensus = consensus_summary.get(normalized_label, {"fraction": 0.0, "mean_confidence": 0.0})
    consensus_fraction = _clamp(float(consensus.get("fraction", 0.0)))
    consensus_mean_confidence = _clamp(float(consensus.get("mean_confidence", 0.0)))
    consensus_score = _clamp(
        0.6 * consensus_fraction + 0.4 * consensus_mean_confidence
        if consensus_fraction > 0.0 or consensus_mean_confidence > 0.0
        else 0.0
    )

    lineage = _infer_lineage(normalized_label)
    lineage_consensus_fraction = _clamp(float(lineage_consensus.get(lineage, 0.0)))
    prior_score = _resolve_prior_score(normalized_label, prior)
    composite_score = _clamp(0.6 * marker_score + 0.3 * consensus_score + 0.1 * prior_score)

    strong_reference_support = (
        consensus_fraction >= thresholds.min_consensus_fraction
        and consensus_mean_confidence >= thresholds.min_mean_confidence
    )
    passes_marker_gate = (
        marker_overlap >= thresholds.min_marker_overlap
        and marker_score >= thresholds.min_marker_score
        and negative_overlap <= thresholds.max_negative_markers
    )
    passes_acceptance_gate = (
        passes_marker_gate and composite_score >= thresholds.min_composite_score
    )
    if passes_acceptance_gate:
        passes_acceptance_gate = (
            strong_reference_support
            or marker_overlap >= (thresholds.min_marker_overlap + 1)
            or prior_score >= 0.6
        )

    return ConservativeCandidateEvidence(
        label=str(label),
        normalized_label=normalized_label,
        lineage=lineage,
        positive_markers=sorted(positive_hits),
        negative_markers=sorted(negative_hits),
        marker_overlap=marker_overlap,
        negative_overlap=negative_overlap,
        marker_score=marker_score,
        consensus_fraction=consensus_fraction,
        consensus_mean_confidence=consensus_mean_confidence,
        consensus_score=consensus_score,
        lineage_consensus_fraction=lineage_consensus_fraction,
        prior_score=prior_score,
        composite_score=composite_score,
        passes_marker_gate=passes_marker_gate,
        passes_acceptance_gate=passes_acceptance_gate,
    )


def evaluate_cluster(
    *,
    cluster_id: str,
    cluster_markers: list[str],
    cluster_labels: list[str],
    cluster_confidences: list[float],
    marker_pack: dict[str, dict[str, list[str]]] | None,
    prior: dict[str, float] | None = None,
    thresholds: ConservativeThresholds | None = None,
) -> ConservativeClusterCall:
    """Evaluate one cluster and return an auditable conservative call."""
    thresholds = thresholds or ConservativeThresholds()
    prior = prior or {}
    consensus_summary, lineage_consensus = _summarize_reference_consensus(
        cluster_labels,
        cluster_confidences,
    )
    top_consensus = sorted(
        consensus_summary.items(),
        key=lambda item: (-item[1]["fraction"], -item[1]["mean_confidence"], item[0]),
    )
    consensus_payload: dict[str, Any] = {
        "top_label": top_consensus[0][0] if top_consensus else "Unknown",
        "top_fraction": top_consensus[0][1]["fraction"] if top_consensus else 0.0,
        "top_mean_confidence": top_consensus[0][1]["mean_confidence"] if top_consensus else 0.0,
        "n_distinct_labels": len(consensus_summary),
    }
    if not marker_pack:
        return ConservativeClusterCall(
            cluster_id=cluster_id,
            n_cells=len(cluster_labels),
            status="abstained",
            final_label="Unknown",
            final_level="unknown",
            confidence=0.0,
            uncertainty=1.0,
            confidence_bucket="low",
            reason="marker_pack_unavailable",
            thresholds=thresholds,
            cluster_markers=list(cluster_markers),
            consensus_summary=consensus_payload,
            prior_summary={"prior": prior},
        )

    candidates = [
        _candidate_from_marker_pack(
            label=label,
            tier_map=tier_map,
            cluster_markers=cluster_markers,
            consensus_summary=consensus_summary,
            lineage_consensus=lineage_consensus,
            prior=prior,
            thresholds=thresholds,
        )
        for label, tier_map in marker_pack.items()
    ]
    candidates.sort(
        key=lambda item: (
            -item.composite_score,
            -item.marker_score,
            -item.consensus_fraction,
            item.normalized_label,
        )
    )

    lineage_scores: dict[str, float] = {}
    for candidate in candidates:
        if candidate.lineage == "Unknown":
            continue
        lineage_scores[candidate.lineage] = max(
            lineage_scores.get(candidate.lineage, 0.0),
            candidate.composite_score,
        )

    accepted = [candidate for candidate in candidates if candidate.passes_acceptance_gate]
    top = accepted[0] if accepted else (candidates[0] if candidates else None)
    second = accepted[1] if len(accepted) > 1 else (candidates[1] if len(candidates) > 1 else None)
    top_margin = (
        max(0.0, float(top.composite_score) - float(second.composite_score))
        if top is not None and second is not None
        else float(top.composite_score if top is not None else 0.0)
    )

    if top is not None and accepted:
        if second is not None and top_margin < thresholds.min_winning_margin:
            if (
                thresholds.allow_lineage_fallback
                and top.lineage != "Unknown"
                and second.lineage == top.lineage
            ):
                confidence = _clamp((top.composite_score + second.composite_score) / 2.0)
                return ConservativeClusterCall(
                    cluster_id=cluster_id,
                    n_cells=len(cluster_labels),
                    status="lineage_only",
                    final_label=top.lineage,
                    final_level="lineage",
                    confidence=confidence,
                    uncertainty=1.0 - confidence,
                    confidence_bucket=_bucket(confidence),
                    reason="close_subtype_competition_same_lineage",
                    thresholds=thresholds,
                    cluster_markers=list(cluster_markers),
                    candidates=candidates[:10],
                    lineage_scores=lineage_scores,
                    consensus_summary=consensus_payload,
                    prior_summary={"prior": prior},
                )
            return ConservativeClusterCall(
                cluster_id=cluster_id,
                n_cells=len(cluster_labels),
                status="ambiguous",
                final_label="Unknown",
                final_level="unknown",
                confidence=_clamp(top.composite_score),
                uncertainty=1.0 - _clamp(top.composite_score),
                confidence_bucket=_bucket(_clamp(top.composite_score)),
                reason="close_competing_labels",
                thresholds=thresholds,
                cluster_markers=list(cluster_markers),
                candidates=candidates[:10],
                lineage_scores=lineage_scores,
                consensus_summary=consensus_payload,
                prior_summary={"prior": prior},
            )
        confidence = _clamp(0.8 * top.composite_score + 0.2 * top_margin)
        return ConservativeClusterCall(
            cluster_id=cluster_id,
            n_cells=len(cluster_labels),
            status="accepted",
            final_label=top.normalized_label,
            final_level="cell_type",
            confidence=confidence,
            uncertainty=1.0 - confidence,
            confidence_bucket=_bucket(confidence),
            reason="marker_and_reference_support",
            thresholds=thresholds,
            cluster_markers=list(cluster_markers),
            candidates=candidates[:10],
            lineage_scores=lineage_scores,
            consensus_summary=consensus_payload,
            prior_summary={"prior": prior},
        )

    sorted_lineages = sorted(lineage_scores.items(), key=lambda item: (-item[1], item[0]))
    if thresholds.allow_lineage_fallback and sorted_lineages:
        top_lineage, top_lineage_score = sorted_lineages[0]
        second_lineage_score = sorted_lineages[1][1] if len(sorted_lineages) > 1 else 0.0
        if top_lineage != "Unknown" and (
            top_lineage_score >= thresholds.lineage_min_score
            and (top_lineage_score - second_lineage_score) >= thresholds.lineage_min_margin
        ):
            confidence = _clamp(top_lineage_score)
            return ConservativeClusterCall(
                cluster_id=cluster_id,
                n_cells=len(cluster_labels),
                status="lineage_only",
                final_label=top_lineage,
                final_level="lineage",
                confidence=confidence,
                uncertainty=1.0 - confidence,
                confidence_bucket=_bucket(confidence),
                reason="lineage_supported_but_subtype_not_resolved",
                thresholds=thresholds,
                cluster_markers=list(cluster_markers),
                candidates=candidates[:10],
                lineage_scores=lineage_scores,
                consensus_summary=consensus_payload,
                prior_summary={"prior": prior},
            )

    abstain_reason = "insufficient_support"
    if (
        top is not None
        and second is not None
        and abs(top.composite_score - second.composite_score) < 0.05
    ):
        confidence = _clamp(top.composite_score)
        return ConservativeClusterCall(
            cluster_id=cluster_id,
            n_cells=len(cluster_labels),
            status="ambiguous",
            final_label="Unknown",
            final_level="unknown",
            confidence=confidence,
            uncertainty=1.0 - confidence,
            confidence_bucket=_bucket(confidence),
            reason="too_close_to_call",
            thresholds=thresholds,
            cluster_markers=list(cluster_markers),
            candidates=candidates[:10],
            lineage_scores=lineage_scores,
            consensus_summary=consensus_payload,
            prior_summary={"prior": prior},
        )
    elif top is not None and top.negative_overlap > thresholds.max_negative_markers:
        abstain_reason = "contradictory_negative_markers"
    elif not candidates:
        abstain_reason = "no_candidates_available"

    return ConservativeClusterCall(
        cluster_id=cluster_id,
        n_cells=len(cluster_labels),
        status="abstained",
        final_label="Unknown",
        final_level="unknown",
        confidence=_clamp(top.composite_score if top is not None else 0.0),
        uncertainty=1.0 - _clamp(top.composite_score if top is not None else 0.0),
        confidence_bucket=_bucket(_clamp(top.composite_score if top is not None else 0.0)),
        reason=abstain_reason,
        thresholds=thresholds,
        cluster_markers=list(cluster_markers),
        candidates=candidates[:10],
        lineage_scores=lineage_scores,
        consensus_summary=consensus_payload,
        prior_summary={"prior": prior},
    )


def annotate_clusters(
    *,
    cluster_assignments: dict[str, str],
    cluster_markers: dict[str, list[str]],
    marker_pack: dict[str, dict[str, list[str]]] | None,
    reference_labels: dict[str, str] | None = None,
    reference_confidences: dict[str, float] | None = None,
    retrieval_priors: dict[str, dict[str, float]] | None = None,
    thresholds: ConservativeThresholds | None = None,
) -> dict[str, ConservativeClusterCall]:
    """Apply the conservative decision rule to every cluster."""
    thresholds = thresholds or ConservativeThresholds()
    reference_labels = reference_labels or {}
    reference_confidences = reference_confidences or {}
    retrieval_priors = retrieval_priors or {}

    cluster_to_cells: dict[str, list[str]] = {}
    for cell_id, cluster_id in cluster_assignments.items():
        cluster_to_cells.setdefault(str(cluster_id), []).append(str(cell_id))

    calls: dict[str, ConservativeClusterCall] = {}
    for cluster_id, cell_ids in sorted(cluster_to_cells.items(), key=lambda item: item[0]):
        labels = [reference_labels.get(cell_id, "Unknown") for cell_id in cell_ids]
        confidences = [
            _clamp(float(reference_confidences.get(cell_id, 0.0))) for cell_id in cell_ids
        ]
        calls[cluster_id] = evaluate_cluster(
            cluster_id=cluster_id,
            cluster_markers=cluster_markers.get(cluster_id, []),
            cluster_labels=labels,
            cluster_confidences=confidences,
            marker_pack=marker_pack,
            prior=retrieval_priors.get(cluster_id, {}),
            thresholds=thresholds,
        )
    return calls


def benchmark_predictions(
    *,
    predicted_labels: dict[str, str],
    reference_labels: dict[str, str],
    reference_key: str,
) -> AnnotationBenchmarkReport:
    """Benchmark predicted labels against a reference annotation column."""
    evaluated_cells = sorted(set(predicted_labels) & set(reference_labels))
    per_label_counts: dict[str, dict[str, int]] = {}
    confusion: dict[str, dict[str, int]] = {}
    covered_cells = 0
    abstained_cells = 0
    correct_covered = 0
    correct_overall = 0
    lineage_consistent_cells = 0

    for cell_id in evaluated_cells:
        predicted = normalize_label(str(predicted_labels[cell_id]).strip() or "Unknown")
        reference = normalize_label(str(reference_labels[cell_id]).strip() or "Unknown")
        if reference.lower() == "nan" or not reference.strip():
            continue
        counts = per_label_counts.setdefault(
            reference, {"support": 0, "covered": 0, "tp": 0, "fp": 0, "abstained": 0}
        )
        counts["support"] += 1
        confusion.setdefault(reference, {})
        confusion[reference][predicted] = confusion[reference].get(predicted, 0) + 1

        if predicted.lower() in _ABSTAIN_LABELS:
            abstained_cells += 1
            counts["abstained"] += 1
            continue

        covered_cells += 1
        counts["covered"] += 1
        predicted_lineage = _infer_lineage(predicted)
        reference_lineage = _infer_lineage(reference)
        lineage_consistent = predicted == reference or (
            predicted_lineage != "Unknown"
            and reference_lineage != "Unknown"
            and predicted_lineage == reference_lineage
        )
        if lineage_consistent:
            lineage_consistent_cells += 1
        if predicted == reference:
            correct_covered += 1
            correct_overall += 1
            counts["tp"] += 1
        else:
            other = per_label_counts.setdefault(
                predicted,
                {"support": 0, "covered": 0, "tp": 0, "fp": 0, "abstained": 0},
            )
            other["fp"] += 1

    total_evaluated = sum(metrics["support"] for metrics in per_label_counts.values())
    if total_evaluated == 0:
        return AnnotationBenchmarkReport(
            reference_key=reference_key, total_cells=len(reference_labels)
        )

    per_label: dict[str, BenchmarkLabelMetrics] = {}
    recall_values: list[float] = []
    f1_values: list[float] = []
    for label, counts in per_label_counts.items():
        tp = counts["tp"]
        support = counts["support"]
        fp = counts["fp"]
        covered = counts["covered"]
        abstained = counts["abstained"]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / support if support > 0 else 0.0
        f1 = 2.0 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        per_label[label] = BenchmarkLabelMetrics(
            support=support,
            covered=covered,
            abstained=abstained,
            precision=precision,
            recall=recall,
            f1=f1,
            coverage=(covered / support) if support > 0 else 0.0,
        )
        if support > 0:
            recall_values.append(recall)
            f1_values.append(f1)

    coverage = covered_cells / total_evaluated if total_evaluated > 0 else 0.0
    return AnnotationBenchmarkReport(
        reference_key=reference_key,
        total_cells=len(reference_labels),
        evaluated_cells=total_evaluated,
        covered_cells=covered_cells,
        abstained_cells=abstained_cells,
        lineage_consistent_cells=lineage_consistent_cells,
        coverage=coverage,
        overall_accuracy=(correct_overall / total_evaluated) if total_evaluated > 0 else 0.0,
        accuracy_on_covered=(correct_covered / covered_cells) if covered_cells > 0 else 0.0,
        lineage_consistent_accuracy=(
            lineage_consistent_cells / total_evaluated if total_evaluated > 0 else 0.0
        ),
        lineage_consistent_accuracy_on_covered=(
            lineage_consistent_cells / covered_cells if covered_cells > 0 else 0.0
        ),
        macro_f1=(sum(f1_values) / len(f1_values)) if f1_values else 0.0,
        balanced_accuracy=(sum(recall_values) / len(recall_values)) if recall_values else 0.0,
        per_label=per_label,
        confusion_matrix=confusion,
    )
