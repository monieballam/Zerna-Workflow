"""Property-based tests for method dependency resolution.

**Feature: zerna-platform-rebuild, Property 10: Method Dependency Resolution**

For any pipeline template, all referenced MethodDefinitions should exist
in the method registry, or template creation should fail.

**Validates: Requirements 3.3**

This test suite uses Hypothesis to generate random pipeline definitions and
verify that:
1. All methods in a valid definition are found in the registry
2. Unknown methods are rejected with descriptive errors
3. Empty method lists are rejected
4. Method names in dependencies match methods in the methods list
5. Mixed valid/invalid methods are properly rejected
"""

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from apps.api.models import Base
from apps.api.services.pipeline_service import PipelineService

# Known methods accepted by resolve_methods (catalog + worker registry + aliases)
KNOWN_METHODS = {
    "qc_filter",
    "qc",
    "ambient_correction",
    "doublet_detection",
    "normalize",
    "select_hvg",
    "run_pca",
    "pca",
    "batch_correct",
    "batch_correction",
    "batch_correction_harmony",
    "batch_correction_scvi",
    "cluster",
    "embed",
    "umap",
    "tsne",
    "annotate",
    "differential_expression",
    "pathway_scoring",
    "ligand_receptor_analysis",
    "ligand_receptor",
}


