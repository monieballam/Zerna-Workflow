"""Property-based tests for the programs registry.

# Feature: gap-analysis-and-verification, Property 44: Programs registry round-trip
# Feature: gap-analysis-and-verification, Property 45: Program selection applies correct defaults

**Validates: Requirements 23.1, 23.4**
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from methods.programs.registry import (
    ProgramConfig,
    apply_program_defaults,
    get_program,
    list_programs,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_registered_cancer_type_st = st.sampled_from(["general", "prostate"])


# ---------------------------------------------------------------------------
# Property 44: Programs registry round-trip
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestProgramsRegistryRoundTrip:
    """Property 44: Programs registry round-trip.

    For any registered program configuration, retrieving it by cancer type
    must return the same marker panels, hierarchy mappings, and default
    parameters.

    **Validates: Requirements 23.1**
    """

    @given(cancer_type=_registered_cancer_type_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_round_trip_returns_same_config(self, cancer_type: str) -> None:
        """# Feature: gap-analysis-and-verification, Property 44: Programs registry round-trip"""
        # Retrieve the program twice — both calls must return identical data.
        first = get_program(cancer_type)
        second = get_program(cancer_type)

        assert isinstance(first, ProgramConfig)
        assert isinstance(second, ProgramConfig)

        assert first.cancer_type == cancer_type
        assert second.cancer_type == cancer_type

        assert first.marker_panels == second.marker_panels
        assert first.hierarchy_mappings == second.hierarchy_mappings
        assert first.default_parameters == second.default_parameters

    @given(cancer_type=_registered_cancer_type_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_retrieved_config_appears_in_list(self, cancer_type: str) -> None:
        """A retrieved program must also appear in list_programs()."""
        program = get_program(cancer_type)
        all_programs = list_programs()

        matching = [p for p in all_programs if p.cancer_type == cancer_type]
        assert len(matching) == 1
        assert matching[0].marker_panels == program.marker_panels
        assert matching[0].hierarchy_mappings == program.hierarchy_mappings
        assert matching[0].default_parameters == program.default_parameters

    @given(cancer_type=_registered_cancer_type_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_marker_panels_non_empty(self, cancer_type: str) -> None:
        """Every registered program must have at least one marker panel."""
        program = get_program(cancer_type)
        assert len(program.marker_panels) > 0

    @given(cancer_type=_registered_cancer_type_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_hierarchy_mappings_non_empty(self, cancer_type: str) -> None:
        """Every registered program must have at least one hierarchy mapping."""
        program = get_program(cancer_type)
        assert len(program.hierarchy_mappings) > 0


# ---------------------------------------------------------------------------
# Property 45: Program selection applies correct defaults
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestProgramSelectionAppliesCorrectDefaults:
    """Property 45: Program selection applies correct defaults.

    For any selected cancer program, the pipeline configuration must use
    that program's marker panels and default parameters.

    **Validates: Requirements 23.4**
    """

    @given(cancer_type=_registered_cancer_type_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_applied_defaults_match_program(self, cancer_type: str) -> None:
        """# Feature: gap-analysis-and-verification, Property 45: Program selection applies correct defaults"""
        program = get_program(cancer_type)
        config = apply_program_defaults(cancer_type)

        assert config["cancer_type"] == cancer_type
        assert config["marker_panels"] == program.marker_panels
        assert config["default_parameters"] == program.default_parameters

    @given(cancer_type=_registered_cancer_type_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_applied_defaults_contain_required_keys(self, cancer_type: str) -> None:
        """Pipeline config must contain cancer_type, marker_panels, and default_parameters."""
        config = apply_program_defaults(cancer_type)

        assert "cancer_type" in config
        assert "marker_panels" in config
        assert "default_parameters" in config

    @given(cancer_type=_registered_cancer_type_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_default_parameters_non_empty(self, cancer_type: str) -> None:
        """Applied default parameters must be non-empty."""
        config = apply_program_defaults(cancer_type)
        assert len(config["default_parameters"]) > 0
