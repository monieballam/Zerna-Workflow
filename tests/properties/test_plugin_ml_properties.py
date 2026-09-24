"""Property-based tests for the plugin system.

# Feature: gap-analysis-and-verification, Property 46: Plugin registration and contract validation

**Validates: Requirements 24.1, 24.3**
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.api.services.plugin_service import (
    ContractValidationError,
    PluginInfo,
    PluginRegistration,
    PluginService,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_name_st = st.text(
    min_size=1,
    max_size=40,
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
).filter(lambda s: s.strip() != "")

_version_st = st.from_regex(r"[0-9]+\.[0-9]+\.[0-9]+", fullmatch=True)

_property_value_st = st.fixed_dictionaries({"type": st.just("string")})

_properties_st = st.dictionaries(
    keys=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L",))),
    values=_property_value_st,
    min_size=1,
    max_size=5,
)

_valid_contract_st = st.fixed_dictionaries(
    {"type": st.just("object"), "properties": _properties_st}
)


def _make_plugin_def(name: str, version: str, input_contract: dict, output_contract: dict) -> dict:
    return {
        "name": name,
        "version": version,
        "input_contract": input_contract,
        "output_contract": output_contract,
    }


# ---------------------------------------------------------------------------
# Property 46: Plugin registration and contract validation
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestPluginRegistrationAndContractValidation:
    """Property 46: Plugin registration and contract validation.

    For any plugin with valid input/output contracts, registration must
    succeed and the plugin must be retrievable.  For any plugin with
    contracts that violate the platform schema, registration must fail
    with validation errors.

    **Validates: Requirements 24.1, 24.3**
    """

    # -- valid registration -------------------------------------------------

    @given(
        name=_name_st,
        version=_version_st,
        input_contract=_valid_contract_st,
        output_contract=_valid_contract_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_plugin_registers_successfully(
        self,
        name: str,
        version: str,
        input_contract: dict,
        output_contract: dict,
    ) -> None:
        """# Feature: gap-analysis-and-verification, Property 46: Plugin registration and contract validation"""
        svc = PluginService()
        plugin_def = _make_plugin_def(name, version, input_contract, output_contract)

        reg = svc.register(plugin_def)

        assert isinstance(reg, PluginRegistration)
        assert reg.name == name.strip()
        assert reg.version == version.strip()
        assert reg.input_contract == input_contract
        assert reg.output_contract == output_contract
        assert reg.plugin_id is not None
        assert reg.registered_at is not None

    @given(
        name=_name_st,
        version=_version_st,
        input_contract=_valid_contract_st,
        output_contract=_valid_contract_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_registered_plugin_is_retrievable(
        self,
        name: str,
        version: str,
        input_contract: dict,
        output_contract: dict,
    ) -> None:
        """A registered plugin must be retrievable by its plugin_id."""
        svc = PluginService()
        plugin_def = _make_plugin_def(name, version, input_contract, output_contract)

        reg = svc.register(plugin_def)
        retrieved = svc.get_plugin(reg.plugin_id)

        assert retrieved is not None
        assert retrieved.plugin_id == reg.plugin_id
        assert retrieved.name == reg.name
        assert retrieved.version == reg.version

    @given(
        name=_name_st,
        version=_version_st,
        input_contract=_valid_contract_st,
        output_contract=_valid_contract_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_registered_plugin_appears_in_list(
        self,
        name: str,
        version: str,
        input_contract: dict,
        output_contract: dict,
    ) -> None:
        """A registered plugin must appear in list_plugins()."""
        svc = PluginService()
        plugin_def = _make_plugin_def(name, version, input_contract, output_contract)

        reg = svc.register(plugin_def)
        plugins = svc.list_plugins()

        assert len(plugins) == 1
        info = plugins[0]
        assert isinstance(info, PluginInfo)
        assert info.plugin_id == reg.plugin_id
        assert info.name == reg.name
        assert info.version == reg.version

    # -- invalid contracts --------------------------------------------------

    @given(name=_name_st, version=_version_st, output_contract=_valid_contract_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_missing_type_in_input_contract_fails(
        self,
        name: str,
        version: str,
        output_contract: dict,
    ) -> None:
        """Input contract missing 'type' must fail validation."""
        svc = PluginService()
        bad_input = {"properties": {"a": {"type": "string"}}}
        plugin_def = _make_plugin_def(name, version, bad_input, output_contract)

        with pytest.raises(ContractValidationError) as exc_info:
            svc.register(plugin_def)

        assert any("type" in e for e in exc_info.value.errors)

    @given(name=_name_st, version=_version_st, input_contract=_valid_contract_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_missing_properties_in_output_contract_fails(
        self,
        name: str,
        version: str,
        input_contract: dict,
    ) -> None:
        """Output contract missing 'properties' must fail validation."""
        svc = PluginService()
        bad_output = {"type": "object"}
        plugin_def = _make_plugin_def(name, version, input_contract, bad_output)

        with pytest.raises(ContractValidationError) as exc_info:
            svc.register(plugin_def)

        assert any("properties" in e for e in exc_info.value.errors)

    @given(name=_name_st, version=_version_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_empty_properties_in_contract_fails(
        self,
        name: str,
        version: str,
    ) -> None:
        """Contract with empty 'properties' dict must fail validation."""
        svc = PluginService()
        bad_contract = {"type": "object", "properties": {}}
        plugin_def = _make_plugin_def(name, version, bad_contract, bad_contract)

        with pytest.raises(ContractValidationError) as exc_info:
            svc.register(plugin_def)

        assert len(exc_info.value.errors) > 0


# ---------------------------------------------------------------------------
# Property 47: ML inference provenance logging
# Feature: gap-analysis-and-verification, Property 47: ML inference provenance logging
#
# **Validates: Requirements 24.2, 24.4**
# ---------------------------------------------------------------------------

from apps.api.services.ml_foundation_service import (
    InferenceLog,
    MLFoundationService,
    ModelRecord,
)

# -- Strategies for ML Foundation ------------------------------------------

_model_name_st = st.text(
    min_size=1,
    max_size=40,
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
).filter(lambda s: s.strip() != "")

_model_version_st = st.from_regex(r"[0-9]+\.[0-9]+\.[0-9]+", fullmatch=True)

_input_hash_st = st.text(
    min_size=1,
    max_size=64,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip() != "")

_extra_metadata_st = st.dictionaries(
    keys=st.text(
        min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L",))
    ).filter(lambda k: k not in ("name", "version")),
    values=st.text(min_size=0, max_size=30),
    min_size=0,
    max_size=5,
)


def _make_model_metadata(name: str, version: str, extra: dict) -> dict:
    return {"name": name, "version": version, **extra}


@pytest.mark.property
class TestMLInferenceProvenanceLogging:
    """Property 47: ML inference provenance logging.

    For any ML model inference, the log must contain model_version,
    input_hash, and timestamp.  For any registered model, retrieval must
    return the same version and metadata.

    **Validates: Requirements 24.2, 24.4**
    """

    # -- model registration round-trip --------------------------------------

    @given(
        name=_model_name_st,
        version=_model_version_st,
        extra=_extra_metadata_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_registered_model_returns_same_version_and_metadata(
        self,
        name: str,
        version: str,
        extra: dict,
    ) -> None:
        """# Feature: gap-analysis-and-verification, Property 47: ML inference provenance logging"""
        svc = MLFoundationService()
        meta = _make_model_metadata(name, version, extra)

        record = svc.register_model(meta)

        assert isinstance(record, ModelRecord)
        assert record.name == name.strip()
        assert record.version == version.strip()
        assert record.metadata == extra
        assert record.model_id is not None
        assert record.registered_at is not None

    @given(
        name=_model_name_st,
        version=_model_version_st,
        extra=_extra_metadata_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_registered_model_is_retrievable(
        self,
        name: str,
        version: str,
        extra: dict,
    ) -> None:
        """Registered model must be retrievable by model_id with same data."""
        svc = MLFoundationService()
        meta = _make_model_metadata(name, version, extra)

        record = svc.register_model(meta)
        retrieved = svc.get_model(record.model_id)

        assert retrieved is not None
        assert retrieved.model_id == record.model_id
        assert retrieved.name == record.name
        assert retrieved.version == record.version
        assert retrieved.metadata == record.metadata

    # -- inference provenance -----------------------------------------------

    @given(
        name=_model_name_st,
        version=_model_version_st,
        extra=_extra_metadata_st,
        input_hash=_input_hash_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_inference_log_contains_required_provenance_fields(
        self,
        name: str,
        version: str,
        extra: dict,
        input_hash: str,
    ) -> None:
        """# Feature: gap-analysis-and-verification, Property 47: ML inference provenance logging

        Every inference log must contain model_version, input_hash, and timestamp.
        """
        svc = MLFoundationService()
        meta = _make_model_metadata(name, version, extra)
        record = svc.register_model(meta)

        log = svc.log_inference(record.model_id, input_hash)

        assert isinstance(log, InferenceLog)
        assert log.model_version == version.strip()
        assert log.input_hash == input_hash.strip()
        assert log.timestamp is not None
        assert log.inference_id is not None
        assert log.model_id == record.model_id

    @given(
        name=_model_name_st,
        version=_model_version_st,
        extra=_extra_metadata_st,
        input_hash=_input_hash_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_inference_log_is_retrievable(
        self,
        name: str,
        version: str,
        extra: dict,
        input_hash: str,
    ) -> None:
        """Logged inference must be retrievable by inference_id."""
        svc = MLFoundationService()
        meta = _make_model_metadata(name, version, extra)
        record = svc.register_model(meta)

        log = svc.log_inference(record.model_id, input_hash)
        retrieved = svc.get_inference(log.inference_id)

        assert retrieved is not None
        assert retrieved.inference_id == log.inference_id
        assert retrieved.model_version == log.model_version
        assert retrieved.input_hash == log.input_hash
        assert retrieved.timestamp == log.timestamp