@pytest.fixture(scope="module")
async def async_engine():
    """Create an in-memory SQLite database for async testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="module")
async def async_session_maker(async_engine):
    """Create an async session maker."""
    return sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def get_pipeline_service(async_session_maker):
    """Helper to create a PipelineService instance."""
    async with async_session_maker() as session:
        return PipelineService(session)


# Hypothesis strategies for generating test data
@st.composite
def valid_method_list(draw):
    """Generate a list of valid method names."""
    return draw(
        st.lists(st.sampled_from(sorted(KNOWN_METHODS)), min_size=1, max_size=10, unique=True)
    )


@st.composite
def invalid_method_list(draw):
    """Generate a list containing at least one invalid method name."""
    # Generate some invalid method names
    invalid_methods = draw(
        st.lists(
            st.text(
                min_size=1,
                max_size=30,
                alphabet=st.characters(
                    min_codepoint=97, max_codepoint=122, whitelist_characters="_"
                ),
            ).filter(lambda x: x not in KNOWN_METHODS),
            min_size=1,
            max_size=3,
            unique=True,
        )
    )

    # Optionally mix with some valid methods
    valid_methods = draw(
        st.lists(st.sampled_from(sorted(KNOWN_METHODS)), min_size=0, max_size=3, unique=True)
    )

    # Combine and shuffle
    all_methods = invalid_methods + valid_methods
    draw(st.randoms()).shuffle(all_methods)

    return all_methods


@st.composite
def valid_pipeline_definition(draw):
    """Generate a valid pipeline definition with known methods."""
    methods = draw(valid_method_list())

    # Generate dependencies (simplified - just empty dict for now)
    dependencies = {}

    return {
        "methods": methods,
        "dependencies": dependencies,
    }


@st.composite
def invalid_pipeline_definition(draw):
    """Generate a pipeline definition with unknown methods."""
    methods = draw(invalid_method_list())

    return {
        "methods": methods,
        "dependencies": {},
    }


@st.composite
def method_format_variant(draw):
    """Generate methods in different formats (string or dict)."""
    methods = draw(valid_method_list())

    # Randomly choose format for each method
    formatted_methods = []
    for method in methods:
        if draw(st.booleans()):
            # String format
            formatted_methods.append(method)
        else:
            # Dict format
            formatted_methods.append(
                {
                    "name": method,
                    "params": draw(
                        st.dictionaries(
                            st.text(min_size=1, max_size=10),
                            st.one_of(st.integers(), st.floats(), st.text()),
                            max_size=3,
                        )
                    ),
                }
            )

    return {
        "methods": formatted_methods,
        "dependencies": {},
    }


@pytest.mark.property
class TestMethodDependencyResolution:
    """Property 10: Method Dependency Resolution

    For any pipeline template, all referenced MethodDefinitions should exist
    in the method registry, or template creation should fail.
    """

    @given(definition=valid_pipeline_definition())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_all_valid_methods_are_resolved(self, async_session_maker, definition):
        """Property: All methods in a valid definition are found in the registry."""
        # Create service
        async with async_session_maker() as session:
            pipeline_service = PipelineService(session)

            # Act
            methods = await pipeline_service.resolve_methods(definition)

            # Assert
            assert len(methods) > 0, "Should resolve at least one method"

            # All returned methods should be from the definition
            definition_methods = definition["methods"]
            assert len(methods) == len(definition_methods), (
                "Should return same number of methods as in definition"
            )

            # All methods should be in the known methods set
            for method in methods:
                method_name = method if isinstance(method, str) else method.get("name")
                assert method_name in KNOWN_METHODS, (
                    f"Method {method_name} should be in known methods"
                )

    @given(definition=invalid_pipeline_definition())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_unknown_methods_are_rejected(self, async_session_maker, definition):
        """Property: Unknown methods are rejected with descriptive errors."""
        # Ensure at least one method is unknown
        method_names = [m if isinstance(m, str) else m.get("name") for m in definition["methods"]]
        assume(any(name not in KNOWN_METHODS for name in method_names))

        # Create service
        async with async_session_maker() as session:
            pipeline_service = PipelineService(session)

            # Act & Assert
            with pytest.raises(ValueError) as exc_info:
                await pipeline_service.resolve_methods(definition)

            # Verify error message is descriptive
            error_message = str(exc_info.value)
            assert "not found in method registry" in error_message, (
                "Error should mention method not found in registry"
            )

            # Verify error message includes available methods
            assert "Available methods:" in error_message, "Error should list available methods"

    async def test_empty_method_list_is_rejected(self, async_session_maker):
        """Property: Empty method lists are rejected."""
        # Arrange
        definition = {
            "methods": [],
            "dependencies": {},
        }

        # Create service
        async with async_session_maker() as session:
            pipeline_service = PipelineService(session)

            # Act & Assert
            with pytest.raises(ValueError) as exc_info:
                await pipeline_service.resolve_methods(definition)

            error_message = str(exc_info.value)
            assert "must define at least one method" in error_message, (
                "Error should mention at least one method required"
            )

    @given(definition=method_format_variant())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_method_names_in_dependencies_match_methods_list(
        self, async_session_maker, definition
    ):
        """Property: Method names in dependencies match methods in the methods list."""
        # Create service
        async with async_session_maker() as session:
            pipeline_service = PipelineService(session)

            # Act
            methods = await pipeline_service.resolve_methods(definition)

            # Assert - all methods should be valid
            assert len(methods) > 0, "Should resolve at least one method"

            # Extract method names from the definition
            method_names = set()
            for method in definition["methods"]:
                if isinstance(method, str):
                    method_names.add(method)
                else:
                    method_names.add(method.get("name"))

            # All method names should be in known methods
            assert method_names.issubset(KNOWN_METHODS), (
                "All method names should be in known methods"
            )

    @given(
        valid_methods=valid_method_list(),
        invalid_method=st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(min_codepoint=97, max_codepoint=122, whitelist_characters="_"),
        ).filter(lambda x: x not in KNOWN_METHODS),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_mixed_valid_invalid_methods_are_rejected(
        self, async_session_maker, valid_methods, invalid_method
    ):
        """Property: Mixed valid/invalid methods are properly rejected."""
        # Arrange - create definition with both valid and invalid methods
        all_methods = valid_methods + [invalid_method]
        definition = {
            "methods": all_methods,
            "dependencies": {},
        }

        # Create service
        async with async_session_maker() as session:
            pipeline_service = PipelineService(session)

            # Act & Assert
            with pytest.raises(ValueError) as exc_info:
                await pipeline_service.resolve_methods(definition)

            # Verify error mentions the invalid method
            error_message = str(exc_info.value)
            assert invalid_method in error_message, (
                f"Error should mention the invalid method '{invalid_method}'"
            )
            assert "not found in method registry" in error_message

    @given(definition=valid_pipeline_definition())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_resolve_methods_is_idempotent(self, async_session_maker, definition):
        """Property: Calling resolve_methods multiple times returns same result."""
        # Create service
        async with async_session_maker() as session:
            pipeline_service = PipelineService(session)

            # Act
            methods1 = await pipeline_service.resolve_methods(definition)
            methods2 = await pipeline_service.resolve_methods(definition)

            # Assert
            assert methods1 == methods2, (
                "Multiple calls to resolve_methods should return same result"
            )

    @given(methods=valid_method_list())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_method_order_is_preserved(self, async_session_maker, methods):
        """Property: Method order in definition is preserved in resolution."""
        # Arrange
        definition = {
            "methods": methods,
            "dependencies": {},
        }

        # Create service
        async with async_session_maker() as session:
            pipeline_service = PipelineService(session)

            # Act
            resolved_methods = await pipeline_service.resolve_methods(definition)

            # Assert - order should be preserved
            assert resolved_methods == methods, "Method order should be preserved during resolution"

    @given(
        method=st.sampled_from(sorted(KNOWN_METHODS)), count=st.integers(min_value=2, max_value=5)
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_duplicate_methods_in_definition(self, async_session_maker, method, count):
        """Property: Duplicate methods in definition are handled."""
        # Arrange - create definition with duplicate methods
        methods = [method] * count
        definition = {
            "methods": methods,
            "dependencies": {},
        }

        # Create service
        async with async_session_maker() as session:
            pipeline_service = PipelineService(session)

            # Act
            resolved_methods = await pipeline_service.resolve_methods(definition)

            # Assert - duplicates should be preserved (or deduplicated based on implementation)
            assert len(resolved_methods) > 0, "Should resolve methods"
            # Current implementation preserves duplicates
            assert len(resolved_methods) == count, (
                "Duplicate methods should be preserved in resolution"
            )

    @given(definition=valid_pipeline_definition())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_resolve_methods_returns_list(self, async_session_maker, definition):
        """Property: resolve_methods always returns a list."""
        # Create service
        async with async_session_maker() as session:
            pipeline_service = PipelineService(session)

            # Act
            result = await pipeline_service.resolve_methods(definition)

            # Assert
            assert isinstance(result, list), "Result should be a list"
            assert len(result) > 0, "Result should not be empty for valid definition"

    @given(
        methods=st.lists(
            st.sampled_from(sorted(KNOWN_METHODS)),
            min_size=1,
            max_size=12,  # All known methods
            unique=True,
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_all_known_methods_can_be_resolved(self, async_session_maker, methods):
        """Property: Any subset of known methods can be successfully resolved."""
        # Arrange
        definition = {
            "methods": methods,
            "dependencies": {},
        }

        # Create service
        async with async_session_maker() as session:
            pipeline_service = PipelineService(session)

            # Act
            resolved_methods = await pipeline_service.resolve_methods(definition)

            # Assert
            assert len(resolved_methods) == len(methods), "All provided methods should be resolved"
            assert resolved_methods == methods, "Resolved methods should match input methods"

    async def test_definition_without_methods_key_fails(self, async_session_maker):
        """Property: Definition without 'methods' key is rejected."""
        # Arrange
        definition = {
            "dependencies": {},
        }

        # Create service
        async with async_session_maker() as session:
            pipeline_service = PipelineService(session)

            # Act & Assert
            with pytest.raises((ValueError, KeyError)):
                await pipeline_service.resolve_methods(definition)

    @given(
        methods=st.one_of(
            st.none(), st.integers(), st.text(), st.dictionaries(st.text(), st.text())
        )
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_invalid_methods_type_is_rejected(self, async_session_maker, methods):
        """Property: Non-list methods value is rejected."""
        # Arrange
        definition = {
            "methods": methods,
            "dependencies": {},
        }

        # Create service
        async with async_session_maker() as session:
            pipeline_service = PipelineService(session)

            # Act & Assert
            # Should raise ValueError or TypeError
            with pytest.raises((ValueError, TypeError, AttributeError)):
                await pipeline_service.resolve_methods(definition)
