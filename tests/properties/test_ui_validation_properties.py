"""Property-based tests for obs schema validation.

# Feature: gap-analysis-and-verification, Property 48: Obs schema validation

**Validates: Requirements 25.6**
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from methods.data.obs_schema_validator import (
    _types_compatible,
    validate_obs_schema,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_DTYPES = ["float64", "int64", "object", "bool", "category"]

_column_name_st = st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
).filter(lambda s: s.strip() != "")

_dtype_st = st.sampled_from(_DTYPES)

_schema_st = st.dictionaries(
    keys=_column_name_st,
    values=_dtype_st,
    min_size=1,
    max_size=15,
)


# ---------------------------------------------------------------------------
# Property 48: Obs schema validation
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestObsSchemaValidation:
    """Property 48: Obs schema validation.

    For any .obs DataFrame schema, the inspector must correctly identify
    missing required columns and type mismatches against the expected schema.
    """

    @given(expected=_schema_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_matching_schema_is_valid(self, expected: dict[str, str]) -> None:
        """# Feature: gap-analysis-and-verification, Property 48: Obs schema validation

        When actual schema matches expected, result must be valid with no issues.
        """
        result = validate_obs_schema(
            actual_schema=dict(expected),
            expected_schema=expected,
        )
        assert result.valid is True, f"Expected valid but got issues: {result.issues}"
        assert result.issues == []

    @given(
        expected=_schema_st,
        extra_cols=st.dictionaries(
            keys=_column_name_st,
            values=_dtype_st,
            min_size=0,
            max_size=5,
        ),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_missing_columns_detected(
        self,
        expected: dict[str, str],
        extra_cols: dict[str, str],
    ) -> None:
        """Missing required columns must each produce a 'missing' issue."""
        # Build actual schema that is missing some expected columns
        # Keep only columns NOT in expected (plus extra)
        actual = dict(extra_cols)

        result = validate_obs_schema(
            actual_schema=actual,
            expected_schema=expected,
        )

        # Every expected column not in actual must appear as a missing issue
        missing_expected = {col for col in expected if col not in actual}
        missing_issues = {issue.column for issue in result.issues if issue.issue_type == "missing"}

        assert missing_expected == missing_issues, (
            f"Expected missing columns {missing_expected} but got {missing_issues}"
        )

        if missing_expected:
            assert result.valid is False

    @given(expected=_schema_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_type_mismatches_detected(self, expected: dict[str, str]) -> None:
        """Type mismatches must each produce a 'type_mismatch' issue."""
        # Build actual schema with deliberately wrong types
        incompatible_map = {
            "float64": "bool",
            "int64": "object",
            "object": "float64",
            "bool": "int64",
            "category": "float64",
        }

        actual = {col: incompatible_map.get(dtype, "object") for col, dtype in expected.items()}

        result = validate_obs_schema(
            actual_schema=actual,
            expected_schema=expected,
        )

        mismatch_issues = {
            issue.column for issue in result.issues if issue.issue_type == "type_mismatch"
        }

        # Every column should have a type mismatch
        for col, dtype in expected.items():
            actual_dtype = actual[col]
            if not _types_compatible(dtype, actual_dtype):
                assert col in mismatch_issues, (
                    f"Column '{col}' expected={dtype} actual={actual_dtype} "
                    f"should be a type_mismatch but was not reported"
                )

        if mismatch_issues:
            assert result.valid is False

    @given(
        expected=_schema_st,
        actual_extra=st.dictionaries(
            keys=_column_name_st,
            values=_dtype_st,
            min_size=0,
            max_size=5,
        ),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_extra_columns_do_not_cause_issues(
        self,
        expected: dict[str, str],
        actual_extra: dict[str, str],
    ) -> None:
        """Extra columns in actual that are not in expected must not cause issues."""
        # Actual has all expected columns (matching types) plus extras
        actual = dict(expected)
        for col, dtype in actual_extra.items():
            if col not in actual:
                actual[col] = dtype

        result = validate_obs_schema(
            actual_schema=actual,
            expected_schema=expected,
        )

        assert result.valid is True, (
            f"Extra columns should not cause issues but got: {result.issues}"
        )
        assert result.issues == []

    @given(expected=_schema_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_issue_fields_are_populated(self, expected: dict[str, str]) -> None:
        """Every issue must have column, issue_type, and message populated."""
        # Empty actual to guarantee missing issues
        result = validate_obs_schema(
            actual_schema={},
            expected_schema=expected,
        )

        assert len(result.issues) == len(expected)
        for issue in result.issues:
            assert issue.column, "Issue column must be non-empty"
            assert issue.issue_type in ("missing", "type_mismatch"), (
                f"Unknown issue_type: {issue.issue_type}"
            )
            assert issue.message, "Issue message must be non-empty"
