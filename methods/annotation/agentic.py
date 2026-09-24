"""Agentic annotation: LLM-assisted label refinement with rule-based fallback.

# Feature: gap-analysis-and-verification

Accepts uncertain cluster labels, uses an LLM to suggest refined annotations
with reasoning.  Labels output as *suggestion* (requires human approval).
Logs model version, prompt hash, reasoning chain.
Falls back to rule-based annotation if LLM is unavailable.

Interface: ``suggest(uncertain_labels, context) -> list[AgenticSuggestion]``
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Protocol, runtime_checkable

from zerna_contracts.base import ZernaBaseModel
from pydantic import Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class AgenticSuggestion(ZernaBaseModel):
    """A single agentic annotation suggestion.

    ``is_authoritative`` is **always** ``False`` until a human approves the
    suggestion via the label lifecycle manager.
    """

    cluster_id: str = Field(description="Cluster identifier")
    original_label: str = Field(description="Original uncertain label")
    suggested_label: str = Field(description="LLM-suggested refined label")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the suggestion")
    reasoning: str = Field(description="Reasoning chain for the suggestion")
    model_version: str = Field(description="LLM model version used")
    prompt_context_hash: str = Field(
        description="SHA-256 hash of the prompt context sent to the LLM"
    )
    is_authoritative: bool = Field(
        default=False,
        description="Always False until human approval",
    )


class UncertainLabel(ZernaBaseModel):
    """An uncertain cluster label submitted for agentic refinement."""

    cluster_id: str = Field(description="Cluster identifier")
    label: str = Field(description="Current uncertain label")
    marker_evidence: dict[str, float] = Field(
        default_factory=dict,
        description="Gene -> expression score supporting the label",
    )


class AnnotationContext(ZernaBaseModel):
    """Contextual information provided alongside uncertain labels."""

    tissue_type: str = Field(default="", description="Tissue of origin")
    organism: str = Field(default="human", description="Organism")
    known_cell_types: list[str] = Field(
        default_factory=list,
        description="Cell types already confidently identified in the dataset",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context key-value pairs",
    )


# ---------------------------------------------------------------------------
# LLM client protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMClient(Protocol):
    """Protocol that any LLM backend must satisfy."""

    def complete(self, prompt: str) -> str:
        """Send *prompt* and return the completion text."""
        ...

    @property
    def model_version(self) -> str:
        """Return the model version string."""
        ...


class LLMUnavailableError(Exception):
    """Raised when the LLM service cannot be reached."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RULE_BASED_MODEL_VERSION = "rule-based-v1"


