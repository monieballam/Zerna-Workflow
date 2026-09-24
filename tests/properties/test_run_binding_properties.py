"""Property-based tests for run start dataset version binding.

# Feature: gap-analysis-and-verification, Property 6: Run start requires dataset version binding

**Validates: Requirements 3.1, 3.2, 3.3**
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.api.services.run_service import RunService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_uuid_st = st.builds(uuid4)

_checksum = st.text(min_size=64, max_size=64, alphabet="0123456789abcdef")

_parameters = st.fixed_dictionaries(
    {
        "n_top_genes": st.integers(min_value=100, max_value=5000),
        "resolution": st.floats(min_value=0.1, max_value=3.0, allow_nan=False),
    }
)

_random_seed = st.one_of(st.none(), st.integers(min_value=0, max_value=2**31 - 1))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_service_with_valid_version(
    checksum: str,
    org_id: UUID | None = None,
    dataset_version_id: UUID | None = None,
    template_id: UUID | None = None,
) -> tuple[RunService, UUID, UUID, UUID]:
    """Create a RunService with mocked DB that has a valid dataset version.

    Returns (service, org_id, dataset_version_id, template_id).
    """
    from apps.api.models.dataset import Dataset
    from apps.api.models.dataset import DatasetVersion as DVModel
    from apps.api.models.pipeline import PipelineTemplate, Run

    _org_id = org_id or uuid4()
    _dv_id = dataset_version_id or uuid4()
    _tmpl_id = template_id or uuid4()

    # Mock dataset version with checksum
    mock_dv = MagicMock(spec=DVModel)
    mock_dv.id = _dv_id
    mock_dv.checksum = checksum
    mock_dv.dataset = MagicMock(spec=Dataset)
    mock_dv.dataset.organization_id = _org_id

    # Mock template
    mock_template = MagicMock(spec=PipelineTemplate)
    mock_template.id = _tmpl_id
    mock_template.organization_id = _org_id

    # Mock DB session
    db = AsyncMock()

    # create_run issues 3 execute calls:
    #   1. select DatasetVersion -> mock_dv
    #   2. select PipelineTemplate -> mock_template
    #   3. pipeline_service.validate_parameters (handled separately)
    dv_result = MagicMock()
    dv_result.scalar_one_or_none.return_value = mock_dv

    tmpl_result = MagicMock()
    tmpl_result.scalar_one_or_none.return_value = mock_template

    db.execute = AsyncMock(side_effect=[dv_result, tmpl_result])
    db.add = MagicMock()
    db.commit = AsyncMock()

    # Make refresh populate the run's id and created_at
    async def _refresh(obj, **kwargs):
        if isinstance(obj, Run) or hasattr(obj, "id"):
            if not hasattr(obj, "_refreshed"):
                obj._refreshed = True
                if obj.id is None:
                    obj.id = uuid4()
                if obj.created_at is None:
                    obj.created_at = datetime.utcnow()

    db.refresh = AsyncMock(side_effect=_refresh)

    # Mock pipeline service
    pipeline_svc = MagicMock()
    pipeline_svc.validate_parameters = AsyncMock(return_value=(True, None))

    # Mock quota service
    quota_svc = MagicMock()
    quota_svc.check_compute_quota = AsyncMock()

    # Mock audit service
    audit_svc = MagicMock()
    audit_svc.audit_log = AsyncMock()

    svc = RunService(
        db=db,
        pipeline_service=pipeline_svc,
        audit_service=audit_svc,
    )
    # Patch quota service directly
    svc.quota_service = quota_svc

    return svc, _org_id, _dv_id, _tmpl_id


def _make_mock_service_no_version(
    org_id: UUID | None = None,
) -> tuple[RunService, UUID]:
    """Create a RunService with mocked DB where dataset version does NOT exist.

    Returns (service, org_id).
    """
    _org_id = org_id or uuid4()

    db = AsyncMock()

    # First execute: select DatasetVersion -> None
    dv_result = MagicMock()
    dv_result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(return_value=dv_result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    pipeline_svc = MagicMock()
    pipeline_svc.validate_parameters = AsyncMock(return_value=(True, None))

    audit_svc = MagicMock()
    audit_svc.audit_log = AsyncMock()

    svc = RunService(
        db=db,
        pipeline_service=pipeline_svc,
        audit_service=audit_svc,
    )
    svc.quota_service = MagicMock()
    svc.quota_service.check_compute_quota = AsyncMock()

    return svc, _org_id


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestRunStartDatasetVersionBinding:
    """Property 6: Run start requires dataset version binding.

    For any run start request, if dataset_version_id is missing or references
    a non-existent version, the request must be rejected. For valid requests,
    the resulting RunManifest must contain the dataset_version_id and
    dataset_checksum.
    """

    @pytest.mark.asyncio
    @given(
        checksum=_checksum,
        parameters=_parameters,
        random_seed=_random_seed,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_valid_run_manifest_contains_version_and_checksum(
        self,
        checksum: str,
        parameters: dict,
        random_seed: int | None,
    ) -> None:
        """For any valid run start request, the resulting RunManifest must
        contain the dataset_version_id and dataset_checksum.

        **Validates: Requirements 3.1, 3.2**
        """
        svc, org_id, dv_id, tmpl_id = _make_mock_service_with_valid_version(
            checksum=checksum,
        )

        run = await svc.create_run(
            org_id=org_id,
            dataset_version_id=dv_id,
            template_id=tmpl_id,
            parameters=parameters,
            random_seed=random_seed,
        )

        manifest = svc.build_run_manifest(
            run=run,
            dataset_checksum=checksum,
        )

        # Manifest must contain the dataset_version_id
        assert manifest.dataset_version_id == dv_id
        # Manifest must contain the dataset checksum
        assert manifest.dataset_checksum == checksum
        assert len(manifest.dataset_checksum) > 0
        # Manifest run_id must match the created run
        assert manifest.run_id == run.id
        # Template must match
        assert manifest.template_id == tmpl_id

    @pytest.mark.asyncio
    @given(
        parameters=_parameters,
        random_seed=_random_seed,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_nonexistent_version_rejected(
        self,
        parameters: dict,
        random_seed: int | None,
    ) -> None:
        """For any run start request referencing a non-existent dataset version,
        the request must be rejected with a ValueError.

        **Validates: Requirements 3.3**
        """
        svc, org_id = _make_mock_service_no_version()

        fake_dv_id = uuid4()
        fake_tmpl_id = uuid4()

        with pytest.raises(ValueError, match="not found"):
            await svc.create_run(
                org_id=org_id,
                dataset_version_id=fake_dv_id,
                template_id=fake_tmpl_id,
                parameters=parameters,
                random_seed=random_seed,
            )

    @pytest.mark.asyncio
    @given(
        checksum=_checksum,
        parameters=_parameters,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_manifest_checksum_matches_dataset_version(
        self,
        checksum: str,
        parameters: dict,
    ) -> None:
        """For any valid run, the manifest's dataset_checksum must exactly
        match the checksum from the dataset version record.

        **Validates: Requirements 3.2**
        """
        svc, org_id, dv_id, tmpl_id = _make_mock_service_with_valid_version(
            checksum=checksum,
        )

        run = await svc.create_run(
            org_id=org_id,
            dataset_version_id=dv_id,
            template_id=tmpl_id,
            parameters=parameters,
        )

        manifest = svc.build_run_manifest(
            run=run,
            dataset_checksum=checksum,
        )

        assert manifest.dataset_checksum == checksum
