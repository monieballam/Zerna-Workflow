"""Property-based tests for merge validation and conflict detection.

# Feature: gap-analysis-and-verification, Property 2: Merge validation detects schema conflicts

**Validates: Requirements 1.4, 1.6**
"""

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from apps.api.services.merge_validator import (
    _BOOL_TYPES,
    _NUMERIC_TYPES,
    _STRING_TYPES,
    FileSchema,
    validate_merge,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Dtype pools — each pool is internally compatible, but cross-pool is incompatible
numeric_dtype = st.sampled_from(sorted(_NUMERIC_TYPES))
string_dtype = st.sampled_from(sorted(_STRING_TYPES))
bool_dtype = st.sampled_from(sorted(_BOOL_TYPES))

all_dtypes = st.sampled_from(sorted(_NUMERIC_TYPES | _STRING_TYPES | _BOOL_TYPES))

column_name = st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
)

filename = st.text(
    min_size=1,
    max_size=40,
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-."),
)

# A schema dict: column_name -> dtype
schema_columns = st.dictionaries(
    keys=column_name,
    values=all_dtypes,
    min_size=1,
    max_size=15,
)

file_schema_st = st.builds(
    FileSchema,
    filename=filename,
    columns=schema_columns,
)


def _make_incompatible_pair() -> st.SearchStrategy:
    """Strategy that produces two dtypes from different compatibility groups."""
    return st.one_of(
        st.tuples(numeric_dtype, string_dtype),
        st.tuples(numeric_dtype, bool_dtype),
        st.tuples(string_dtype, bool_dtype),
    )


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestMergeValidationDetectsSchemaConflicts:
    """Property 2: Merge validation detects schema conflicts.

    For any pair of dataset schemas, if they have incompatible column types,
    the merge validator should report compatible=False with a non-empty list
    of SchemaConflict entries. If schemas are compatible, it should report
    compatible=True with an empty conflict list.
    """

    @given(
        col=column_name,
        type_a=numeric_dtype,
        type_b=string_dtype,
        fname_a=filename,
        fname_b=filename,
    )
    @settings(max_examples=100)
    def test_incompatible_types_detected(
        self,
        col: str,
        type_a: str,
        type_b: str,
        fname_a: str,
        fname_b: str,
    ) -> None:
        """For any pair of schemas sharing a column with incompatible types,
        validate_merge must return compatible=False with at least one conflict
        referencing that column.

        **Validates: Requirements 1.4, 1.6**
        """
        assume(fname_a != fname_b)

        schema_a = FileSchema(filename=fname_a, columns={col: type_a})
        schema_b = FileSchema(filename=fname_b, columns={col: type_b})

        result = validate_merge([schema_a, schema_b])

        assert result.compatible is False
        assert len(result.conflicts) >= 1
        assert result.merged_schema is None

        # The conflict must reference the specific column and files
        conflict_fields = {c.field for c in result.conflicts}
        assert col in conflict_fields

        # Each conflict must have an actionable message
        for conflict in result.conflicts:
            assert len(conflict.message) > 0
            assert conflict.field == col
            assert conflict.type_a != "" and conflict.type_b != ""

    @given(
        cols=st.dictionaries(
            keys=column_name,
            values=numeric_dtype,
            min_size=1,
            max_size=10,
        ),
        fname_a=filename,
        fname_b=filename,
    )
    @settings(max_examples=100)
    def test_compatible_schemas_pass(
        self,
        cols: dict[str, str],
        fname_a: str,
        fname_b: str,
    ) -> None:
        """For any pair of schemas where shared columns have compatible types,
        validate_merge must return compatible=True with an empty conflict list
        and a non-None merged_schema.

        **Validates: Requirements 1.4, 1.6**
        """
        assume(fname_a != fname_b)

        # Both schemas share the same columns with compatible (numeric) types
        schema_a = FileSchema(filename=fname_a, columns=cols)
        schema_b = FileSchema(filename=fname_b, columns=cols)

        result = validate_merge([schema_a, schema_b])

        assert result.compatible is True
        assert result.conflicts == []
        assert result.merged_schema is not None
        # Merged schema must contain all columns from both schemas
        assert set(result.merged_schema.keys()) == set(cols.keys())

    @given(
        shared_col=column_name,
        type_a=numeric_dtype,
        type_b=string_dtype,
        extra_cols_a=st.dictionaries(keys=column_name, values=all_dtypes, max_size=5),
        extra_cols_b=st.dictionaries(keys=column_name, values=all_dtypes, max_size=5),
        fname_a=filename,
        fname_b=filename,
    )
    @settings(max_examples=100)
    def test_conflict_reports_specific_fields(
        self,
        shared_col: str,
        type_a: str,
        type_b: str,
        extra_cols_a: dict[str, str],
        extra_cols_b: dict[str, str],
        fname_a: str,
        fname_b: str,
    ) -> None:
        """For schemas with a known incompatible shared column, the conflict
        list must reference that specific field with both file names and types.

        **Validates: Requirements 1.6**
        """
        assume(fname_a != fname_b)

        cols_a = {**extra_cols_a, shared_col: type_a}
        cols_b = {**extra_cols_b, shared_col: type_b}

        schema_a = FileSchema(filename=fname_a, columns=cols_a)
        schema_b = FileSchema(filename=fname_b, columns=cols_b)

        result = validate_merge([schema_a, schema_b])

        # Must detect the known incompatible column
        assert result.compatible is False
        matching = [c for c in result.conflicts if c.field == shared_col]
        assert len(matching) >= 1

        for conflict in matching:
            assert conflict.file_a in (fname_a, fname_b)
            assert conflict.file_b in (fname_a, fname_b)
            assert conflict.file_a != conflict.file_b
            assert conflict.type_a != ""
            assert conflict.type_b != ""
            assert shared_col in conflict.message

    @given(schemas=st.lists(file_schema_st, min_size=0, max_size=1))
    @settings(max_examples=100)
    def test_single_or_empty_always_compatible(
        self,
        schemas: list[FileSchema],
    ) -> None:
        """For zero or one file schemas, validate_merge must always return
        compatible=True with no conflicts.

        **Validates: Requirements 1.4**
        """
        result = validate_merge(schemas)

        assert result.compatible is True
        assert result.conflicts == []
        assert result.merged_schema is not None

    @given(
        cols=st.dictionaries(
            keys=column_name,
            values=all_dtypes,
            min_size=1,
            max_size=10,
        ),
        fnames=st.lists(filename, min_size=2, max_size=5, unique=True),
    )
    @settings(max_examples=100)
    def test_identical_schemas_always_compatible(
        self,
        cols: dict[str, str],
        fnames: list[str],
    ) -> None:
        """For any set of schemas with identical columns and types,
        validate_merge must return compatible=True.

        **Validates: Requirements 1.4**
        """
        schemas = [FileSchema(filename=fn, columns=cols) for fn in fnames]

        result = validate_merge(schemas)

        assert result.compatible is True
        assert result.conflicts == []
        assert result.merged_schema is not None
        assert set(result.merged_schema.keys()) == set(cols.keys())
