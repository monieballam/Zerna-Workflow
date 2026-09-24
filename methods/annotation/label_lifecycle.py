"""Label lifecycle manager: draft → validate → finalize → post-finalize guard.

Defines label contracts, validates labels against contracts, finalizes label sets
with locking, and guards against post-finalize modifications without version increment.

# Feature: gap-analysis-and-verification
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from zerna_contracts.base import ZernaBaseModel
from pydantic import Field

from methods.annotation.guardrails import GuardrailResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class LabelContract(ZernaBaseModel):
    """Defines the required fields, types, and constraints for valid annotation labels."""

    required_fields: list[str] = Field(
        description="Fields that every label record must contain",
    )
    field_types: dict[str, str] = Field(
        default_factory=dict,
        description="Expected type name for each field (e.g. 'str', 'int', 'float')",
    )
    allowed_labels: list[str] | None = Field(
        default=None,
        description="If set, only these label values are permitted",
    )
    hierarchy_constraints: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Parent label -> list of allowed child labels",
    )


class ContractViolation(ZernaBaseModel):
    """A single label contract violation."""

    cell_id: str = Field(description="Cell identifier (or '__contract__' for global issues)")
    field: str = Field(description="The field that violated the contract")
    violation_type: str = Field(
        description="Type of violation: 'missing_field', 'wrong_type', 'disallowed_label'",
    )
    message: str = Field(description="Human-readable description of the violation")


class ValidationReport(ZernaBaseModel):
    """Result of validating labels against a label contract."""

    valid: bool = Field(description="True if no violations were found")
    violations: list[ContractViolation] = Field(
        default_factory=list,
        description="All violations found (not just the first one)",
    )


class FinalizedLabels(ZernaBaseModel):
    """A finalized, locked label set."""

    labels: dict[str, str] = Field(description="cell_id -> label mapping")
    version: int = Field(description="Version number of this label set")
    finalized_by: UUID = Field(description="User who finalized the labels")
    finalized_at: datetime = Field(description="Timestamp of finalization")
    locked: bool = Field(default=True, description="Whether labels are locked")


class ModificationResult(ZernaBaseModel):
    """Result of attempting to modify finalized labels."""

    success: bool = Field(description="Whether the modification was accepted")
    message: str = Field(description="Description of the outcome")
    updated_labels: FinalizedLabels | None = Field(
        default=None,
        description="Updated label set if modification succeeded",
    )


# ---------------------------------------------------------------------------
# Type mapping for contract validation
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
}


# ---------------------------------------------------------------------------
# Label contract validation
# ---------------------------------------------------------------------------


def validate_labels(
    labels: dict[str, dict[str, Any]],
    contract: LabelContract,
) -> ValidationReport:
    """Validate a set of label records against a label contract.

    Checks ALL violations — missing fields, wrong types, disallowed labels —
    and returns them in a single report (not just the first one found).

    Args:
        labels: cell_id -> {field: value} mapping. Each cell has a record of fields.
        contract: The label contract to validate against.

    Returns:
        ValidationReport with all violations found.
    """
    violations: list[ContractViolation] = []

    for cell_id, record in labels.items():
        # Check required fields
        for field in contract.required_fields:
            if field not in record:
                violations.append(
                    ContractViolation(
                        cell_id=cell_id,
                        field=field,
                        violation_type="missing_field",
                        message=f"Required field '{field}' is missing for cell '{cell_id}'.",
                    )
                )

        # Check field types
        for field, expected_type_name in contract.field_types.items():
            if field in record:
                expected_type = _TYPE_MAP.get(expected_type_name)
                if expected_type is not None and not isinstance(record[field], expected_type):
                    violations.append(
                        ContractViolation(
                            cell_id=cell_id,
                            field=field,
                            violation_type="wrong_type",
                            message=(
                                f"Field '{field}' for cell '{cell_id}' has type "
                                f"'{type(record[field]).__name__}', expected '{expected_type_name}'."
                            ),
                        )
                    )

        # Check allowed labels (if the record has a 'label' field)
        if contract.allowed_labels is not None and "label" in record:
            label_value = record["label"]
            if isinstance(label_value, str) and label_value not in contract.allowed_labels:
                violations.append(
                    ContractViolation(
                        cell_id=cell_id,
                        field="label",
                        violation_type="disallowed_label",
                        message=(
                            f"Label '{label_value}' for cell '{cell_id}' is not in the "
                            f"allowed labels list."
                        ),
                    )
                )

    return ValidationReport(
        valid=len(violations) == 0,
        violations=violations,
    )


# ---------------------------------------------------------------------------
# Guardrail-gated finalization
# ---------------------------------------------------------------------------


def finalize(
    labels: dict[str, str],
    user: UUID,
    *,
    guardrail_result: GuardrailResult | None = None,
    version: int = 1,
) -> FinalizedLabels:
    """Finalize a label set, locking it for future modification.

    If a guardrail_result is provided and contains violations, finalization
    is rejected with a ValueError that includes the violation details.

    Args:
        labels: cell_id -> label mapping to finalize.
        user: UUID of the user performing finalization.
        guardrail_result: Optional pre-computed guardrail validation result.
            If provided and invalid, finalization is blocked.
        version: Version number for the finalized label set.

    Returns:
        FinalizedLabels with locked=True.

    Raises:
        ValueError: If guardrail violations are present.
    """
    if guardrail_result is not None and not guardrail_result.valid:
        violation_details = [
            {"cell_id": v.cell_id, "label": v.label, "rule": v.rule, "message": v.message}
            for v in guardrail_result.violations
        ]
        raise ValueError(
            f"Cannot finalize labels: {len(guardrail_result.violations)} guardrail "
            f"violation(s) found. Details: {violation_details}"
        )

    now = datetime.utcnow()
    return FinalizedLabels(
        labels=labels,
        version=version,
        finalized_by=user,
        finalized_at=now,
        locked=True,
    )


# ---------------------------------------------------------------------------
# Post-finalize modification guard
# ---------------------------------------------------------------------------


def modify_finalized(
    finalized: FinalizedLabels,
    new_labels: dict[str, str],
    new_version: int,
    user: UUID,
) -> ModificationResult:
    """Attempt to modify a finalized label set.

    Modification is only allowed if the new version number is strictly greater
    than the current version. Without a version increment, the modification
    is rejected.

    Args:
        finalized: The current finalized label set.
        new_labels: The proposed new labels.
        new_version: The proposed new version number.
        user: UUID of the user requesting modification.

    Returns:
        ModificationResult indicating success or failure.
    """
    if not finalized.locked:
        # Shouldn't happen, but handle gracefully
        return ModificationResult(
            success=False,
            message="Label set is not in a finalized state.",
        )

    if new_version <= finalized.version:
        return ModificationResult(
            success=False,
            message=(
                f"Version increment required. Current version is {finalized.version}, "
                f"but proposed version is {new_version}. "
                f"New version must be greater than {finalized.version}."
            ),
        )

    now = datetime.utcnow()
    updated = FinalizedLabels(
        labels=new_labels,
        version=new_version,
        finalized_by=user,
        finalized_at=now,
        locked=True,
    )

    return ModificationResult(
        success=True,
        message=f"Labels updated to version {new_version}.",
        updated_labels=updated,
    )
