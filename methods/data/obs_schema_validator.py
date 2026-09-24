"""Obs DataFrame schema validation.

Validates `.obs` DataFrame schemas against an expected schema definition,
identifying missing required columns and type mismatches.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SchemaIssue:
    """A single schema validation issue."""

    column: str
    issue_type: str  # "missing" | "type_mismatch"
    expected: str | None = None
    actual: str | None = None
    message: str = ""


@dataclass(frozen=True)
class ObsSchemaValidationResult:
    """Result of validating an obs schema against expected schema."""

    valid: bool
    issues: list[SchemaIssue] = field(default_factory=list)


# Canonical type aliases — allows flexible matching
_TYPE_ALIASES: dict[str, set[str]] = {
    "float64": {"float64", "float", "double", "float32"},
    "int64": {"int64", "int", "integer", "int32"},
    "object": {"object", "str", "string", "unicode"},
    "bool": {"bool", "boolean"},
    "category": {"category", "categorical"},
}


def _types_compatible(expected: str, actual: str) -> bool:
    """Check if actual dtype is compatible with expected dtype."""
    if expected == actual:
        return True
    expected_lower = expected.lower()
    actual_lower = actual.lower()
    if expected_lower == actual_lower:
        return True
    aliases = _TYPE_ALIASES.get(expected_lower)
    if aliases and actual_lower in aliases:
        return True
    return False


def validate_obs_schema(
    actual_schema: dict[str, str],
    expected_schema: dict[str, str],
) -> ObsSchemaValidationResult:
    """Validate an obs DataFrame schema against an expected schema.

    Parameters
    ----------
    actual_schema:
        Mapping of column name -> dtype string for the actual .obs DataFrame.
    expected_schema:
        Mapping of column name -> dtype string for the required columns.

    Returns
    -------
    ObsSchemaValidationResult with ``valid=True`` if no issues, else ``valid=False``
    with a list of ``SchemaIssue`` entries.
    """
    issues: list[SchemaIssue] = []

    for col_name, expected_dtype in expected_schema.items():
        if col_name not in actual_schema:
            issues.append(
                SchemaIssue(
                    column=col_name,
                    issue_type="missing",
                    expected=expected_dtype,
                    actual=None,
                    message=f"Required column '{col_name}' is missing",
                )
            )
        else:
            actual_dtype = actual_schema[col_name]
            if not _types_compatible(expected_dtype, actual_dtype):
                issues.append(
                    SchemaIssue(
                        column=col_name,
                        issue_type="type_mismatch",
                        expected=expected_dtype,
                        actual=actual_dtype,
                        message=(
                            f"Column '{col_name}' has type '{actual_dtype}' "
                            f"but expected '{expected_dtype}'"
                        ),
                    )
                )

    return ObsSchemaValidationResult(
        valid=len(issues) == 0,
        issues=issues,
    )
