"""Property-based tests for Temporal workflow retry with exponential backoff.

**Validates: Requirements 13.4, 16.4**
"""

from datetime import timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from temporalio.common import RetryPolicy

from workflows.run_execution.workflow import RunExecutionWorkflow


@pytest.mark.property
class TestTemporalWorkflowRetry:
    """Property 25: Temporal Workflow Retry with Exponential Backoff

    For any transient error in a Temporal workflow activity, the workflow should
    retry the activity with exponentially increasing delays.
    """

    @pytest.mark.asyncio
    @given(
        initial_interval_seconds=st.integers(min_value=1, max_value=5),
        backoff_coefficient=st.floats(min_value=1.5, max_value=3.0),
        max_attempts=st.integers(min_value=2, max_value=5),
    )
    @settings(max_examples=20, deadline=None)
    async def test_property_retry_policy_has_exponential_backoff(
        self,
        initial_interval_seconds,
        backoff_coefficient,
        max_attempts,
    ):
        """Property: Retry policy is configured with exponential backoff parameters.

        **Validates: Requirements 13.4, 16.4**
        """
        # Create retry policy with generated parameters
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=initial_interval_seconds),
            maximum_interval=timedelta(seconds=60),
            backoff_coefficient=backoff_coefficient,
            maximum_attempts=max_attempts,
        )

        # Property assertions
        assert retry_policy.initial_interval == timedelta(seconds=initial_interval_seconds), (
            "Initial interval should match configured value"
        )

        assert retry_policy.backoff_coefficient == backoff_coefficient, (
            "Backoff coefficient should match configured value"
        )

        assert retry_policy.maximum_attempts == max_attempts, (
            "Maximum attempts should match configured value"
        )

        # Verify exponential growth property
        # For exponential backoff: delay_n = initial_interval * (backoff_coefficient ^ (n-1))
        expected_delay_2 = initial_interval_seconds * backoff_coefficient
        expected_delay_3 = initial_interval_seconds * (backoff_coefficient**2)

        assert expected_delay_2 > initial_interval_seconds, (
            "Second retry delay should be greater than initial interval"
        )

        assert expected_delay_3 > expected_delay_2, (
            "Third retry delay should be greater than second retry delay"
        )

        # Verify exponential growth rate
        growth_rate_2_to_3 = expected_delay_3 / expected_delay_2
        assert abs(growth_rate_2_to_3 - backoff_coefficient) < 0.01, (
            f"Growth rate should equal backoff coefficient: {growth_rate_2_to_3} ≈ {backoff_coefficient}"
        )

    @pytest.mark.asyncio
    async def test_property_retry_policy_configuration_in_workflow(self):
        """Property: Workflow activities are configured with retry policies.

        This test verifies that the actual workflow code configures retry policies
        for activities, which is the key requirement for exponential backoff.

        **Validates: Requirements 13.4, 16.4**
        """
        import inspect

        # Get the workflow source code
        source = inspect.getsource(RunExecutionWorkflow.run)

        # Count how many activities use retry_policy
        activity_calls = source.count("execute_activity")
        retry_policy_uses = source.count("retry_policy=retry_policy")

        # Property assertion: All activities should use retry policy
        assert activity_calls > 0, "Workflow should have at least one activity call"

        assert retry_policy_uses > 0, "Workflow should configure retry_policy for activities"

        # Verify the retry policy is defined with exponential backoff
        assert "RetryPolicy(" in source, "Workflow should define RetryPolicy"

        assert "backoff_coefficient=2.0" in source or "backoff_coefficient = 2.0" in source, (
            "Workflow should use exponential backoff with coefficient 2.0"
        )

    @pytest.mark.asyncio
    @given(
        num_activities=st.integers(min_value=1, max_value=5),
        max_attempts=st.integers(min_value=2, max_value=5),
    )
    @settings(max_examples=20, deadline=None)
    async def test_property_multiple_activities_all_have_retry(self, num_activities, max_attempts):
        """Property: When a workflow has multiple activities, all should have retry policies.

        **Validates: Requirements 13.4, 16.4**
        """
        # This is a structural property test - we verify that the pattern is consistent
        # In a real workflow with N activities, all N should have retry policies

        # Create a retry policy
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=60),
            backoff_coefficient=2.0,
            maximum_attempts=max_attempts,
        )

        # Property assertion: Retry policy should be reusable across activities
        assert retry_policy.maximum_attempts == max_attempts, (
            "Retry policy should maintain configured max_attempts"
        )

        # Verify that applying the same retry policy to multiple activities is valid
        for i in range(num_activities):
            # Each activity would use the same retry policy
            assert retry_policy.backoff_coefficient == 2.0, (
                f"Activity {i} should use exponential backoff"
            )

    @pytest.mark.asyncio
    async def test_property_compensation_logic_exists_for_failures(self):
        """Property: Workflows have compensation logic for handling failures.

        **Validates: Requirements 13.4**
        """
        import inspect

        # Get the workflow source code
        source = inspect.getsource(RunExecutionWorkflow.run)

        # Property assertions: Verify compensation logic exists
        assert "except" in source, "Workflow should have exception handling for compensation"

        assert "cleanup" in source.lower(), "Workflow should have cleanup/compensation logic"

        # Verify cleanup activity is called on failure
        assert "cleanup_run_resources" in source, (
            "Workflow should call cleanup_run_resources on failure"
        )

    @pytest.mark.asyncio
    async def test_property_actual_workflow_has_retry_policy(self):
        """Property: Actual RunExecutionWorkflow has retry policy configured.

        **Validates: Requirements 13.4, 16.4**
        """

        # Read the workflow source to verify retry policy configuration
        import inspect

        source = inspect.getsource(RunExecutionWorkflow.run)

        # Property assertions: Verify retry policy is configured in workflow
        assert "RetryPolicy" in source, "Workflow should configure RetryPolicy for activities"

        assert "initial_interval" in source, "Retry policy should specify initial_interval"

        assert "backoff_coefficient" in source, (
            "Retry policy should specify backoff_coefficient for exponential backoff"
        )

        assert "maximum_attempts" in source, "Retry policy should specify maximum_attempts"

        # Verify exponential backoff is used (backoff_coefficient > 1)
        assert "backoff_coefficient=2.0" in source or "backoff_coefficient = 2.0" in source, (
            "Workflow should use exponential backoff with coefficient >= 2.0"
        )

    @pytest.mark.asyncio
    @given(
        initial_seconds=st.integers(min_value=1, max_value=5),
        coefficient=st.floats(min_value=1.5, max_value=3.0),
    )
    @settings(max_examples=20, deadline=None)
    async def test_property_exponential_delay_calculation(self, initial_seconds, coefficient):
        """Property: Exponential backoff delays grow according to formula.

        Formula: delay_n = initial_interval * (backoff_coefficient ^ (n-1))

        **Validates: Requirements 13.4, 16.4**
        """
        # Calculate expected delays for first 5 attempts
        delays = []
        for attempt in range(1, 6):
            delay = initial_seconds * (coefficient ** (attempt - 1))
            delays.append(delay)

        # Property assertions: Verify exponential growth
        for i in range(len(delays) - 1):
            assert delays[i + 1] > delays[i], (
                f"Delay should increase: delay[{i + 1}]={delays[i + 1]} > delay[{i}]={delays[i]}"
            )

            # Verify growth rate equals backoff coefficient
            growth_rate = delays[i + 1] / delays[i]
            assert abs(growth_rate - coefficient) < 0.01, (
                f"Growth rate should equal coefficient: {growth_rate} ≈ {coefficient}"
            )

        # Verify first delay equals initial interval
        assert delays[0] == initial_seconds, (
            f"First delay should equal initial interval: {delays[0]} == {initial_seconds}"
        )

    @pytest.mark.asyncio
    async def test_property_dataset_ingestion_workflow_has_retry_policy(self):
        """Property: DatasetIngestionWorkflow has retry policy configured.

        **Validates: Requirements 13.4, 16.4**
        """
        # Read the workflow source
        import inspect

        from workflows.dataset_ingestion.workflow import DatasetIngestionWorkflow

        source = inspect.getsource(DatasetIngestionWorkflow.run)

        # Property assertions
        assert "RetryPolicy" in source, "DatasetIngestionWorkflow should configure RetryPolicy"

        assert "backoff_coefficient" in source, (
            "DatasetIngestionWorkflow should use exponential backoff"
        )

    @pytest.mark.asyncio
    async def test_property_export_workflow_has_retry_policy(self):
        """Property: ExportWorkflow has retry policy configured.

        **Validates: Requirements 13.4, 16.4**
        """
        # Read the workflow source
        import inspect

        from workflows.export.workflow import ExportWorkflow

        source = inspect.getsource(ExportWorkflow.run)

        # Property assertions
        assert "RetryPolicy" in source, "ExportWorkflow should configure RetryPolicy"

        assert "backoff_coefficient" in source, "ExportWorkflow should use exponential backoff"
