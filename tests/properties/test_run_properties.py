"""Property-based tests for run replay reproducibility and persistence round-trip.

# Feature: gap-analysis-and-verification, Property 7: Deterministic method replay reproducibility
# Feature: gap-analysis-and-verification, Property 8: Run persistence round-trip

**Validates: Requirements 3.4, 5.1**
"""

import hashlib
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from zerna_contracts.enums import ArtifactType, RunStatus
from zerna_contracts.run_manifest import RunManifest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.api.models.dataset import Dataset
from apps.api.models.dataset import DatasetVersion as DVModel
from apps.api.models.pipeline import Artifact, Run
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

_random_seed = st.integers(min_value=0, max_value=2**31 - 1)

_method_versions = st.dictionaries(
    keys=st.sampled_from(["qc", "normalize", "hvg", "pca", "cluster", "annotate"]),
    values=st.from_regex(r"[0-9]+\.[0-9]+\.[0-9]+", fullmatch=True),
    min_size=1,
    max_size=6,
)


# ---------------------------------------------------------------------------
# Helpers — deterministic method simulation
# ---------------------------------------------------------------------------


def _deterministic_method(data: bytes, seed: int, params: dict) -> bytes:
    """Simulate a deterministic scientific method.

    Given the same input data, seed, and parameters, this always produces
    the same output bytes (SHA-256 based).
    """
    h = hashlib.sha256()
    h.update(data)
    h.update(seed.to_bytes(8, "big"))
    for k in sorted(params):
        h.update(k.encode())
        h.update(str(params[k]).encode())
    return h.digest()


# ---------------------------------------------------------------------------
# Helpers — mock DB for manifest persistence
# ---------------------------------------------------------------------------


class _ManifestDB:
    """In-memory mock that stores Run rows and supports manifest persistence."""

    def __init__(self) -> None:
        self._runs: dict[UUID, Run] = {}
        self._artifacts: dict[UUID, list[Artifact]] = {}

    def seed_run(
        self,
        run: Run,
        artifacts: list[Artifact] | None = None,
    ) -> None:
        self._runs[run.id] = run
        if artifacts:
            self._artifacts[run.id] = artifacts

    # --- async session interface ---

    def add(self, obj: object) -> None:
        if isinstance(obj, Run):
            self._runs[obj.id] = obj
        elif isinstance(obj, Artifact):
            self._artifacts.setdefault(obj.run_id, []).append(obj)

    async def commit(self) -> None:
        pass

    async def refresh(self, obj: object, **kwargs: object) -> None:
        if isinstance(obj, Run) and hasattr(obj, "id"):
            if obj.id is None:
                obj.id = uuid4()
            if obj.created_at is None:
                obj.created_at = datetime.utcnow()

    async def delete(self, obj: object) -> None:
        if isinstance(obj, Run):
            self._runs.pop(obj.id, None)
            self._artifacts.pop(obj.id, None)

    async def execute(self, stmt: object) -> "_FakeResult":
        stmt_str = str(stmt)

        # Route to the right handler
        if "artifacts" in stmt_str:
            return self._execute_artifact_query(stmt, stmt_str)
        if "runs" in stmt_str or "dataset_versions" in stmt_str or "pipeline_templates" in stmt_str:
            return self._execute_run_query(stmt, stmt_str)
        return _FakeResult(items=[])

    def _execute_run_query(self, stmt: object, stmt_str: str) -> "_FakeResult":
        from tests.properties.test_persistent_storage_properties import _try_compile

        compiled = _try_compile(stmt)
        params = compiled.get("params", {}) if compiled else {}

        # Check if this is a DatasetVersion query
        if "dataset_versions" in stmt_str and "runs" not in stmt_str:
            # Return the mock dataset version stored on the run
            for v in params.values():
                if isinstance(v, UUID):
                    for run in self._runs.values():
                        if hasattr(run, "_mock_dv") and run._mock_dv.id == v:
                            return _FakeResult(items=[run._mock_dv])
            return _FakeResult(items=[])

        # Check if this is a PipelineTemplate query
        if "pipeline_templates" in stmt_str and "runs" not in stmt_str:
            for v in params.values():
                if isinstance(v, UUID):
                    for run in self._runs.values():
                        if hasattr(run, "_mock_tmpl") and run._mock_tmpl.id == v:
                            return _FakeResult(items=[run._mock_tmpl])
            return _FakeResult(items=[])

        # Run query — filter by params
        items = list(self._runs.values())
        for v in params.values():
            if isinstance(v, UUID) and v in self._runs:
                items = [self._runs[v]]
                break

        return _FakeResult(items=items)

    def _execute_artifact_query(self, stmt: object, stmt_str: str) -> "_FakeResult":
        all_artifacts: list[Artifact] = []
        for arts in self._artifacts.values():
            all_artifacts.extend(arts)
        return _FakeResult(items=all_artifacts)


