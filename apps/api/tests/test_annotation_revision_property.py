"""Property-based tests for annotation revision creation on edit.

**Validates: Requirements 5.5**
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from zerna_contracts.enums import RunStatus
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.models import Base, Dataset, DatasetVersion, Organization, PipelineTemplate, Run, User
from apps.api.services.annotation_service import AnnotationService


@pytest_asyncio.fixture(scope="module")
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


async def get_clean_session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(delete(table))
        await session.commit()
        return session


async def _make_run(session: AsyncSession) -> Run:
    """Helper: create minimal org/user/dataset/run for tests."""
    org = Organization(id=uuid4(), name="Org", storage_quota_gb=100, compute_quota_runs=10)
    session.add(org)
    await session.flush()

    user = User(id=uuid4(), email=f"{uuid4()}@test.com", hashed_password="x")
    session.add(user)
    await session.flush()

    dataset = Dataset(id=uuid4(), organization_id=org.id, name="DS")
    session.add(dataset)
    await session.flush()

    version = DatasetVersion(
        id=uuid4(), dataset_id=dataset.id, version="v1", s3_path="s3://b/f.h5ad"
    )
    session.add(version)
    await session.flush()

    template = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name=f"t-{uuid4().hex[:8]}",
        version="v1",
        definition={},
    )
    session.add(template)
    await session.flush()

    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=version.id,
        template_id=template.id,
        status=RunStatus.COMPLETED,
        parameters={},
    )
    session.add(run)
    await session.commit()
    return run


# ── Strategies ─────────────────────────────────────────────────────────────────

annotation_value = st.one_of(st.text(max_size=20), st.integers(), st.floats(allow_nan=False))
annotations_dict = st.dictionaries(
    st.text(
        min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))
    ),
    annotation_value,
    min_size=0,
    max_size=5,
)
edits_dict = st.dictionaries(
    st.text(
        min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))
    ),
    annotation_value,
    min_size=1,
    max_size=5,
)


@pytest.mark.property
class TestAnnotationRevisionCreationOnEdit:
    """Property 15: Annotation Revision Creation on Edit

    For any manual edit to cell type annotations, a new AnnotationRevision should
    be created with incremented revision_number, preserving the previous revision.
    """

    @pytest.mark.asyncio
    @given(initial_annotations=annotations_dict, edits=edits_dict)
    @settings(max_examples=100)
    async def test_edit_creates_new_revision_with_incremented_number(
        self, async_engine, initial_annotations, edits
    ):
        """Property: editing creates a new revision with revision_number = old + 1.

        **Validates: Requirements 5.5**
        """
        session = await get_clean_session(async_engine)
        run = await _make_run(session)
        svc = AnnotationService(session)

        original = await svc.create_revision(
            run_id=run.id,
            annotations=initial_annotations,
            created_by=uuid4(),
        )
        original_number = original.revision_number

        new_rev = await svc.edit_annotations(
            revision_id=original.id,
            edits=edits,
            user_id=uuid4(),
        )

        assert new_rev.revision_number == original_number + 1, (
            f"Expected revision_number {original_number + 1}, got {new_rev.revision_number}"
        )
        await session.close()

    @pytest.mark.asyncio
    @given(initial_annotations=annotations_dict, edits=edits_dict)
    @settings(max_examples=100)
    async def test_previous_revision_preserved_after_edit(
        self, async_engine, initial_annotations, edits
    ):
        """Property: the previous revision still exists with its original data.

        **Validates: Requirements 5.5**
        """
        session = await get_clean_session(async_engine)
        run = await _make_run(session)
        svc = AnnotationService(session)

        original = await svc.create_revision(
            run_id=run.id,
            annotations=initial_annotations,
            created_by=uuid4(),
        )
        original_id = original.id
        original_annotations = dict(original.annotations)

        await svc.edit_annotations(
            revision_id=original.id,
            edits=edits,
            user_id=uuid4(),
        )

        # Original revision must still exist unchanged
        preserved = await svc.get_revision(original_id)
        assert preserved is not None, "Original revision must still exist after edit"
        assert preserved.annotations == original_annotations, (
            "Original revision annotations must be unchanged"
        )
        await session.close()

    @pytest.mark.asyncio
    @given(initial_annotations=annotations_dict, edits=edits_dict)
    @settings(max_examples=100)
    async def test_new_revision_contains_merged_annotations(
        self, async_engine, initial_annotations, edits
    ):
        """Property: the new revision contains the merged/updated annotations.

        **Validates: Requirements 5.5**
        """
        session = await get_clean_session(async_engine)
        run = await _make_run(session)
        svc = AnnotationService(session)

        original = await svc.create_revision(
            run_id=run.id,
            annotations=initial_annotations,
            created_by=uuid4(),
        )

        new_rev = await svc.edit_annotations(
            revision_id=original.id,
            edits=edits,
            user_id=uuid4(),
        )

        expected = {**initial_annotations, **edits}
        assert new_rev.annotations == expected, (
            f"New revision should contain merged annotations. "
            f"Expected {expected}, got {new_rev.annotations}"
        )
        await session.close()

    @pytest.mark.asyncio
    @given(
        initial_annotations=annotations_dict,
        edit_sequence=st.lists(edits_dict, min_size=2, max_size=5),
    )
    @settings(max_examples=100)
    async def test_sequential_edits_produce_monotonically_increasing_revision_numbers(
        self, async_engine, initial_annotations, edit_sequence
    ):
        """Property: multiple sequential edits each create a new revision with monotonically
        increasing revision_numbers.

        **Validates: Requirements 5.5**
        """
        session = await get_clean_session(async_engine)
        run = await _make_run(session)
        svc = AnnotationService(session)

        current = await svc.create_revision(
            run_id=run.id,
            annotations=initial_annotations,
            created_by=uuid4(),
        )

        prev_number = current.revision_number
        for edits in edit_sequence:
            new_rev = await svc.edit_annotations(
                revision_id=current.id,
                edits=edits,
                user_id=uuid4(),
            )
            assert new_rev.revision_number == prev_number + 1, (
                f"Expected revision_number {prev_number + 1}, got {new_rev.revision_number}"
            )
            prev_number = new_rev.revision_number
            current = new_rev

        # Verify all revisions exist and are ordered
        all_revisions = await svc.list_revisions(run.id)
        numbers = [r.revision_number for r in all_revisions]
        assert numbers == sorted(numbers), "Revisions must be ordered by revision_number"
        assert len(numbers) == len(edit_sequence) + 1, (
            f"Expected {len(edit_sequence) + 1} revisions, got {len(numbers)}"
        )
        await session.close()
