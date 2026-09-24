"""Property-based tests for pipeline compute.

# Feature: gap-analysis-and-verification, Property 4: Step output schema conformance
# Feature: gap-analysis-and-verification, Property 5: Checkpoint persistence on failure

**Validates: Requirements 2.2, 2.6**
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from zerna_contracts.enums import RunStatus
from zerna_contracts.run_checkpoint import RunCheckpoint
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# All registered pipeline step names
_ALL_STEPS = [
    "qc_filter",
    "doublet_detection",
    "normalize",
    "select_hvg",
    "run_pca",
    "batch_correction_harmony",
    "batch_correction_scvi",
    "cluster",
    "embed",
    "annotate",
    "differential_expression",
]

_step_name_st = st.sampled_from(_ALL_STEPS)

_error_message_st = st.text(
    min_size=1,
    max_size=200,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs", "P")),
).filter(lambda s: s.strip() != "")

_artifact_refs_st = st.lists(
    st.text(min_size=1, max_size=80, alphabet="abcdefghijklmnopqrstuvwxyz0123456789/_-."),
    max_size=5,
)


# ---------------------------------------------------------------------------
# Property 4: Step output schema conformance
# ---------------------------------------------------------------------------


class TestStepOutputSchemaConformance:
    """Property 4: For any pipeline step output, validating it against the
    corresponding contract schema must succeed without errors.

    We verify this by instantiating each method, checking that its
    output_schema() returns a valid Pydantic model class, and that the
    method's execute() produces an instance that validates against that schema.

    Since running real scientific compute requires actual data, we test the
    structural property: every registered method has a well-defined
    output_schema that is a Pydantic BaseModel subclass with the expected
    fields (adata and/or metrics).

    **Validates: Requirements 2.2**
    """

    @given(step_name=_step_name_st)
    @settings(
        max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    def test_method_output_schema_is_valid_pydantic_model(self, step_name: str) -> None:
        """For any registered step, output_schema() must return a Pydantic
        BaseModel subclass.

        **Validates: Requirements 2.2**
        """
        from pydantic import BaseModel as PydanticBaseModel

        from workflows.run_execution.activities import _get_method_instance

        method = _get_method_instance(step_name)
        schema_cls = method.output_schema()

        assert schema_cls is not None
        assert issubclass(schema_cls, PydanticBaseModel), (
            f"output_schema for '{step_name}' must be a Pydantic BaseModel subclass, "
            f"got {schema_cls}"
        )

    @given(step_name=_step_name_st)
    @settings(
        max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    def test_method_input_schema_is_valid_pydantic_model(self, step_name: str) -> None:
        """For any registered step, input_schema() must return a Pydantic
        BaseModel subclass.

        **Validates: Requirements 2.2**
        """
        from pydantic import BaseModel as PydanticBaseModel

        from workflows.run_execution.activities import _get_method_instance

        method = _get_method_instance(step_name)
        schema_cls = method.input_schema()

        assert schema_cls is not None
        assert issubclass(schema_cls, PydanticBaseModel), (
            f"input_schema for '{step_name}' must be a Pydantic BaseModel subclass, "
            f"got {schema_cls}"
        )

    @given(step_name=_step_name_st)
    @settings(
        max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    def test_method_has_name_and_version(self, step_name: str) -> None:
        """For any registered step, the method instance must have non-empty
        name and version attributes.

        **Validates: Requirements 2.2**
        """
        from workflows.run_execution.activities import _get_method_instance

        method = _get_method_instance(step_name)

        assert hasattr(method, "name") and isinstance(method.name, str) and len(method.name) > 0
        assert (
            hasattr(method, "version")
            and isinstance(method.version, str)
            and len(method.version) > 0
        )

    @given(step_name=_step_name_st)
    @settings(
        max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    def test_output_schema_has_adata_field(self, step_name: str) -> None:
        """For any registered step, the output schema must contain an 'adata'
        field (the primary output of every pipeline step).

        **Validates: Requirements 2.2**
        """
        from workflows.run_execution.activities import _get_method_instance

        method = _get_method_instance(step_name)
        schema_cls = method.output_schema()
        fields = schema_cls.model_fields

        assert "adata" in fields, (
            f"output_schema for '{step_name}' must have an 'adata' field, "
            f"got fields: {list(fields.keys())}"
        )


# ---------------------------------------------------------------------------
# Property 5: Checkpoint persistence on step failure
# ---------------------------------------------------------------------------


class TestCheckpointPersistenceOnFailure:
    """Property 5: For any pipeline step that fails during execution, a
    RunCheckpoint with status=FAILED and a non-null error_message must be
    persisted, and the run must be resumable from that checkpoint.

    **Validates: Requirements 2.6**
    """

    @given(
        step_name=_step_name_st,
        error_msg=_error_message_st,
        artifact_refs=_artifact_refs_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_failed_checkpoint_has_required_fields(
        self,
        step_name: str,
        error_msg: str,
        artifact_refs: list[str],
    ) -> None:
        """For any failed step, the RunCheckpoint must have status=FAILED
        and a non-null error_message.

        **Validates: Requirements 2.6**
        """
        checkpoint = RunCheckpoint(
            run_id=uuid4(),
            step_name=step_name,
            status=RunStatus.FAILED,
            artifact_refs=artifact_refs,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            error_message=error_msg,
        )

        assert checkpoint.status == RunStatus.FAILED
        assert checkpoint.error_message is not None
        assert len(checkpoint.error_message) > 0
        assert checkpoint.step_name == step_name

    @given(
        step_name=_step_name_st,
        error_msg=_error_message_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_checkpoint_persist_and_load_roundtrip(
        self,
        step_name: str,
        error_msg: str,
    ) -> None:
        """For any failed checkpoint, persisting and loading it back must
        return the same data.

        **Validates: Requirements 2.6**
        """
        import tempfile

        import workflows.run_execution.checkpoint as ckpt_mod
        from workflows.run_execution.checkpoint import (
            clear_checkpoints,
            load_checkpoints,
            persist_checkpoint,
        )

        # Use a temp directory to avoid polluting the real checkpoint dir
        original_dir = ckpt_mod._CHECKPOINT_DIR
        tmp_dir = tempfile.mkdtemp(prefix="zerna_test_ckpt_")
        ckpt_mod._CHECKPOINT_DIR = tmp_dir

        try:
            run_id = uuid4()
            started = datetime.utcnow()

            checkpoint = RunCheckpoint(
                run_id=run_id,
                step_name=step_name,
                status=RunStatus.FAILED,
                artifact_refs=[],
                started_at=started,
                completed_at=datetime.utcnow(),
                error_message=error_msg,
            )

            persist_checkpoint(checkpoint)
            loaded = load_checkpoints(run_id)

            assert len(loaded) == 1
            loaded_ckpt = loaded[0]
            assert loaded_ckpt.run_id == run_id
            assert loaded_ckpt.step_name == step_name
            assert loaded_ckpt.status == RunStatus.FAILED
            assert loaded_ckpt.error_message == error_msg

            # Cleanup
            clear_checkpoints(run_id)
            assert load_checkpoints(run_id) == []
        finally:
            ckpt_mod._CHECKPOINT_DIR = original_dir
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)

    @given(
        steps=st.lists(
            _step_name_st,
            min_size=2,
            max_size=6,
            unique=True,
        ),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_resume_point_after_failure(
        self,
        steps: list[str],
    ) -> None:
        """For any sequence of steps where some complete and one fails,
        get_resume_point must return the failed step name.

        **Validates: Requirements 2.6**
        """
        import shutil
        import tempfile

        import workflows.run_execution.checkpoint as ckpt_mod
        from workflows.run_execution.checkpoint import (
            get_resume_point,
            persist_checkpoint,
        )

        original_dir = ckpt_mod._CHECKPOINT_DIR
        tmp_dir = tempfile.mkdtemp(prefix="zerna_test_ckpt_")
        ckpt_mod._CHECKPOINT_DIR = tmp_dir

        try:
            run_id = uuid4()

            # Simulate: first N-1 steps complete, last step fails
            fail_index = len(steps) - 1

            for i, step in enumerate(steps):
                if i < fail_index:
                    persist_checkpoint(
                        RunCheckpoint(
                            run_id=run_id,
                            step_name=step,
                            status=RunStatus.COMPLETED,
                            artifact_refs=[],
                            started_at=datetime.utcnow(),
                            completed_at=datetime.utcnow(),
                            error_message=None,
                        )
                    )
                else:
                    persist_checkpoint(
                        RunCheckpoint(
                            run_id=run_id,
                            step_name=step,
                            status=RunStatus.FAILED,
                            artifact_refs=[],
                            started_at=datetime.utcnow(),
                            completed_at=datetime.utcnow(),
                            error_message="simulated failure",
                        )
                    )

            resume = get_resume_point(run_id, steps)
            assert resume == steps[fail_index], (
                f"Expected resume at '{steps[fail_index]}', got '{resume}'"
            )
        finally:
            ckpt_mod._CHECKPOINT_DIR = original_dir
            shutil.rmtree(tmp_dir, ignore_errors=True)
