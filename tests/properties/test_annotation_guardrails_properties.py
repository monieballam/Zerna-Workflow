"""Property-based tests for annotation guardrails.

# Feature: gap-analysis-and-verification, Property 16: Guardrail violation detection
# Feature: gap-analysis-and-verification, Property 17: Label normalization idempotence
# Feature: gap-analysis-and-verification, Property 18: Annotation columns policy enforcement

**Validates: Requirements 11.1, 11.2, 11.3**
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from methods.annotation.guardrails import (
    ColumnsPolicy,
    OntologyDefinition,
    normalize_label,
    validate,
    validate_columns_policy,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_label_st = st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd", "Zs")),
).filter(lambda s: s.strip() != "")

_cell_id_st = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("L", "N")),
)

_column_name_st = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("L", "N", "Pc")),
)


@st.composite
def _ontology_st(draw):
    """Strategy for an ontology definition with valid labels and hierarchy."""
    n_labels = draw(st.integers(min_value=2, max_value=15))
    labels = list({draw(_label_st) for _ in range(n_labels + 5)})[:n_labels]
    assume(len(labels) >= 2)

    # Build a simple hierarchy: first label is parent, rest are children
    hierarchy: dict[str, list[str]] = {}
    if len(labels) >= 3:
        parent = labels[0]
        children = labels[1 : draw(st.integers(min_value=2, max_value=len(labels)))]
        hierarchy[parent] = children

    return OntologyDefinition(
        name=draw(st.text(min_size=1, max_size=15, alphabet="abcdefghij")),
        valid_labels=set(labels),
        hierarchy=hierarchy,
    )


@st.composite
def _columns_policy_st(draw):
    """Strategy for a columns policy."""
    n_required = draw(st.integers(min_value=1, max_value=5))
    n_optional = draw(st.integers(min_value=0, max_value=3))
    n_protected = draw(st.integers(min_value=1, max_value=5))

    all_cols: list[str] = []
    for _ in range(n_required + n_optional + n_protected + 5):
        col = draw(_column_name_st)
        if col not in all_cols:
            all_cols.append(col)
    assume(len(all_cols) >= n_required + n_optional + n_protected)

    required = all_cols[:n_required]
    optional = all_cols[n_required : n_required + n_optional]
    protected = all_cols[n_required + n_optional : n_required + n_optional + n_protected]

    return ColumnsPolicy(required=required, optional=optional, protected=protected)


# ---------------------------------------------------------------------------
# Property 16: Guardrail violation detection
# ---------------------------------------------------------------------------


class TestGuardrailViolationDetection:
    """Property 16: Guardrail violation detection.

    For any set of annotation labels and an ontology definition, the guardrails
    must flag every label that violates the ontology or hierarchy constraints.
    Labels that conform must pass validation.

    **Validates: Requirements 11.1**
    """

    @given(ontology=_ontology_st(), data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_conforming_labels_pass_validation(
        self,
        ontology: OntologyDefinition,
        data: st.DataObject,
    ) -> None:
        """Labels that are in the ontology's valid_labels set must pass validation.

        **Validates: Requirements 11.1**
        """
        assume(len(ontology.valid_labels) > 0)
        valid_list = sorted(ontology.valid_labels)

        n_cells = data.draw(st.integers(min_value=1, max_value=10))
        labels: dict[str, str] = {}
        for i in range(n_cells):
            cell_id = f"cell_{i}"
            labels[cell_id] = data.draw(st.sampled_from(valid_list))

        result = validate(labels, ontology=ontology)

        # Filter to only ontology_membership violations (hierarchy may still flag)
        ontology_violations = [v for v in result.violations if v.rule == "ontology_membership"]
        assert ontology_violations == [], (
            f"Valid labels should not produce ontology violations: {ontology_violations}"
        )

    @given(ontology=_ontology_st(), data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_invalid_labels_are_flagged(
        self,
        ontology: OntologyDefinition,
        data: st.DataObject,
    ) -> None:
        """Labels NOT in the ontology's valid_labels set must be flagged.

        **Validates: Requirements 11.1**
        """
        assume(len(ontology.valid_labels) > 0)

        # Generate a label guaranteed to not be in the ontology
        invalid_label = data.draw(_label_st.filter(lambda l: l not in ontology.valid_labels))

        labels = {"cell_0": invalid_label}
        result = validate(labels, ontology=ontology)

        assert not result.valid, "Invalid label should cause validation failure"
        ontology_violations = [v for v in result.violations if v.rule == "ontology_membership"]
        flagged_cells = {v.cell_id for v in ontology_violations}
        assert "cell_0" in flagged_cells, (
            f"Cell with invalid label '{invalid_label}' was not flagged"
        )

    @given(ontology=_ontology_st(), data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_mixed_valid_invalid_flags_only_invalid(
        self,
        ontology: OntologyDefinition,
        data: st.DataObject,
    ) -> None:
        """In a mix of valid and invalid labels, only invalid ones are flagged.

        **Validates: Requirements 11.1**
        """
        assume(len(ontology.valid_labels) >= 1)
        valid_list = sorted(ontology.valid_labels)

        valid_label = data.draw(st.sampled_from(valid_list))
        invalid_label = data.draw(_label_st.filter(lambda l: l not in ontology.valid_labels))

        labels = {"valid_cell": valid_label, "invalid_cell": invalid_label}
        result = validate(labels, ontology=ontology)

        ontology_violations = [v for v in result.violations if v.rule == "ontology_membership"]
        flagged_cells = {v.cell_id for v in ontology_violations}

        assert "valid_cell" not in flagged_cells, "Valid label should not be flagged"
        assert "invalid_cell" in flagged_cells, "Invalid label should be flagged"


# ---------------------------------------------------------------------------
# Property 17: Label normalization idempotence
# ---------------------------------------------------------------------------


class TestLabelNormalizationIdempotence:
    """Property 17: Label normalization idempotence.

    For any label string, normalize(normalize(label)) must equal normalize(label).
    The normalized form must be a canonical cell type name.

    **Validates: Requirements 11.2**
    """

    @given(label=_label_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_normalization_is_idempotent(self, label: str) -> None:
        """normalize(normalize(label)) == normalize(label).

        **Validates: Requirements 11.2**
        """
        once = normalize_label(label)
        twice = normalize_label(once)
        assert once == twice, (
            f"Normalization not idempotent: "
            f"normalize('{label}') = '{once}', "
            f"normalize('{once}') = '{twice}'"
        )

    @given(label=_label_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_normalized_form_is_stripped(self, label: str) -> None:
        """Normalized labels must have no leading/trailing whitespace.

        **Validates: Requirements 11.2**
        """
        result = normalize_label(label)
        assert result == result.strip(), f"Normalized label has whitespace: '{result}'"

    @given(
        alias_map=st.dictionaries(
            keys=st.text(min_size=1, max_size=20).map(str.lower),
            values=_label_st,
            min_size=1,
            max_size=10,
        ),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_idempotent_with_custom_alias_map(
        self,
        alias_map: dict[str, str],
        data: st.DataObject,
    ) -> None:
        """Idempotence holds for any custom alias map.

        **Validates: Requirements 11.2**
        """
        # Ensure alias map values are themselves canonical (normalize to themselves)
        # by making values map to themselves in the alias map
        canonical_map: dict[str, str] = {}
        for key, val in alias_map.items():
            clean_val = val.strip()
            if not clean_val:
                continue
            canonical_map[key] = clean_val
            # Ensure the canonical value maps to itself
            canonical_map[clean_val.lower()] = clean_val

        assume(len(canonical_map) > 0)

        label = data.draw(_label_st)
        once = normalize_label(label, alias_map=canonical_map)
        twice = normalize_label(once, alias_map=canonical_map)
        assert once == twice, (
            f"Normalization not idempotent with custom map: "
            f"normalize('{label}') = '{once}', normalize('{once}') = '{twice}'"
        )


# ---------------------------------------------------------------------------
# Property 18: Annotation columns policy enforcement
# ---------------------------------------------------------------------------


class TestAnnotationColumnsPolicyEnforcement:
    """Property 18: Annotation columns policy enforcement.

    For any annotation operation, required columns must be present in the output,
    and protected columns must not be modified from their pre-annotation values.

    **Validates: Requirements 11.3**
    """

    @given(policy=_columns_policy_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_missing_required_columns_are_flagged(
        self,
        policy: ColumnsPolicy,
    ) -> None:
        """When required columns are missing from output, violations are reported.

        **Validates: Requirements 11.3**
        """
        assume(len(policy.required) > 0)

        # Output has none of the required columns
        output_columns: set[str] = set(policy.optional)

        violations = validate_columns_policy(
            output_columns=output_columns,
            pre_annotation_values={},
            post_annotation_values={},
            policy=policy,
        )

        missing_violations = [v for v in violations if v.rule == "required_column_missing"]
        flagged_cols = {v.message.split("'")[1] for v in missing_violations}

        for col in policy.required:
            if col not in output_columns:
                assert col in flagged_cols, f"Missing required column '{col}' was not flagged"

    @given(policy=_columns_policy_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_all_required_present_no_required_violations(
        self,
        policy: ColumnsPolicy,
    ) -> None:
        """When all required columns are present, no required-column violations.

        **Validates: Requirements 11.3**
        """
        output_columns = set(policy.required) | set(policy.optional)

        violations = validate_columns_policy(
            output_columns=output_columns,
            pre_annotation_values={},
            post_annotation_values={},
            policy=policy,
        )

        required_violations = [v for v in violations if v.rule == "required_column_missing"]
        assert required_violations == [], (
            f"Should have no required-column violations: {required_violations}"
        )

    @given(policy=_columns_policy_st(), data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_modified_protected_columns_are_flagged(
        self,
        policy: ColumnsPolicy,
        data: st.DataObject,
    ) -> None:
        """When protected columns are modified, violations are reported.

        **Validates: Requirements 11.3**
        """
        assume(len(policy.protected) > 0)

        cell_id = "cell_0"
        # Pick a protected column and give it different pre/post values
        protected_col = data.draw(st.sampled_from(policy.protected))

        pre_values = {cell_id: {protected_col: "original_value"}}
        post_values = {cell_id: {protected_col: "modified_value"}}

        output_columns = set(policy.required) | {protected_col}

        violations = validate_columns_policy(
            output_columns=output_columns,
            pre_annotation_values=pre_values,
            post_annotation_values=post_values,
            policy=policy,
        )

        protected_violations = [v for v in violations if v.rule == "protected_column_modified"]
        assert len(protected_violations) > 0, (
            f"Modified protected column '{protected_col}' was not flagged"
        )
        assert any(v.cell_id == cell_id for v in protected_violations)

    @given(policy=_columns_policy_st(), data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_unmodified_protected_columns_pass(
        self,
        policy: ColumnsPolicy,
        data: st.DataObject,
    ) -> None:
        """When protected columns are unchanged, no protected-column violations.

        **Validates: Requirements 11.3**
        """
        assume(len(policy.protected) > 0)

        cell_id = "cell_0"
        # All protected columns have same pre and post values
        pre_values: dict[str, dict[str, str]] = {cell_id: {}}
        post_values: dict[str, dict[str, str]] = {cell_id: {}}
        for col in policy.protected:
            val = data.draw(st.text(min_size=1, max_size=10))
            pre_values[cell_id][col] = val
            post_values[cell_id][col] = val

        output_columns = set(policy.required) | set(policy.protected)

        violations = validate_columns_policy(
            output_columns=output_columns,
            pre_annotation_values=pre_values,
            post_annotation_values=post_values,
            policy=policy,
        )

        protected_violations = [v for v in violations if v.rule == "protected_column_modified"]
        assert protected_violations == [], (
            f"Unmodified protected columns should not be flagged: {protected_violations}"
        )


# ---------------------------------------------------------------------------
# Imports for Properties 19-22 (Label Lifecycle)
# ---------------------------------------------------------------------------

from uuid import uuid4

from methods.annotation.label_lifecycle import (
    LabelContract,
    finalize,
    modify_finalized,
    validate_labels,
)

# ---------------------------------------------------------------------------
# Strategies for label lifecycle tests
# ---------------------------------------------------------------------------

_field_name_st = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip() != "")

_uuid_st = st.builds(uuid4)


@st.composite
def _label_contract_st(draw):
    """Strategy for a LabelContract with required fields, types, and allowed labels."""
    n_required = draw(st.integers(min_value=1, max_value=5))
    required_fields: list[str] = []
    for _ in range(n_required + 3):
        f = draw(_field_name_st)
        if f not in required_fields:
            required_fields.append(f)
    required_fields = required_fields[:n_required]
    assume(len(required_fields) >= 1)

    # Ensure "label" is always a required field so allowed_labels checks work
    if "label" not in required_fields:
        required_fields.append("label")

    field_types: dict[str, str] = {}
    for f in required_fields:
        if f == "label":
            field_types[f] = "str"
        else:
            field_types[f] = draw(st.sampled_from(["str", "int", "float"]))

    use_allowed = draw(st.booleans())
    allowed_labels: list[str] | None = None
    if use_allowed:
        n_allowed = draw(st.integers(min_value=2, max_value=10))
        allowed_labels = list({draw(_label_st) for _ in range(n_allowed + 3)})[:n_allowed]
        assume(len(allowed_labels) >= 2)

    return LabelContract(
        required_fields=required_fields,
        field_types=field_types,
        allowed_labels=allowed_labels,
        hierarchy_constraints={},
    )


@st.composite
def _valid_label_records_st(draw, contract: LabelContract):
    """Strategy for label records that fully satisfy a contract."""
    n_cells = draw(st.integers(min_value=1, max_value=5))
    records: dict[str, dict] = {}
    for i in range(n_cells):
        cell_id = f"cell_{i}"
        record: dict = {}
        for field in contract.required_fields:
            expected_type = contract.field_types.get(field, "str")
            if expected_type == "str":
                if field == "label" and contract.allowed_labels:
                    record[field] = draw(st.sampled_from(contract.allowed_labels))
                else:
                    record[field] = draw(st.text(min_size=1, max_size=15, alphabet="abcdefghij"))
            elif expected_type == "int":
                record[field] = draw(st.integers(min_value=0, max_value=1000))
            elif expected_type == "float":
                record[field] = draw(st.floats(min_value=0.0, max_value=100.0, allow_nan=False))
        records[cell_id] = record
    return records


# ---------------------------------------------------------------------------
# Property 19: Guardrail-blocked finalization
# ---------------------------------------------------------------------------


class TestGuardrailBlockedFinalization:
    """Property 19: Guardrail-blocked finalization.

    For any set of labels with at least one guardrail violation, the finalization
    step must reject the labels and return the violation details.

    # Feature: gap-analysis-and-verification, Property 19: Guardrail-blocked finalization

    **Validates: Requirements 11.4**
    """

    @given(ontology=_ontology_st(), data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_finalization_rejected_when_guardrail_violations_exist(
        self,
        ontology: OntologyDefinition,
        data: st.DataObject,
    ) -> None:
        """Labels with guardrail violations must not be finalized.

        **Validates: Requirements 11.4**
        """
        assume(len(ontology.valid_labels) > 0)

        # Create labels with at least one invalid label
        invalid_label = data.draw(_label_st.filter(lambda l: l not in ontology.valid_labels))
        labels = {"cell_0": invalid_label}

        # Run guardrail validation
        guardrail_result = validate(labels, ontology=ontology)
        assume(not guardrail_result.valid)

        user = data.draw(_uuid_st)

        # Finalization must raise ValueError
        with pytest.raises(ValueError) as exc_info:
            finalize(labels, user, guardrail_result=guardrail_result)

        error_msg = str(exc_info.value)
        assert "violation" in error_msg.lower(), (
            f"Error message should mention violations: {error_msg}"
        )

    @given(ontology=_ontology_st(), data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_finalization_succeeds_when_no_guardrail_violations(
        self,
        ontology: OntologyDefinition,
        data: st.DataObject,
    ) -> None:
        """Labels without guardrail violations can be finalized.

        **Validates: Requirements 11.4**
        """
        assume(len(ontology.valid_labels) > 0)
        valid_list = sorted(ontology.valid_labels)

        n_cells = data.draw(st.integers(min_value=1, max_value=5))
        labels: dict[str, str] = {}
        for i in range(n_cells):
            labels[f"cell_{i}"] = data.draw(st.sampled_from(valid_list))

        guardrail_result = validate(labels, ontology=ontology)
        assume(guardrail_result.valid)

        user = data.draw(_uuid_st)
        result = finalize(labels, user, guardrail_result=guardrail_result)

        assert result.locked is True
        assert result.labels == labels


# ---------------------------------------------------------------------------
# Property 20: Label contract validation completeness
# ---------------------------------------------------------------------------


class TestLabelContractValidationCompleteness:
    """Property 20: Label contract validation completeness.

    For any set of labels, validation against the label contract must report
    all violations (missing fields, wrong types, disallowed labels) — not just
    the first one found.

    # Feature: gap-analysis-and-verification, Property 20: Label contract validation completeness

    **Validates: Requirements 12.1, 12.2, 12.5**
    """

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_all_missing_fields_reported(self, data: st.DataObject) -> None:
        """Every missing required field must appear in the violation report.

        **Validates: Requirements 12.1, 12.5**
        """
        contract = data.draw(_label_contract_st())

        # Create a record with NO required fields
        labels = {"cell_0": {"extra_field": "value"}}

        report = validate_labels(labels, contract)

        assert not report.valid
        missing_violations = [v for v in report.violations if v.violation_type == "missing_field"]
        missing_fields = {v.field for v in missing_violations}

        for field in contract.required_fields:
            assert field in missing_fields, (
                f"Missing field '{field}' was not reported. Reported: {missing_fields}"
            )

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_wrong_types_reported(self, data: st.DataObject) -> None:
        """Every field with the wrong type must appear in the violation report.

        **Validates: Requirements 12.2, 12.5**
        """
        contract = data.draw(_label_contract_st())

        # Build a record where every typed field has the wrong type
        record: dict = {}
        expected_wrong: set[str] = set()
        for field, type_name in contract.field_types.items():
            if type_name == "str":
                record[field] = 42  # wrong: int instead of str
                expected_wrong.add(field)
            elif type_name == "int":
                record[field] = "not_an_int"  # wrong: str instead of int
                expected_wrong.add(field)
            elif type_name == "float":
                record[field] = "not_a_float"  # wrong: str instead of float
                expected_wrong.add(field)

        assume(len(expected_wrong) > 0)
        labels = {"cell_0": record}

        report = validate_labels(labels, contract)

        type_violations = [v for v in report.violations if v.violation_type == "wrong_type"]
        flagged_fields = {v.field for v in type_violations}

        for field in expected_wrong:
            assert field in flagged_fields, (
                f"Wrong-type field '{field}' was not reported. Reported: {flagged_fields}"
            )

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_disallowed_labels_reported(self, data: st.DataObject) -> None:
        """Labels not in the allowed list must be reported.

        **Validates: Requirements 12.1, 12.5**
        """
        contract = data.draw(_label_contract_st())
        assume(contract.allowed_labels is not None)
        assume(len(contract.allowed_labels) > 0)

        # Create a label that is NOT in the allowed list
        disallowed = data.draw(_label_st.filter(lambda l: l not in contract.allowed_labels))

        # Build a valid record except for the disallowed label
        record: dict = {}
        for field in contract.required_fields:
            type_name = contract.field_types.get(field, "str")
            if field == "label":
                record[field] = disallowed
            elif type_name == "str":
                record[field] = "valid"
            elif type_name == "int":
                record[field] = 1
            elif type_name == "float":
                record[field] = 1.0

        labels = {"cell_0": record}
        report = validate_labels(labels, contract)

        disallowed_violations = [
            v for v in report.violations if v.violation_type == "disallowed_label"
        ]
        assert len(disallowed_violations) > 0, f"Disallowed label '{disallowed}' was not reported"

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_records_pass(self, data: st.DataObject) -> None:
        """Records that satisfy the contract must produce no violations.

        **Validates: Requirements 12.1, 12.2, 12.5**
        """
        contract = data.draw(_label_contract_st())
        records = data.draw(_valid_label_records_st(contract))

        report = validate_labels(records, contract)

        assert report.valid, (
            f"Valid records should pass validation. Violations: {report.violations}"
        )


# ---------------------------------------------------------------------------
# Property 21: Finalization locks labels
# ---------------------------------------------------------------------------


class TestFinalizationLocksLabels:
    """Property 21: Finalization locks labels.

    For any finalized label set, the result must have locked=True, a non-null
    finalized_at timestamp, and a non-null finalized_by user ID.

    # Feature: gap-analysis-and-verification, Property 21: Finalization locks labels

    **Validates: Requirements 12.3**
    """

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_finalized_labels_are_locked(self, data: st.DataObject) -> None:
        """Finalized labels must have locked=True, non-null finalized_at and finalized_by.

        **Validates: Requirements 12.3**
        """
        n_cells = data.draw(st.integers(min_value=1, max_value=10))
        labels: dict[str, str] = {}
        for i in range(n_cells):
            labels[f"cell_{i}"] = data.draw(st.text(min_size=1, max_size=20, alphabet="abcdefghij"))

        user = data.draw(_uuid_st)
        version = data.draw(st.integers(min_value=1, max_value=100))

        result = finalize(labels, user, version=version)

        assert result.locked is True, "Finalized labels must be locked"
        assert result.finalized_at is not None, "finalized_at must not be None"
        assert result.finalized_by is not None, "finalized_by must not be None"
        assert result.finalized_by == user, "finalized_by must match the user"
        assert result.version == version, "version must match"
        assert result.labels == labels, "labels must match input"


# ---------------------------------------------------------------------------
# Property 22: Post-finalize modification guard
# ---------------------------------------------------------------------------


class TestPostFinalizeModificationGuard:
    """Property 22: Post-finalize modification guard.

    For any finalized label set, attempting to modify labels without incrementing
    the version number must fail. Modification with a version increment must succeed.

    # Feature: gap-analysis-and-verification, Property 22: Post-finalize modification guard

    **Validates: Requirements 12.4**
    """

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_modification_without_version_increment_fails(self, data: st.DataObject) -> None:
        """Modifying finalized labels with same or lower version must fail.

        **Validates: Requirements 12.4**
        """
        labels = {"cell_0": data.draw(_label_st)}
        user = data.draw(_uuid_st)
        version = data.draw(st.integers(min_value=1, max_value=50))

        finalized = finalize(labels, user, version=version)

        new_labels = {"cell_0": data.draw(_label_st)}
        # Use same version (no increment)
        same_version = version
        result = modify_finalized(finalized, new_labels, same_version, user)

        assert not result.success, "Modification without version increment should fail"

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_modification_with_lower_version_fails(self, data: st.DataObject) -> None:
        """Modifying finalized labels with a lower version must fail.

        **Validates: Requirements 12.4**
        """
        labels = {"cell_0": data.draw(_label_st)}
        user = data.draw(_uuid_st)
        version = data.draw(st.integers(min_value=2, max_value=50))

        finalized = finalize(labels, user, version=version)

        new_labels = {"cell_0": data.draw(_label_st)}
        lower_version = data.draw(st.integers(min_value=1, max_value=version - 1))
        result = modify_finalized(finalized, new_labels, lower_version, user)

        assert not result.success, "Modification with lower version should fail"

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_modification_with_version_increment_succeeds(self, data: st.DataObject) -> None:
        """Modifying finalized labels with a higher version must succeed.

        **Validates: Requirements 12.4**
        """
        labels = {"cell_0": data.draw(_label_st)}
        user = data.draw(_uuid_st)
        version = data.draw(st.integers(min_value=1, max_value=50))

        finalized = finalize(labels, user, version=version)

        new_labels = {"cell_0": data.draw(_label_st)}
        new_version = version + data.draw(st.integers(min_value=1, max_value=10))
        result = modify_finalized(finalized, new_labels, new_version, user)

        assert result.success, (
            f"Modification with version increment should succeed: {result.message}"
        )
        assert result.updated_labels is not None
        assert result.updated_labels.version == new_version
        assert result.updated_labels.locked is True
        assert result.updated_labels.labels == new_labels