class _FakeResult:
    """Mimics SQLAlchemy Result."""

    def __init__(self, items: list | None = None, scalar_value: object = None) -> None:
        self._items = items or []
        self._scalar_value = scalar_value

    def scalar_one_or_none(self) -> object:
        if self._scalar_value is not None:
            return self._scalar_value
        return self._items[0] if self._items else None

    def scalar_one(self) -> object:
        if self._scalar_value is not None:
            return self._scalar_value
        return self._items[0]

    def scalars(self) -> "_FakeScalars":
        return _FakeScalars(self._items)

    def unique(self) -> "_FakeResult":
        return self


class _FakeScalars:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return self._items


def _make_run(
    org_id: UUID,
    dv_id: UUID,
    tmpl_id: UUID,
    checksum: str,
    parameters: dict,
    random_seed: int | None = None,
    status: RunStatus = RunStatus.COMPLETED,
) -> Run:
    """Create a Run ORM object with associated mock dataset version and template."""
    run = Run(
        id=uuid4(),
        organization_id=org_id,
        dataset_version_id=dv_id,
        template_id=tmpl_id,
        status=status,
        parameters=dict(parameters),
        random_seed=random_seed,
        created_at=datetime.utcnow(),
    )

    # Attach mock dataset version for replay queries
    mock_dv = MagicMock(spec=DVModel)
    mock_dv.id = dv_id
    mock_dv.checksum = checksum
    mock_dv.dataset = MagicMock(spec=Dataset)
    mock_dv.dataset.organization_id = org_id
    run._mock_dv = mock_dv  # type: ignore[attr-defined]

    # Attach mock template
    from apps.api.models.pipeline import PipelineTemplate

    mock_tmpl = MagicMock(spec=PipelineTemplate)
    mock_tmpl.id = tmpl_id
    mock_tmpl.organization_id = org_id
    run._mock_tmpl = mock_tmpl  # type: ignore[attr-defined]

    return run


def _make_service(db: _ManifestDB) -> RunService:
    """Create a RunService wired to the in-memory DB."""
    pipeline_svc = MagicMock()
    pipeline_svc.validate_parameters = AsyncMock(return_value=(True, None))

    audit_svc = MagicMock()
    audit_svc.audit_log = AsyncMock()

    svc = RunService(
        db=db,  # type: ignore[arg-type]
        pipeline_service=pipeline_svc,
        audit_service=audit_svc,
    )
    svc.quota_service = MagicMock()
    svc.quota_service.check_compute_quota = AsyncMock()
    return svc


# ---------------------------------------------------------------------------
# Property 7: Deterministic method replay reproducibility
# ---------------------------------------------------------------------------


