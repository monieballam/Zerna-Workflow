"""Property-based tests for dataset version immutability and lineage completeness.

# Feature: gap-analysis-and-verification, Property 3: Dataset version immutability and lineage completeness

**Validates: Requirements 1.5**
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.api.services.dataset_service import DatasetService, VersionMetadata

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_uuid_st = st.builds(uuid4)

_source_type_non_merge = st.sampled_from(["upload", "s3_uri"])
_source_type_all = st.sampled_from(["upload", "s3_uri", "merge"])

_file_refs = st.lists(
    st.text(min_size=5, max_size=80, alphabet="abcdefghijklmnopqrstuvwxyz0123456789/_-."),
    min_size=1,
    max_size=5,
)

_schema_summary = st.fixed_dictionaries(
    {
        "columns": st.lists(
            st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz_"),
            min_size=1,
            max_size=10,
        ),
        "shape": st.tuples(
            st.integers(min_value=1, max_value=100_000),
            st.integers(min_value=1, max_value=50_000),
        ),
    }
)

_checksum = st.text(min_size=64, max_size=64, alphabet="0123456789abcdef")


def _version_metadata_non_merge() -> st.SearchStrategy["VersionMetadata"]:
    """Strategy for upload/s3_uri version metadata."""
    return st.builds(
        VersionMetadata,
        source_type=_source_type_non_merge,
        parent_version_ids=st.just([]),
        schema_summary=_schema_summary,
        uploaded_by=_uuid_st,
        checksum=_checksum,
    )


def _version_metadata_merge() -> st.SearchStrategy["VersionMetadata"]:
    """Strategy for merge version metadata with non-empty parent_version_ids."""
    return st.builds(
        VersionMetadata,
        source_type=st.just("merge"),
        parent_version_ids=st.lists(_uuid_st, min_size=1, max_size=5),
        schema_summary=_schema_summary,
        uploaded_by=_uuid_st,
        checksum=_checksum,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_service() -> tuple[DatasetService, UUID, UUID]:
    """Create a DatasetService backed by an in-memory mock DB session.

    Returns (service, dataset_id, org_id).
    """

    from apps.api.models.dataset import Dataset

    org_id = uuid4()
    dataset_id = uuid4()

    # Fake dataset row
    mock_dataset = MagicMock(spec=Dataset)
    mock_dataset.id = dataset_id
    mock_dataset.organization_id = org_id

    # Mock DB session
    db = AsyncMock()

    # First execute call: select Dataset -> returns mock_dataset
    # Second execute call: select DatasetVersion -> returns empty list
    dataset_result = MagicMock()
    dataset_result.scalar_one_or_none.return_value = mock_dataset

    version_result = MagicMock()
    version_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

    db.execute = AsyncMock(side_effect=[dataset_result, version_result])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    svc = DatasetService(
        db=db,
        s3_service=MagicMock(),
        file_validation_service=MagicMock(),
    )

    return svc, dataset_id, org_id


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestDatasetVersionImmutabilityAndLineage:
    """Property 3: Dataset version immutability and lineage completeness.

    For any imported dataset, the resulting DatasetVersion must have a non-null
    checksum, uploaded_by, created_at, schema_summary, and source_type.
    For merge-sourced versions, parent_version_ids must be non-empty.
    """

    @pytest.mark.asyncio
    @given(
        file_refs=_file_refs,
        meta=_version_metadata_non_merge(),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_non_merge_version_has_required_fields(
        self, file_refs: list[str], meta: VersionMetadata
    ) -> None:
        """For any upload/s3_uri version, checksum, uploaded_by, created_at,
        schema_summary, and source_type must all be non-null.

        **Validates: Requirements 1.5**
        """
        svc, dataset_id, org_id = _make_mock_service()

        version = await svc.create_immutable_version(
            dataset_id=dataset_id,
            file_refs=file_refs,
            metadata=meta,
            org_id=org_id,
        )

        assert version.checksum is not None and len(version.checksum) > 0
        assert version.uploaded_by is not None
        assert version.created_at is not None
        assert version.schema_summary is not None
        assert version.source_type is not None
        assert version.source_type in ("upload", "s3_uri", "merge")

    @pytest.mark.asyncio
    @given(
        file_refs=_file_refs,
        meta=_version_metadata_merge(),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_merge_version_has_non_empty_parent_ids(
        self, file_refs: list[str], meta: VersionMetadata
    ) -> None:
        """For any merge-sourced version, parent_version_ids must be non-empty.

        **Validates: Requirements 1.5**
        """
        svc, dataset_id, org_id = _make_mock_service()

        version = await svc.create_immutable_version(
            dataset_id=dataset_id,
            file_refs=file_refs,
            metadata=meta,
            org_id=org_id,
        )

        assert version.source_type == "merge"
        assert version.parent_version_ids is not None
        assert len(version.parent_version_ids) > 0

    @pytest.mark.asyncio
    @given(
        file_refs=_file_refs,
        meta=_version_metadata_non_merge(),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_checksum_is_deterministic(
        self, file_refs: list[str], meta: VersionMetadata
    ) -> None:
        """When a checksum is provided in metadata, the version must use that
        exact checksum (immutability guarantee).

        **Validates: Requirements 1.5**
        """
        svc, dataset_id, org_id = _make_mock_service()

        version = await svc.create_immutable_version(
            dataset_id=dataset_id,
            file_refs=file_refs,
            metadata=meta,
            org_id=org_id,
        )

        assert version.checksum == meta.checksum

    @pytest.mark.asyncio
    async def test_merge_without_parents_raises(self) -> None:
        """A merge version with empty parent_version_ids must be rejected.

        **Validates: Requirements 1.5**
        """
        svc, dataset_id, org_id = _make_mock_service()

        meta = VersionMetadata(
            source_type="merge",
            parent_version_ids=[],
            schema_summary={"columns": ["a"], "shape": (10, 1)},
            uploaded_by=uuid4(),
            checksum="a" * 64,
        )

        with pytest.raises(ValueError, match="parent_version_ids"):
            await svc.create_immutable_version(
                dataset_id=dataset_id,
                file_refs=["s3://bucket/file.h5ad"],
                metadata=meta,
                org_id=org_id,
            )
