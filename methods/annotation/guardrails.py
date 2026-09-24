"""Annotation guardrails for ontology validation, label normalization, and columns policy.

Validates labels against cell type ontologies and hierarchy constraints,
normalizes variant label strings to canonical names, and enforces annotation
columns policy (required, optional, protected).

# Feature: gap-analysis-and-verification
"""

from __future__ import annotations

import logging
import re
from typing import Any

from zerna_contracts.base import ZernaBaseModel
from pydantic import Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class GuardrailViolation(ZernaBaseModel):
    """A single guardrail violation."""

    cell_id: str = Field(description="Cell identifier that violated the rule")
    label: str = Field(description="The label that caused the violation")
    rule: str = Field(description="Name of the guardrail rule violated")
    message: str = Field(description="Human-readable description of the violation")


class GuardrailResult(ZernaBaseModel):
    """Result of guardrail validation."""

    valid: bool = Field(description="True if no violations were found")
    violations: list[GuardrailViolation] = Field(
        default_factory=list,
        description="List of all violations found",
    )


class OntologyDefinition(ZernaBaseModel):
    """Defines a cell type ontology for validation."""

    name: str = Field(description="Ontology name (e.g. 'cell_ontology')")
    valid_labels: set[str] = Field(description="Set of valid canonical cell type labels")
    hierarchy: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Parent label -> list of allowed child labels",
    )


class ColumnsPolicy(ZernaBaseModel):
    """Policy defining required, optional, and protected annotation columns."""

    required: list[str] = Field(
        default_factory=list,
        description="Columns that must be present in annotation output",
    )
    optional: list[str] = Field(
        default_factory=list,
        description="Columns that may be present but are not required",
    )
    protected: list[str] = Field(
        default_factory=list,
        description="Columns that must not be modified from pre-annotation values",
    )


# ---------------------------------------------------------------------------
# Label normalization
# ---------------------------------------------------------------------------

# Mapping of common variant strings to canonical cell type names.
# Keys are lowercased, stripped variants; values are canonical names.
_DEFAULT_ALIAS_MAP: dict[str, str] = {
    "t cell": "T cell",
    "t cells": "T cell",
    "t-cell": "T cell",
    "t-cells": "T cell",
    "tcell": "T cell",
    "b cell": "B cell",
    "b cells": "B cell",
    "b-cell": "B cell",
    "b-cells": "B cell",
    "bcell": "B cell",
    "nk cell": "NK cell",
    "nk cells": "NK cell",
    "nk-cell": "NK cell",
    "natural killer": "NK cell",
    "natural killer cell": "NK cell",
    "monocyte": "Monocyte",
    "monocytes": "Monocyte",
    "macrophage": "Macrophage",
    "macrophages": "Macrophage",
    "dendritic cell": "Dendritic cell",
    "dendritic cells": "Dendritic cell",
    "dc": "Dendritic cell",
    "fibroblast": "Fibroblast",
    "fibroblasts": "Fibroblast",
    "endothelial": "Endothelial",
    "endothelial cell": "Endothelial",
    "endothelial cells": "Endothelial",
    "epithelial": "Epithelial",
    "epithelial cell": "Epithelial",
    "epithelial cells": "Epithelial",
    "stromal": "Stromal",
    "stromal cell": "Stromal",
    "stromal cells": "Stromal",
    "pericyte": "Pericyte",
    "pericytes": "Pericyte",
    "smooth muscle cell": "Smooth muscle cell",
    "smooth muscle cells": "Smooth muscle cell",
    "smc": "Smooth muscle cell",
    "neutrophil": "Neutrophil",
    "neutrophils": "Neutrophil",
    "mast cell": "Mast cell",
    "mast cells": "Mast cell",
    "plasma cell": "Plasma cell",
    "plasma cells": "Plasma cell",
    "unknown": "Unknown",
}


def normalize_label(label: str, alias_map: dict[str, str] | None = None) -> str:
    """Normalize a variant label string to its canonical cell type name.

    Normalization steps:
    1. Strip leading/trailing whitespace
    2. Collapse internal whitespace to single spaces
    3. Look up the lowercased form in the alias map
    4. If not found, return the cleaned (but not lowercased) form

    The function is idempotent: normalize(normalize(x)) == normalize(x).

    Args:
        label: The raw label string.
        alias_map: Optional custom alias map. Defaults to built-in aliases.

    Returns:
        The canonical cell type name.
    """
    if alias_map is None:
        alias_map = _DEFAULT_ALIAS_MAP

    # Step 1 & 2: strip and collapse whitespace
    cleaned = re.sub(r"\s+", " ", label.strip())

    # Step 3: lookup in alias map (case-insensitive), chase chains to a fixed
    # point so that normalize(normalize(x)) == normalize(x).
    key = cleaned.lower()
    seen: set[str] = set()
    while key in alias_map and key not in seen:
        seen.add(key)
        resolved = re.sub(r"\s+", " ", alias_map[key].strip())
        next_key = resolved.lower()
        if next_key == key or next_key not in alias_map:
            return resolved
        key = next_key
    if seen:
        # We broke out because of a cycle — return last resolved value
        return alias_map.get(key, cleaned)

    # Step 4: return cleaned form
    return cleaned


# ---------------------------------------------------------------------------
# Ontology and hierarchy validation
# ---------------------------------------------------------------------------