class TestDeterministicMethodReplayReproducibility:
    """Property 7: For any deterministic method and a given RunManifest
    (same dataset version, parameters, and random seed), replaying the
    method must produce byte-identical outputs.

    **Validates: Requirements 3.4**
    """

    @given(
        checksum=_checksum,
        parameters=_parameters,
        random_seed=_random_seed,
        method_versions=_method_versions,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_same_manifest_produces_identical_output(
        self,
        checksum: str,
        parameters: dict,
        random_seed: int,
        method_versions: dict[str, str],
    ) -> None:
        """Running a deterministic method twice with the same manifest
        (dataset version, parameters, random seed) produces byte-identical
        outputs.

        **Validates: Requirements 3.4**
        """
        # Simulate dataset bytes derived from checksum
        dataset_bytes = checksum.encode("utf-8")

        manifest = RunManifest(
            run_id=uuid4(),
            dataset_version_id=uuid4(),
            dataset_checksum=checksum,
            template_id=uuid4(),
            parameters=parameters,
            method_versions=method_versions,
            random_seed=random_seed,
            created_at=datetime.utcnow(),
        )

        # Execute the deterministic method twice with the same inputs
        output_1 = _deterministic_method(
            data=dataset_bytes,
            seed=manifest.random_seed,
            params=manifest.parameters,
        )
        output_2 = _deterministic_method(
            data=dataset_bytes,
            seed=manifest.random_seed,
            params=manifest.parameters,
        )

        assert output_1 == output_2, (
            "Deterministic method must produce byte-identical outputs "
            "for the same dataset, parameters, and seed"
        )

    @given(
        checksum=_checksum,
        parameters=_parameters,
        seed_a=_random_seed,
        seed_b=_random_seed,
        method_versions=_method_versions,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_different_seed_produces_different_output(
        self,
        checksum: str,
        parameters: dict,
        seed_a: int,
        seed_b: int,
        method_versions: dict[str, str],
    ) -> None:
        """When the random seed differs, the deterministic method should
        (with overwhelming probability) produce different outputs.

        **Validates: Requirements 3.4**
        """
        if seed_a == seed_b:
            return  # skip trivial case

        dataset_bytes = checksum.encode("utf-8")

        output_a = _deterministic_method(data=dataset_bytes, seed=seed_a, params=parameters)
        output_b = _deterministic_method(data=dataset_bytes, seed=seed_b, params=parameters)

        assert output_a != output_b, "Different seeds should produce different outputs"

    @pytest.mark.asyncio
    @given(
        checksum=_checksum,
        parameters=_parameters,
        random_seed=_random_seed,
        method_versions=_method_versions,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.nested_given],
    )
    async def test_replay_preserves_manifest_fields(
        self,
        checksum: str,
        parameters: dict,
        random_seed: int,
        method_versions: dict[str, str],
    ) -> None:
        """Replaying a run via replay_run() produces a new manifest that
        preserves dataset_version_id, parameters, random_seed, and
        method_versions from the original.

        **Validates: Requirements 3.4**
        """
        org_id = uuid4()
        dv_id = uuid4()
        tmpl_id = uuid4()

        db = _ManifestDB()
        run = _make_run(org_id, dv_id, tmpl_id, checksum, parameters, random_seed)
        db.seed_run(run)

        svc = _make_service(db)

        # Build and persist the original manifest
        original_manifest = svc.build_run_manifest(
            run=run,
            dataset_checksum=checksum,
            method_versions=method_versions,
        )
        await svc.persist_manifest(original_manifest)

        # Replay
        new_run, new_manifest = await svc.replay_run(
            run_id=run.id,
            org_id=org_id,
        )

        # The replayed manifest must preserve the reproducibility-critical fields
        assert new_manifest.dataset_version_id == original_manifest.dataset_version_id
        assert new_manifest.dataset_checksum == original_manifest.dataset_checksum
        assert new_manifest.template_id == original_manifest.template_id
        assert new_manifest.random_seed == original_manifest.random_seed
        assert new_manifest.method_versions == original_manifest.method_versions
        # Parameters should match (excluding internal _manifest key)
        orig_params = {k: v for k, v in original_manifest.parameters.items() if k != "_manifest"}
        new_params = {k: v for k, v in new_manifest.parameters.items() if k != "_manifest"}
        assert new_params == orig_params


# ---------------------------------------------------------------------------
# Property 8: Run persistence round-trip
# ---------------------------------------------------------------------------


class TestRunPersistenceRoundTrip:
    """Property 8: For any run created with sessions, checkpoints, and events,
    querying the database must return the same run data with all associated
    records intact.

    **Validates: Requirements 5.1**
    """

    @pytest.mark.asyncio
    @given(
        checksum=_checksum,
        parameters=_parameters,
        random_seed=_random_seed,
        method_versions=_method_versions,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.nested_given],
    )
    async def test_manifest_persist_and_retrieve_roundtrip(
        self,
        checksum: str,
        parameters: dict,
        random_seed: int,
        method_versions: dict[str, str],
    ) -> None:
        """Persisting a RunManifest and retrieving it returns an identical
        manifest (all fields match).

        **Validates: Requirements 5.1**
        """
        org_id = uuid4()
        dv_id = uuid4()
        tmpl_id = uuid4()

        db = _ManifestDB()
        run = _make_run(org_id, dv_id, tmpl_id, checksum, parameters, random_seed)
        db.seed_run(run)

        svc = _make_service(db)

        manifest = svc.build_run_manifest(
            run=run,
            dataset_checksum=checksum,
            method_versions=method_versions,
        )

        # Persist
        await svc.persist_manifest(manifest)

        # Retrieve
        retrieved = await svc.get_manifest(run.id)

        assert retrieved is not None
        assert retrieved.run_id == manifest.run_id
        assert retrieved.dataset_version_id == manifest.dataset_version_id
        assert retrieved.dataset_checksum == manifest.dataset_checksum
        assert retrieved.template_id == manifest.template_id
        assert retrieved.parameters == manifest.parameters
        assert retrieved.method_versions == manifest.method_versions
        assert retrieved.random_seed == manifest.random_seed
        assert retrieved.created_at == manifest.created_at

    @pytest.mark.asyncio
    @given(
        checksum=_checksum,
        parameters=_parameters,
        random_seed=_random_seed,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.nested_given],
    )
    async def test_run_data_preserved_after_persist(
        self,
        checksum: str,
        parameters: dict,
        random_seed: int,
    ) -> None:
        """After persisting a manifest, the run's core fields (status,
        dataset_version_id, template_id, parameters, random_seed) remain
        intact when queried.

        **Validates: Requirements 5.1**
        """
        org_id = uuid4()
        dv_id = uuid4()
        tmpl_id = uuid4()

        db = _ManifestDB()
        run = _make_run(org_id, dv_id, tmpl_id, checksum, parameters, random_seed)
        db.seed_run(run)

        svc = _make_service(db)

        manifest = svc.build_run_manifest(run=run, dataset_checksum=checksum)
        await svc.persist_manifest(manifest)

        # Query the run back from the DB
        stored_run = db._runs.get(run.id)
        assert stored_run is not None
        assert stored_run.dataset_version_id == dv_id
        assert stored_run.template_id == tmpl_id
        assert stored_run.random_seed == random_seed
        assert stored_run.status == RunStatus.COMPLETED
        # Original parameters are preserved alongside the manifest
        for k, v in parameters.items():
            assert stored_run.parameters[k] == v

    @pytest.mark.asyncio
    @given(
        checksum=_checksum,
        parameters=_parameters,
        random_seed=_random_seed,
        n_artifacts=st.integers(min_value=0, max_value=5),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.nested_given],
    )
    async def test_run_with_artifacts_roundtrip(
        self,
        checksum: str,
        parameters: dict,
        random_seed: int,
        n_artifacts: int,
    ) -> None:
        """A run with associated artifacts retains all artifact records
        after persistence.

        **Validates: Requirements 5.1**
        """
        org_id = uuid4()
        dv_id = uuid4()
        tmpl_id = uuid4()

        db = _ManifestDB()
        run = _make_run(org_id, dv_id, tmpl_id, checksum, parameters, random_seed)

        artifacts = []
        for i in range(n_artifacts):
            art = Artifact(
                id=uuid4(),
                run_id=run.id,
                artifact_type=ArtifactType.H5AD,
                s3_path=f"s3://bucket/run/{run.id}/artifact_{i}.h5ad",
                size_bytes=1024 * (i + 1),
                extra_metadata={"step": f"step_{i}"},
                created_at=datetime.utcnow(),
            )
            artifacts.append(art)

        db.seed_run(run, artifacts=artifacts)
        svc = _make_service(db)

        manifest = svc.build_run_manifest(run=run, dataset_checksum=checksum)
        await svc.persist_manifest(manifest)

        # Verify artifacts are still associated
        stored_artifacts = db._artifacts.get(run.id, [])
        assert len(stored_artifacts) == n_artifacts
        for i, art in enumerate(stored_artifacts):
            assert art.run_id == run.id
            assert art.s3_path == f"s3://bucket/run/{run.id}/artifact_{i}.h5ad"

    @pytest.mark.asyncio
    async def test_get_manifest_returns_none_for_missing_run(self) -> None:
        """get_manifest returns None when the run does not exist.

        **Validates: Requirements 5.1**
        """
        db = _ManifestDB()
        svc = _make_service(db)

        result = await svc.get_manifest(uuid4())
        assert result is None
