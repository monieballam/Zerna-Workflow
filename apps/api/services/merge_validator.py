"""Merge validator for schema compatibility checking across multiple files.

Validates schema compatibility before merging multiple dataset files.
Reports field-level conflicts with actionable error messages.

# Feature: gap-analysis-and-verification
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from packages.contracts.zerna_contracts.base import ZernaBaseModel


class FileSchema(ZernaBaseModel):
    """Schema description for a single file in a merge operation.

    Attributes:
        filename: Name or identifier of the source file.
        columns: Mapping of column name to dtype string (e.g. "float64", "int64", "object").
    """

    filename: str = Field(description="Source file name or identifier")
    columns: dict[str, str] = Field(description="Mapping of column name to dtype string")


class SchemaConflict(ZernaBaseModel):
    """A single field-level conflict between two file schemas.

    Attributes:
        field: Column name where the conflict occurs.
        file_a: First file involved in the conflict.
        file_b: Second file involved in the conflict.
        type_a: Column dtype in file_a.
        type_b: Column dtype in file_b.
        message: Human-readable description of the conflict.
    """

    field: str = Field(description="Column name where the conflict occurs")
    file_a: str = Field(description="First file involved in the conflict")
    file_b: str = Field(description="Second file involved in the conflict")
    type_a: str = Field(description="Column dtype in file_a")
    type_b: str = Field(description="Column dtype in file_b")
    message: str = Field(description="Human-readable conflict description")


class MergeValidationResult(ZernaBaseModel):
    """Result of validating schema compatibility across multiple files.

    Attributes:
        compatible: True if all schemas are compatible for merge.
        conflicts: List of field-level conflicts found (empty when compatible).
        merged_schema: Union of all column schemas when compatible, None otherwise.
    """

    compatible: bool = Field(description="Whether schemas are compatible for merge")
    conflicts: list[SchemaConflict] = Field(
        default_factory=list,
        description="Field-level conflicts found across file schemas",
    )
    merged_schema: dict[str, Any] | None = Field(
        default=None,
        description="Merged column schema (union of all columns) when compatible",
    )


# Dtype compatibility groups — types within the same group are considered compatible.
_NUMERIC_TYPES: set[str] = {"float64", "float32", "int64", "int32", "int16", "int8", "uint8"}
_STRING_TYPES: set[str] = {"object", "string", "str", "category"}
_BOOL_TYPES: set[str] = {"bool", "boolean"}

_COMPAT_GROUPS: list[set[str]] = [_NUMERIC_TYPES, _STRING_TYPES, _BOOL_TYPES]


def _types_compatible(type_a: str, type_b: str) -> bool:
    """Check whether two dtype strings are compatible for merge.

    Two types are compatible if they are identical or belong to the same
    compatibility group (e.g. int64 and float64 are both numeric).
    """
    if type_a == type_b:
        return True
    for group in _COMPAT_GROUPS:
        if type_a in group and type_b in group:
            return True
    return False


def _pick_wider_type(type_a: str, type_b: str) -> str:
    """Return the wider / more general type when two compatible types differ.

    For numeric types, float64 is preferred. For string types, object is preferred.
    Falls back to type_a when both are identical.
    """
    if type_a == type_b:
        return type_a
    # Numeric: prefer float64
    if type_a in _NUMERIC_TYPES and type_b in _NUMERIC_TYPES:
        return "float64"
    # String: prefer object
    if type_a in _STRING_TYPES and type_b in _STRING_TYPES:
        return "object"
    return type_a


def validate_merge(file_schemas: list[FileSchema]) -> MergeValidationResult:
    """Validate schema compatibility across multiple files before merge.

    Compares every pair of file schemas and reports field-level conflicts
    where the same column has incompatible dtypes. When all schemas are
    compatible, returns a merged schema that is the union of all columns.

    Args:
        file_schemas: List of per-file schema descriptions.

    Returns:
        MergeValidationResult indicating compatibility, any conflicts,
        and the merged schema when compatible.
    """
    if not file_schemas:
        return MergeValidationResult(compatible=True, conflicts=[], merged_schema={})

    if len(file_schemas) == 1:
        return MergeValidationResult(
            compatible=True,
            conflicts=[],
            merged_schema=dict(file_schemas[0].columns),
        )

    conflicts: list[SchemaConflict] = []

    # Compare every pair of schemas for type conflicts on shared columns
    for i in range(len(file_schemas)):
        for j in range(i + 1, len(file_schemas)):
            schema_a = file_schemas[i]
            schema_b = file_schemas[j]
            shared_cols = set(schema_a.columns) & set(schema_b.columns)
            for col in sorted(shared_cols):
                type_a = schema_a.columns[col]
                type_b = schema_b.columns[col]
                if not _types_compatible(type_a, type_b):
                    conflicts.append(
                        SchemaConflict(
                            field=col,
                            file_a=schema_a.filename,
                            file_b=schema_b.filename,
                            type_a=type_a,
                            type_b=type_b,
                            message=(
                                f"Column '{col}' has incompatible types: "
                                f"'{type_a}' in '{schema_a.filename}' vs "
                                f"'{type_b}' in '{schema_b.filename}'"
                            ),
                        )
                    )

    if conflicts:
        return MergeValidationResult(
            compatible=False,
            conflicts=conflicts,
            merged_schema=None,
        )

    # Build merged schema — union of all columns with widened types
    merged: dict[str, str] = {}
    for schema in file_schemas:
        for col, dtype in schema.columns.items():
            if col in merged:
                merged[col] = _pick_wider_type(merged[col], dtype)
            else:
                merged[col] = dtype

    return MergeValidationResult(
        compatible=True,
        conflicts=[],
        merged_schema=merged,
    )