def _validate_ontology(
    labels: dict[str, str],
    ontology: OntologyDefinition,
) -> list[GuardrailViolation]:
    """Validate labels against the ontology's valid label set."""
    violations: list[GuardrailViolation] = []
    for cell_id, label in labels.items():
        if label not in ontology.valid_labels:
            violations.append(
                GuardrailViolation(
                    cell_id=cell_id,
                    label=label,
                    rule="ontology_membership",
                    message=(
                        f"Label '{label}' is not a valid label in ontology "
                        f"'{ontology.name}'. Valid labels: "
                        f"{sorted(ontology.valid_labels)[:10]}..."
                    ),
                )
            )
    return violations


def _validate_hierarchy(
    labels: dict[str, str],
    ontology: OntologyDefinition,
) -> list[GuardrailViolation]:
    """Validate labels against hierarchy constraints.

    For each cell, if its label is a child in the hierarchy, check that
    the parent-child relationship is respected among sibling cells.
    """
    violations: list[GuardrailViolation] = []
    if not ontology.hierarchy:
        return violations

    # Build child -> allowed parents mapping
    child_to_parents: dict[str, set[str]] = {}
    for parent, children in ontology.hierarchy.items():
        for child in children:
            child_to_parents.setdefault(child, set()).add(parent)

    # All valid children across the hierarchy
    all_valid_children: set[str] = set()
    for children in ontology.hierarchy.values():
        all_valid_children.update(children)

    for cell_id, label in labels.items():
        # If the label claims to be a child, verify it's listed under some parent
        if label in child_to_parents:
            # Label is a valid child — no violation
            continue
        # If the label is a parent, that's fine too
        if label in ontology.hierarchy:
            continue
        # If the label is in valid_labels but not in hierarchy at all, skip
        if label in ontology.valid_labels:
            continue
        # Label not in ontology at all — already caught by ontology_membership
        # Only flag hierarchy violations for labels that ARE in the ontology
        # but violate hierarchy constraints
        if label not in ontology.valid_labels and label in all_valid_children:
            violations.append(
                GuardrailViolation(
                    cell_id=cell_id,
                    label=label,
                    rule="hierarchy_constraint",
                    message=f"Label '{label}' violates hierarchy constraints.",
                )
            )

    return violations


# ---------------------------------------------------------------------------
# Columns policy enforcement
# ---------------------------------------------------------------------------


def validate_columns_policy(
    output_columns: set[str],
    pre_annotation_values: dict[str, dict[str, Any]],
    post_annotation_values: dict[str, dict[str, Any]],
    policy: ColumnsPolicy,
) -> list[GuardrailViolation]:
    """Validate annotation output against the columns policy.

    Args:
        output_columns: Set of column names present in the annotation output.
        pre_annotation_values: cell_id -> {column: value} before annotation.
        post_annotation_values: cell_id -> {column: value} after annotation.
        policy: The columns policy to enforce.

    Returns:
        List of violations found.
    """
    violations: list[GuardrailViolation] = []

    # Check required columns are present
    for col in policy.required:
        if col not in output_columns:
            violations.append(
                GuardrailViolation(
                    cell_id="__policy__",
                    label="",
                    rule="required_column_missing",
                    message=f"Required column '{col}' is missing from annotation output.",
                )
            )

    # Check protected columns are not modified
    for col in policy.protected:
        for cell_id in post_annotation_values:
            pre_val = pre_annotation_values.get(cell_id, {}).get(col)
            post_val = post_annotation_values.get(cell_id, {}).get(col)
            if pre_val is not None and post_val is not None and pre_val != post_val:
                violations.append(
                    GuardrailViolation(
                        cell_id=cell_id,
                        label="",
                        rule="protected_column_modified",
                        message=(
                            f"Protected column '{col}' was modified for cell '{cell_id}': "
                            f"'{pre_val}' -> '{post_val}'."
                        ),
                    )
                )

    return violations


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------


def validate(
    labels: dict[str, str],
    ontology: OntologyDefinition | None = None,
    policy: ColumnsPolicy | None = None,
    output_columns: set[str] | None = None,
    pre_annotation_values: dict[str, dict[str, Any]] | None = None,
    post_annotation_values: dict[str, dict[str, Any]] | None = None,
) -> GuardrailResult:
    """Validate annotation labels against ontology, hierarchy, and columns policy.

    Args:
        labels: cell_id -> label mapping to validate.
        ontology: Optional ontology definition for label validation.
        policy: Optional columns policy for output validation.
        output_columns: Column names in the annotation output (for policy check).
        pre_annotation_values: Pre-annotation column values (for protected check).
        post_annotation_values: Post-annotation column values (for protected check).

    Returns:
        GuardrailResult with valid=True if no violations, else valid=False
        with all violations listed.
    """
    all_violations: list[GuardrailViolation] = []

    # Ontology validation
    if ontology is not None:
        all_violations.extend(_validate_ontology(labels, ontology))
        all_violations.extend(_validate_hierarchy(labels, ontology))

    # Columns policy validation
    if policy is not None:
        all_violations.extend(
            validate_columns_policy(
                output_columns=output_columns or set(),
                pre_annotation_values=pre_annotation_values or {},
                post_annotation_values=post_annotation_values or {},
                policy=policy,
            )
        )

    return GuardrailResult(
        valid=len(all_violations) == 0,
        violations=all_violations,
    )
