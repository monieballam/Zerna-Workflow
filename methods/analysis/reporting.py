"""Automated reporting module.

Generates QC reports, annotation summaries, run diagnostics,
annotation debug exports, and audit bundles.

# Feature: gap-analysis-and-verification
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from zerna_contracts.base import ZernaBaseModel

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ReportSection(ZernaBaseModel):
    """A single section within a QC or summary report."""

    title: str
    content: dict[str, Any]


class Report(ZernaBaseModel):
    """QC / annotation summary report."""

    report_type: str  # "qc", "annotation_summary", "diagnostic"
    sections: list[ReportSection]
    generated_at: datetime


class AnnotationDebugExport(ZernaBaseModel):
    """Diagnostic bundle for troubleshooting annotation issues."""

    diagnostic_data: dict[str, Any]
    cell_count: int
    label_distribution: dict[str, int]
    generated_at: datetime


class AuditBundle(ZernaBaseModel):
    """Audit bundle packaging QA metrics, calibration data, and provenance."""

    run_id: UUID
    qa_metrics: dict[str, Any]
    calibration_data: dict[str, Any]
    provenance: dict[str, Any]
    generated_at: datetime


# ---------------------------------------------------------------------------
# Required QC report sections
# ---------------------------------------------------------------------------

_REQUIRED_QC_SECTIONS = [
    "cell_counts",
    "gene_counts",
    "mitochondrial_fraction",
    "doublet_summary",
    "quality_filters",
]

_REQUIRED_ANNOTATION_SECTIONS = [
    "label_distribution",
    "confidence_summary",
    "marker_coverage",
]

_REQUIRED_DIAGNOSTIC_SECTIONS = [
    "run_parameters",
    "step_timings",
    "warnings",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_qc_report(adata: dict[str, Any]) -> Report:
    """Generate a QC report from expression data.

    Parameters
    ----------
    adata : dict
        Simplified AnnData-like dict with ``"obs"`` and optionally ``"X"``
        keys.

    Returns
    -------
    Report
        A report with all required QC sections populated.
    """
    obs: dict[str, dict[str, Any]] = adata.get("obs", {})
    x_data: dict[str, dict[str, float]] = adata.get("X", {})

    cell_count = len(obs)
    gene_set: set[str] = set()
    for cell_expr in x_data.values():
        gene_set.update(cell_expr.keys())

    sections: list[ReportSection] = [
        ReportSection(
            title="cell_counts",
            content={"total_cells": cell_count},
        ),
        ReportSection(
            title="gene_counts",
            content={"total_genes": len(gene_set)},
        ),
        ReportSection(
            title="mitochondrial_fraction",
            content={
                "mt_genes": [g for g in gene_set if g.startswith("MT-") or g.startswith("mt-")],
                "fraction": _compute_mt_fraction(x_data, gene_set),
            },
        ),
        ReportSection(
            title="doublet_summary",
            content=_compute_doublet_summary(obs),
        ),
        ReportSection(
            title="quality_filters",
            content={
                "min_genes_per_cell": 200,
                "min_cells_per_gene": 3,
                "max_mt_fraction": 0.2,
            },
        ),
    ]

    return Report(
        report_type="qc",
        sections=sections,
        generated_at=datetime.utcnow(),
    )


def generate_annotation_summary(adata: dict[str, Any]) -> Report:
    """Generate an annotation summary report.

    Parameters
    ----------
    adata : dict
        Simplified AnnData-like dict with ``"obs"`` containing annotation
        metadata (``cell_type``, ``confidence``, etc.).

    Returns
    -------
    Report
    """
    obs: dict[str, dict[str, Any]] = adata.get("obs", {})

    label_dist: dict[str, int] = {}
    confidences: list[float] = []
    markers_used: set[str] = set()

    for meta in obs.values():
        ct = str(meta.get("cell_type", "unknown"))
        label_dist[ct] = label_dist.get(ct, 0) + 1
        conf = meta.get("confidence")
        if conf is not None:
            confidences.append(float(conf))
        marker_list = meta.get("markers", [])
        if isinstance(marker_list, list):
            markers_used.update(marker_list)

    avg_conf = sum(confidences) / max(len(confidences), 1)

    sections: list[ReportSection] = [
        ReportSection(
            title="label_distribution",
            content={"distribution": label_dist},
        ),
        ReportSection(
            title="confidence_summary",
            content={
                "mean_confidence": avg_conf,
                "num_scored_cells": len(confidences),
            },
        ),
        ReportSection(
            title="marker_coverage",
            content={
                "markers_used": sorted(markers_used),
                "total_markers": len(markers_used),
            },
        ),
    ]

    return Report(
        report_type="annotation_summary",
        sections=sections,
        generated_at=datetime.utcnow(),
    )


def generate_diagnostic_report(run_params: dict[str, Any]) -> Report:
    """Generate a run diagnostic report.

    Parameters
    ----------
    run_params : dict
        Dictionary with run parameters, step timings, and any warnings.

    Returns
    -------
    Report
    """
    sections: list[ReportSection] = [
        ReportSection(
            title="run_parameters",
            content=run_params.get("parameters", {}),
        ),
        ReportSection(
            title="step_timings",
            content=run_params.get("step_timings", {}),
        ),
        ReportSection(
            title="warnings",
            content={"warnings": run_params.get("warnings", [])},
        ),
    ]

    return Report(
        report_type="diagnostic",
        sections=sections,
        generated_at=datetime.utcnow(),
    )


def generate_annotation_debug_export(adata: dict[str, Any]) -> AnnotationDebugExport:
    """Generate an annotation debug export (diagnostic bundle).

    Parameters
    ----------
    adata : dict
        Simplified AnnData-like dict with ``"obs"`` containing annotation
        metadata.

    Returns
    -------
    AnnotationDebugExport
    """
    obs: dict[str, dict[str, Any]] = adata.get("obs", {})

    label_dist: dict[str, int] = {}
    for meta in obs.values():
        ct = str(meta.get("cell_type", "unknown"))
        label_dist[ct] = label_dist.get(ct, 0) + 1

    diagnostic_data: dict[str, Any] = {
        "obs_columns": _collect_obs_columns(obs),
        "label_distribution": label_dist,
        "sample_cells": dict(list(obs.items())[:5]),
    }

    return AnnotationDebugExport(
        diagnostic_data=diagnostic_data,
        cell_count=len(obs),
        label_distribution=label_dist,
        generated_at=datetime.utcnow(),
    )


def generate_audit_bundle(
    run_id: UUID,
    qa_metrics: dict[str, Any],
    calibration_data: dict[str, Any],
    provenance: dict[str, Any],
) -> AuditBundle:
    """Generate an audit bundle for a completed run.

    Parameters
    ----------
    run_id : UUID
        Identifier of the run being audited.
    qa_metrics : dict
        QA metrics (e.g. accuracy, coverage, flagged cells).
    calibration_data : dict
        Calibration data (e.g. threshold tuning, confidence distributions).
    provenance : dict
        Provenance information (e.g. method versions, marker panel refs).

    Returns
    -------
    AuditBundle
    """
    return AuditBundle(
        run_id=run_id,
        qa_metrics=qa_metrics,
        calibration_data=calibration_data,
        provenance=provenance,
        generated_at=datetime.utcnow(),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_mt_fraction(
    x_data: dict[str, dict[str, float]],
    gene_set: set[str],
) -> float:
    """Compute average mitochondrial gene fraction across cells."""
    if not x_data:
        return 0.0
    mt_genes = {g for g in gene_set if g.startswith("MT-") or g.startswith("mt-")}
    if not mt_genes:
        return 0.0

    fractions: list[float] = []
    for cell_expr in x_data.values():
        total = sum(cell_expr.values())
        if total > 0:
            mt_total = sum(cell_expr.get(g, 0.0) for g in mt_genes)
            fractions.append(mt_total / total)
    return sum(fractions) / max(len(fractions), 1)


def _compute_doublet_summary(obs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Summarise doublet information from obs metadata."""
    doublet_count = 0
    for meta in obs.values():
        if meta.get("is_doublet", False):
            doublet_count += 1
    return {
        "total_cells": len(obs),
        "doublets_detected": doublet_count,
        "doublet_rate": doublet_count / max(len(obs), 1),
    }


def _collect_obs_columns(obs: dict[str, dict[str, Any]]) -> list[str]:
    """Collect all unique column names across obs entries."""
    columns: set[str] = set()
    for meta in obs.values():
        columns.update(meta.keys())
    return sorted(columns)