def _compute_prompt_hash(prompt: str) -> str:
    """Return a deterministic SHA-256 hex digest of *prompt*."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _build_prompt(
    labels: list[UncertainLabel],
    context: AnnotationContext,
) -> str:
    """Build the LLM prompt from uncertain labels and context."""
    lines = [
        "You are a cell-type annotation expert.",
        f"Tissue: {context.tissue_type or 'unknown'}",
        f"Organism: {context.organism}",
    ]
    if context.known_cell_types:
        lines.append(f"Known cell types: {', '.join(context.known_cell_types)}")
    lines.append("")
    lines.append("Refine the following uncertain cluster labels:")
    for ul in labels:
        evidence = ", ".join(f"{g}={v:.2f}" for g, v in sorted(ul.marker_evidence.items()))
        lines.append(f"  Cluster {ul.cluster_id}: '{ul.label}' (markers: {evidence})")
    lines.append("")
    lines.append(
        "For each cluster, respond with: cluster_id | suggested_label | confidence (0-1) | reasoning"
    )
    return "\n".join(lines)


def _parse_llm_response(
    response: str,
    labels: list[UncertainLabel],
    model_version: str,
    prompt_hash: str,
) -> list[AgenticSuggestion]:
    """Parse a structured LLM response into ``AgenticSuggestion`` objects.

    Expected format per line::

        cluster_id | suggested_label | confidence | reasoning

    Lines that cannot be parsed are skipped and a warning is logged.
    """
    suggestions: list[AgenticSuggestion] = []
    label_map = {ul.cluster_id: ul for ul in labels}

    for line in response.strip().splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        cluster_id, suggested_label, conf_str, reasoning = (
            parts[0],
            parts[1],
            parts[2],
            " | ".join(parts[3:]),
        )
        if cluster_id not in label_map:
            logger.warning("LLM returned unknown cluster_id=%s, skipping", cluster_id)
            continue
        try:
            confidence = max(0.0, min(1.0, float(conf_str)))
        except ValueError:
            logger.warning(
                "Could not parse confidence '%s' for cluster %s, defaulting to 0.5",
                conf_str,
                cluster_id,
            )
            confidence = 0.5

        suggestions.append(
            AgenticSuggestion(
                cluster_id=cluster_id,
                original_label=label_map[cluster_id].label,
                suggested_label=suggested_label or label_map[cluster_id].label,
                confidence=confidence,
                reasoning=reasoning or "No reasoning provided",
                model_version=model_version,
                prompt_context_hash=prompt_hash,
                is_authoritative=False,
            )
        )

    return suggestions


# ---------------------------------------------------------------------------
# Rule-based fallback (Req 16.4)
# ---------------------------------------------------------------------------

# Simple heuristic rules mapping marker patterns to refined labels.
_DEFAULT_RULES: dict[str, list[tuple[str, str, float]]] = {
    # marker_gene -> [(suggested_label, reasoning_snippet, confidence)]
    "CD3D": [("T cell", "High CD3D expression indicates T cell lineage", 0.7)],
    "CD3E": [("T cell", "High CD3E expression indicates T cell lineage", 0.7)],
    "CD19": [("B cell", "High CD19 expression indicates B cell lineage", 0.7)],
    "CD79A": [("B cell", "High CD79A expression indicates B cell lineage", 0.7)],
    "CD14": [("Monocyte", "High CD14 expression indicates monocyte lineage", 0.65)],
    "CD68": [("Macrophage", "High CD68 expression indicates macrophage lineage", 0.65)],
    "EPCAM": [("Epithelial", "High EPCAM expression indicates epithelial lineage", 0.7)],
    "PECAM1": [("Endothelial", "High PECAM1 expression indicates endothelial lineage", 0.7)],
    "COL1A1": [("Fibroblast", "High COL1A1 expression indicates fibroblast lineage", 0.65)],
    "PTPRC": [("Immune", "High PTPRC (CD45) expression indicates immune lineage", 0.6)],
}

_MARKER_THRESHOLD = 1.0  # minimum expression to consider a marker "expressed"


def _rule_based_suggest(
    labels: list[UncertainLabel],
    context: AnnotationContext,
    rules: dict[str, list[tuple[str, str, float]]] | None = None,
) -> list[AgenticSuggestion]:
    """Produce suggestions using simple marker-based heuristic rules.

    This is the fallback path when the LLM service is unavailable.
    """
    rule_map = rules or _DEFAULT_RULES
    prompt_text = _build_prompt(labels, context)
    prompt_hash = _compute_prompt_hash(prompt_text)

    suggestions: list[AgenticSuggestion] = []
    for ul in labels:
        best_label = ul.label
        best_confidence = 0.3  # low default confidence for rule-based
        best_reasoning = "Rule-based fallback: no strong marker evidence found"

        for gene, expr_val in ul.marker_evidence.items():
            if expr_val < _MARKER_THRESHOLD:
                continue
            if gene in rule_map:
                for suggested, reasoning, conf in rule_map[gene]:
                    if conf > best_confidence:
                        best_label = suggested
                        best_confidence = conf
                        best_reasoning = f"Rule-based fallback: {reasoning}"

        suggestions.append(
            AgenticSuggestion(
                cluster_id=ul.cluster_id,
                original_label=ul.label,
                suggested_label=best_label,
                confidence=best_confidence,
                reasoning=best_reasoning,
                model_version=_RULE_BASED_MODEL_VERSION,
                prompt_context_hash=prompt_hash,
                is_authoritative=False,
            )
        )

    return suggestions


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def suggest(
    uncertain_labels: list[UncertainLabel],
    context: AnnotationContext | None = None,
    llm_client: LLMClient | None = None,
    rules: dict[str, list[tuple[str, str, float]]] | None = None,
) -> list[AgenticSuggestion]:
    """Suggest refined annotations for uncertain cluster labels.

    Attempts to use the provided *llm_client* first.  If the client is
    ``None`` or raises :class:`LLMUnavailableError` (or any other
    ``Exception``), the system falls back to rule-based annotation
    transparently.

    Every returned :class:`AgenticSuggestion` has ``is_authoritative=False``
    and includes ``model_version``, ``prompt_context_hash``, and
    ``reasoning``.

    Args:
        uncertain_labels: Cluster labels to refine.
        context: Optional annotation context (tissue, organism, etc.).
        llm_client: Optional LLM backend.  ``None`` triggers rule-based
            fallback immediately.
        rules: Optional custom rule map for the rule-based fallback.

    Returns:
        A list of :class:`AgenticSuggestion`, one per input label.
    """
    if not uncertain_labels:
        return []

    ctx = context or AnnotationContext()

    # --- LLM path ---
    if llm_client is not None:
        try:
            prompt = _build_prompt(uncertain_labels, ctx)
            prompt_hash = _compute_prompt_hash(prompt)
            response = llm_client.complete(prompt)
            suggestions = _parse_llm_response(
                response, uncertain_labels, llm_client.model_version, prompt_hash
            )
            # If the LLM returned suggestions for all clusters, use them.
            # Otherwise, fill gaps with rule-based suggestions.
            if len(suggestions) == len(uncertain_labels):
                logger.info("Agentic annotation: LLM produced %d suggestions", len(suggestions))
                return suggestions

            # Fill missing clusters with rule-based fallback
            covered = {s.cluster_id for s in suggestions}
            missing = [ul for ul in uncertain_labels if ul.cluster_id not in covered]
            if missing:
                logger.info(
                    "Agentic annotation: LLM covered %d/%d clusters, "
                    "filling %d with rule-based fallback",
                    len(covered),
                    len(uncertain_labels),
                    len(missing),
                )
                suggestions.extend(_rule_based_suggest(missing, ctx, rules))
            return suggestions

        except Exception:
            logger.warning(
                "LLM service unavailable, falling back to rule-based annotation",
                exc_info=True,
            )

    # --- Rule-based fallback ---
    logger.info(
        "Agentic annotation: using rule-based fallback for %d labels", len(uncertain_labels)
    )
    return _rule_based_suggest(uncertain_labels, ctx, rules)
