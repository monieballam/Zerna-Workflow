"""Unit tests for ExportService - h5ad export with complete data."""

import json
import tempfile
from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import anndata as ad
import numpy as np
import pandas as pd
import pytest
import pytest_asyncio
from zerna_contracts.enums import ArtifactType, RunStatus

from apps.api.models.annotation import AnnotationRevision
from apps.api.models.organization import Organization
from apps.api.models.pipeline import Artifact, Run
from apps.api.services.export_service import ExportService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def organization(async_session):
    org = Organization(id=uuid4(), name="Test Org", storage_quota_gb=100, compute_quota_runs=5)
    async_session.add(org)
    await async_session.commit()
    await async_session.refresh(org)
    return org


@pytest_asyncio.fixture
async def run(async_session, organization):
    from apps.api.models.dataset import Dataset, DatasetVersion
    from apps.api.models.pipeline import PipelineTemplate

    dataset = Dataset(
        id=uuid4(),
        organization_id=organization.id,
        name="DS",
        extra_metadata={},
    )
    async_session.add(dataset)
    await async_session.flush()

    dv = DatasetVersion(
        id=uuid4(),
        dataset_id=dataset.id,
        version="v1",
        s3_path="s3://bucket/ds/file.h5ad",
        cell_count=100,
        gene_count=200,
        file_format="h5ad",
    )
    async_session.add(dv)
    await async_session.flush()

    template = PipelineTemplate(
        id=uuid4(),
        organization_id=organization.id,
        name="tmpl",
        version="1.0",
        definition={"steps": []},
    )
    async_session.add(template)
    await async_session.flush()

    r = Run(
        id=uuid4(),
        organization_id=organization.id,
        dataset_version_id=dv.id,
        template_id=template.id,
        status=RunStatus.COMPLETED,
        parameters={"resolution": 0.5},
        software_versions={"scanpy": "1.9.3"},
        random_seed=42,
        started_at=datetime(2024, 1, 1, 10, 0),
        completed_at=datetime(2024, 1, 1, 11, 0),
        created_at=datetime(2024, 1, 1, 9, 0),
    )
    async_session.add(r)
    await async_session.commit()
    await async_session.refresh(r)
    return r


@pytest_asyncio.fixture
async def h5ad_artifact(async_session, run):
    artifact = Artifact(
        id=uuid4(),
        run_id=run.id,
        artifact_type=ArtifactType.H5AD,
        s3_path=f"test-artifacts-bucket/{run.organization_id}/runs/{run.id}/h5ad/result.h5ad",
        size_bytes=1024,
        extra_metadata={},
    )
    async_session.add(artifact)
    await async_session.commit()
    await async_session.refresh(artifact)
    return artifact


@pytest_asyncio.fixture
async def annotation_revision(async_session, run):
    from apps.api.models.organization import User

    user = User(id=uuid4(), email="bio@example.com", hashed_password="x")
    async_session.add(user)
    await async_session.flush()

    rev = AnnotationRevision(
        id=uuid4(),
        run_id=run.id,
        revision_number=1,
        annotations={
            "cell_0": {
                "tissue": "lung",
                "lineage": "epithelial",
                "cell_type": "AT2",
                "confidence": 0.95,
            },
            "cell_1": {
                "tissue": "lung",
                "lineage": "immune",
                "cell_type": "T cell",
                "confidence": 0.88,
            },
        },
        method="celltypist",
        created_by=user.id,
        created_at=datetime(2024, 1, 1, 12, 0),
    )
    async_session.add(rev)
    await async_session.commit()
    await async_session.refresh(rev)
    return rev


def _make_mock_s3_service(artifacts_bucket: str = "test-artifacts-bucket") -> MagicMock:
    s3 = MagicMock()
    s3.artifacts_bucket = artifacts_bucket
    s3.upload_file = MagicMock(return_value={"etag": "abc", "size": 100, "checksum": "xyz"})
    s3.s3_client = MagicMock()
    return s3


def _write_adata_safe(adata: ad.AnnData, path: str) -> None:
    """Write AnnData to h5ad, converting Arrow-backed string columns to object dtype first."""
    import copy

    adata = copy.copy(adata)
    # Fix index dtypes
    if adata.obs.index.dtype != object:
        adata.obs.index = adata.obs.index.astype("object")
    if adata.var.index.dtype != object:
        adata.var.index = adata.var.index.astype("object")
    # Fix obs columns with Arrow-backed or categorical Arrow strings
    obs = adata.obs.copy()
    for col in obs.columns:
        col_dtype_str = str(obs[col].dtype)
        if col_dtype_str in ("string[pyarrow]", "string[pyarrow_numpy]", "str"):
            obs[col] = obs[col].astype("object")
        elif hasattr(obs[col], "cat"):
            cat_dtype = str(obs[col].cat.categories.dtype)
            if cat_dtype in ("string[pyarrow]", "string[pyarrow_numpy]", "str"):
                obs[col] = obs[col].astype(str).astype("category")
    adata.obs = obs
    adata.write_h5ad(path)


# ---------------------------------------------------------------------------
# Tests: verify_export_completeness
# ---------------------------------------------------------------------------


def _make_adata(n_obs: int = 5, n_vars: int = 3) -> ad.AnnData:
    """Create an AnnData with an explicit object-dtype obs index (h5ad-compatible)."""
    obs_names = [f"cell_{i}" for i in range(n_obs)]
    var_names = [f"gene_{i}" for i in range(n_vars)]
    obs = pd.DataFrame(index=pd.Index(obs_names, dtype="object"))
    var = pd.DataFrame(index=pd.Index(var_names, dtype="object"))
    X = np.zeros((n_obs, n_vars)) if n_obs > 0 else np.zeros((0, n_vars))
    return ad.AnnData(X=X, obs=obs, var=var)


def test_verify_export_completeness_valid_file():
    """Round-trip: a properly written h5ad passes verification."""
    svc = ExportService(db=MagicMock(), s3_service=_make_mock_s3_service())

    adata = _make_adata(5, 3)
    adata.uns["zerna_run_metadata"] = {
        "run_id": str(uuid4()),
        "org_id": str(uuid4()),
        "exported_at": "2024-01-01T00:00:00+00:00",
    }

    with tempfile.NamedTemporaryFile(suffix=".h5ad", delete=False) as f:
        tmp_path = f.name

    adata.write_h5ad(tmp_path)
    assert svc.verify_export_completeness(tmp_path) is True


def test_verify_export_completeness_missing_metadata():
    """h5ad without zerna_run_metadata fails verification."""
    svc = ExportService(db=MagicMock(), s3_service=_make_mock_s3_service())

    adata = _make_adata(5, 3)

    with tempfile.NamedTemporaryFile(suffix=".h5ad", delete=False) as f:
        tmp_path = f.name

    adata.write_h5ad(tmp_path)
    assert svc.verify_export_completeness(tmp_path) is False


def test_verify_export_completeness_empty_cells():
    """h5ad with zero cells fails verification."""
    svc = ExportService(db=MagicMock(), s3_service=_make_mock_s3_service())

    adata = _make_adata(0, 3)
    adata.uns["zerna_run_metadata"] = {
        "run_id": str(uuid4()),
        "org_id": str(uuid4()),
        "exported_at": "2024-01-01T00:00:00+00:00",
    }

    with tempfile.NamedTemporaryFile(suffix=".h5ad", delete=False) as f:
        tmp_path = f.name

    adata.write_h5ad(tmp_path)
    assert svc.verify_export_completeness(tmp_path) is False


def test_verify_export_completeness_bad_path():
    """Non-existent path returns False without raising."""
    svc = ExportService(db=MagicMock(), s3_service=_make_mock_s3_service())
    assert svc.verify_export_completeness("/nonexistent/path/file.h5ad") is False


def test_verify_export_completeness_partial_metadata():
    """h5ad missing required keys in zerna_run_metadata fails."""
    svc = ExportService(db=MagicMock(), s3_service=_make_mock_s3_service())

    adata = _make_adata(3, 2)
    adata.uns["zerna_run_metadata"] = {"run_id": str(uuid4())}  # missing org_id, exported_at

    with tempfile.NamedTemporaryFile(suffix=".h5ad", delete=False) as f:
        tmp_path = f.name

    adata.write_h5ad(tmp_path)
    assert svc.verify_export_completeness(tmp_path) is False


# ---------------------------------------------------------------------------
# Tests: _add_annotations
# ---------------------------------------------------------------------------


def test_add_annotations_per_cell_format():
    """Per-cell annotation dict is mapped to obs columns."""
    svc = ExportService(db=MagicMock(), s3_service=_make_mock_s3_service())

    obs_names = ["cell_0", "cell_1"]
    adata = ad.AnnData(
        X=np.zeros((2, 3)),
        obs=pd.DataFrame(index=pd.Index(obs_names, dtype="object")),
    )

    rev = MagicMock(spec=AnnotationRevision)
    rev.id = uuid4()
    rev.revision_number = 1
    rev.method = "celltypist"
    rev.knowledge_pack_id = None
    rev.approved_by = None
    rev.approved_at = None
    rev.created_at = datetime(2024, 1, 1)
    rev.annotations = {
        "cell_0": {"cell_type": "AT2", "confidence": 0.95},
        "cell_1": {"cell_type": "T cell", "confidence": 0.88},
    }

    result = svc._add_annotations(adata, [rev])

    assert "zerna_cell_type" in result.obs.columns
    assert result.obs.loc["cell_0", "zerna_cell_type"] == "AT2"
    assert "zerna_annotation_revisions" in result.uns


def test_add_annotations_no_revisions():
    """No revisions leaves adata unchanged."""
    svc = ExportService(db=MagicMock(), s3_service=_make_mock_s3_service())
    adata = ad.AnnData(X=np.zeros((2, 3)))
    result = svc._add_annotations(adata, [])
    assert "zerna_annotation_revisions" not in result.uns


def test_add_annotations_latest_revision_wins():
    """When multiple revisions exist, the latest one is applied to obs."""
    svc = ExportService(db=MagicMock(), s3_service=_make_mock_s3_service())

    obs_names = ["cell_0"]
    adata = ad.AnnData(
        X=np.zeros((1, 2)),
        obs=pd.DataFrame(index=pd.Index(obs_names, dtype="object")),
    )

    def _make_rev(num, cell_type):
        rev = MagicMock(spec=AnnotationRevision)
        rev.id = uuid4()
        rev.revision_number = num
        rev.method = "manual"
        rev.knowledge_pack_id = None
        rev.approved_by = None
        rev.approved_at = None
        rev.created_at = datetime(2024, 1, num)
        rev.annotations = {"cell_0": {"cell_type": cell_type}}
        return rev

    result = svc._add_annotations(adata, [_make_rev(1, "AT2"), _make_rev(2, "Club cell")])
    assert result.obs.loc["cell_0", "zerna_cell_type"] == "Club cell"
    assert len(json.loads(result.uns["zerna_annotation_revisions"])) == 2


# ---------------------------------------------------------------------------
# Tests: _add_run_metadata
# ---------------------------------------------------------------------------


def test_add_run_metadata_populates_uns(run):
    """Run metadata is stored in uns with required keys."""
    svc = ExportService(db=MagicMock(), s3_service=_make_mock_s3_service())
    adata = ad.AnnData(X=np.zeros((2, 2)))

    result = svc._add_run_metadata(adata, run, [])

    meta = result.uns["zerna_run_metadata"]
    assert meta["run_id"] == str(run.id)
    assert meta["org_id"] == str(run.organization_id)
    assert meta["parameters"] == {"resolution": 0.5}
    assert meta["software_versions"] == {"scanpy": "1.9.3"}
    assert meta["random_seed"] == 42
    assert "exported_at" in meta
    assert json.loads(result.uns["zerna_artifacts"]) == []


# ---------------------------------------------------------------------------
# Tests: export_h5ad (integration-style with mocked S3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_h5ad_no_artifact_creates_minimal(async_session, run):
    """When no h5ad artifact exists, export creates a minimal AnnData."""
    mock_s3 = _make_mock_s3_service()
    svc = ExportService(db=async_session, s3_service=mock_s3)

    s3_path = await svc.export_h5ad(run.id, run.organization_id)

    assert s3_path == f"{run.organization_id}/exports/{run.id}/export.h5ad"
    mock_s3.upload_file.assert_called_once()
    call_kwargs = mock_s3.upload_file.call_args
    assert call_kwargs.kwargs["s3_path"] == s3_path


@pytest.mark.asyncio
async def test_export_h5ad_wrong_org_raises(async_session, run):
    """Exporting with wrong org_id raises ValueError."""
    svc = ExportService(db=async_session, s3_service=_make_mock_s3_service())
    with pytest.raises(ValueError, match="not found"):
        await svc.export_h5ad(run.id, uuid4())


@pytest.mark.asyncio
async def test_export_h5ad_with_artifact_downloads_and_enriches(async_session, run, h5ad_artifact):
    """When h5ad artifact exists, it is downloaded, enriched, and re-uploaded."""
    # Build a small real AnnData to "download"
    source_adata = ad.AnnData(
        X=np.random.rand(10, 5),
        obs=pd.DataFrame(index=pd.Index([f"cell_{i}" for i in range(10)], dtype="object")),
        var=pd.DataFrame(index=pd.Index([f"gene_{i}" for i in range(5)], dtype="object")),
    )

    mock_s3 = _make_mock_s3_service()

    def fake_download(bucket, key, local_path):
        source_adata.write_h5ad(local_path)

    mock_s3.s3_client.download_file.side_effect = fake_download

    svc = ExportService(db=async_session, s3_service=mock_s3)
    s3_path = await svc.export_h5ad(run.id, run.organization_id)

    assert s3_path.endswith("export.h5ad")
    mock_s3.s3_client.download_file.assert_called_once()
    mock_s3.upload_file.assert_called_once()


@pytest.mark.asyncio
async def test_export_h5ad_with_annotations(async_session, run, annotation_revision):
    """Annotations from AnnotationRevision are included in the export."""
    import shutil

    mock_s3 = _make_mock_s3_service()

    captured_files = []

    def capture_upload(file_path, bucket, s3_path, content_type=None):
        with tempfile.NamedTemporaryFile(suffix=".h5ad", delete=False) as f:
            dest = f.name
        shutil.copy2(str(file_path), dest)
        captured_files.append(dest)
        return {"etag": "abc", "size": 100, "checksum": "xyz"}

    mock_s3.upload_file.side_effect = capture_upload

    svc = ExportService(db=async_session, s3_service=mock_s3)
    await svc.export_h5ad(run.id, run.organization_id)

    assert len(captured_files) == 1
    # Load the exported file and verify annotations are present
    exported = ad.read_h5ad(captured_files[0])
    assert "zerna_annotation_revisions" in exported.uns
    revisions = json.loads(exported.uns["zerna_annotation_revisions"])
    assert len(revisions) == 1
    assert revisions[0]["method"] == "celltypist"


@pytest.mark.asyncio
async def test_export_h5ad_s3_path_format(async_session, run):
    """Exported S3 path follows org_id/exports/run_id/export.h5ad pattern."""
    mock_s3 = _make_mock_s3_service()
    svc = ExportService(db=async_session, s3_service=mock_s3)

    s3_path = await svc.export_h5ad(run.id, run.organization_id)

    expected = f"{run.organization_id}/exports/{run.id}/export.h5ad"
    assert s3_path == expected


@pytest.mark.asyncio
async def test_export_h5ad_run_metadata_in_output(async_session, run):
    """Exported h5ad contains run metadata in uns."""
    import shutil

    mock_s3 = _make_mock_s3_service()
    captured = []

    def capture(file_path, bucket, s3_path, content_type=None):
        # Copy to a persistent temp file before the TemporaryDirectory is cleaned up
        with tempfile.NamedTemporaryFile(suffix=".h5ad", delete=False) as f:
            dest = f.name
        shutil.copy2(str(file_path), dest)
        captured.append(dest)
        return {"etag": "x", "size": 1, "checksum": "y"}

    mock_s3.upload_file.side_effect = capture

    svc = ExportService(db=async_session, s3_service=mock_s3)
    await svc.export_h5ad(run.id, run.organization_id)

    exported = ad.read_h5ad(captured[0])
    meta = exported.uns["zerna_run_metadata"]
    assert meta["run_id"] == str(run.id)
    assert meta["parameters"] == {"resolution": 0.5}
    assert meta["software_versions"] == {"scanpy": "1.9.3"}
    assert meta["random_seed"] == 42


# ---------------------------------------------------------------------------
# Tests: export_de_results_csv
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_de_results_csv_s3_path_format(async_session, run):
    """Exported DE results CSV S3 path follows org_id/exports/run_id/de_results.csv pattern."""
    mock_s3 = _make_mock_s3_service()
    svc = ExportService(db=async_session, s3_service=mock_s3)

    s3_path = await svc.export_de_results_csv(run.id, run.organization_id)

    expected = f"{run.organization_id}/exports/{run.id}/de_results.csv"
    assert s3_path == expected


@pytest.mark.asyncio
async def test_export_de_results_csv_no_artifact_creates_minimal(async_session, run):
    """When no DE_RESULTS artifact exists, a minimal CSV with correct headers is created."""
    import shutil

    mock_s3 = _make_mock_s3_service()
    captured = []

    def capture_upload(file_path, bucket, s3_path, content_type=None):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            dest = f.name
        shutil.copy2(str(file_path), dest)
        captured.append(dest)
        return {"etag": "abc", "size": 10, "checksum": "xyz"}

    mock_s3.upload_file.side_effect = capture_upload

    svc = ExportService(db=async_session, s3_service=mock_s3)
    await svc.export_de_results_csv(run.id, run.organization_id)

    assert len(captured) == 1
    df = pd.read_csv(captured[0])
    expected_cols = ["gene", "cluster", "log_fold_change", "p_value", "adjusted_p_value"]
    assert list(df.columns) == expected_cols
    assert len(df) == 0


@pytest.mark.asyncio
async def test_export_de_results_csv_with_artifact(async_session, run):
    """When DE_RESULTS artifact exists, its data is downloaded and re-uploaded."""
    import shutil

    # Create a DE_RESULTS artifact in the DB
    de_artifact = Artifact(
        id=uuid4(),
        run_id=run.id,
        artifact_type=ArtifactType.DE_RESULTS,
        s3_path=f"test-artifacts-bucket/{run.organization_id}/runs/{run.id}/de_results/de_results.csv",
        size_bytes=512,
        extra_metadata={},
    )
    async_session.add(de_artifact)
    await async_session.commit()

    # Build a real CSV to "download"
    source_df = pd.DataFrame(
        {
            "gene": ["BRCA1", "TP53"],
            "cluster": ["0", "1"],
            "log_fold_change": [1.5, -0.8],
            "p_value": [0.001, 0.05],
            "adjusted_p_value": [0.01, 0.1],
        }
    )

    mock_s3 = _make_mock_s3_service()
    captured = []

    def fake_download(bucket, key, local_path):
        source_df.to_csv(local_path, index=False)

    def capture_upload(file_path, bucket, s3_path, content_type=None):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            dest = f.name
        shutil.copy2(str(file_path), dest)
        captured.append(dest)
        return {"etag": "abc", "size": 100, "checksum": "xyz"}

    mock_s3.s3_client.download_file.side_effect = fake_download
    mock_s3.upload_file.side_effect = capture_upload

    svc = ExportService(db=async_session, s3_service=mock_s3)
    s3_path = await svc.export_de_results_csv(run.id, run.organization_id)

    assert s3_path.endswith("de_results.csv")
    assert len(captured) == 1
    df = pd.read_csv(captured[0])
    expected_cols = ["gene", "cluster", "log_fold_change", "p_value", "adjusted_p_value"]
    assert list(df.columns) == expected_cols
    assert len(df) == 2
    assert df["gene"].tolist() == ["BRCA1", "TP53"]


@pytest.mark.asyncio
async def test_export_de_results_csv_wrong_org_raises(async_session, run):
    """Exporting DE results with wrong org_id raises ValueError."""
    svc = ExportService(db=async_session, s3_service=_make_mock_s3_service())
    with pytest.raises(ValueError, match="not found"):
        await svc.export_de_results_csv(run.id, uuid4())


@pytest.mark.asyncio
async def test_export_de_results_csv_download_failure_creates_minimal(async_session, run):
    """When S3 download fails, a minimal CSV with correct headers is created."""
    import shutil

    de_artifact = Artifact(
        id=uuid4(),
        run_id=run.id,
        artifact_type=ArtifactType.DE_RESULTS,
        s3_path=f"test-artifacts-bucket/{run.organization_id}/runs/{run.id}/de_results/de_results.csv",
        size_bytes=512,
        extra_metadata={},
    )
    async_session.add(de_artifact)
    await async_session.commit()

    mock_s3 = _make_mock_s3_service()
    captured = []

    mock_s3.s3_client.download_file.side_effect = Exception("S3 connection error")

    def capture_upload(file_path, bucket, s3_path, content_type=None):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            dest = f.name
        shutil.copy2(str(file_path), dest)
        captured.append(dest)
        return {"etag": "abc", "size": 10, "checksum": "xyz"}

    mock_s3.upload_file.side_effect = capture_upload

    svc = ExportService(db=async_session, s3_service=mock_s3)
    await svc.export_de_results_csv(run.id, run.organization_id)

    assert len(captured) == 1
    df = pd.read_csv(captured[0])
    expected_cols = ["gene", "cluster", "log_fold_change", "p_value", "adjusted_p_value"]
    assert list(df.columns) == expected_cols
    assert len(df) == 0


# ---------------------------------------------------------------------------
# Tests: export_embeddings_csv
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_embeddings_csv_s3_path_format(async_session, run):
    """Exported embeddings CSV S3 path follows org_id/exports/run_id/embeddings.csv pattern."""
    mock_s3 = _make_mock_s3_service()
    svc = ExportService(db=async_session, s3_service=mock_s3)

    s3_path = await svc.export_embeddings_csv(run.id, run.organization_id)

    expected = f"{run.organization_id}/exports/{run.id}/embeddings.csv"
    assert s3_path == expected


@pytest.mark.asyncio
async def test_export_embeddings_csv_no_artifact_creates_minimal(async_session, run):
    """When no H5AD artifact exists, a minimal CSV with correct headers is created."""
    import shutil

    mock_s3 = _make_mock_s3_service()
    captured = []

    def capture_upload(file_path, bucket, s3_path, content_type=None):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            dest = f.name
        shutil.copy2(str(file_path), dest)
        captured.append(dest)
        return {"etag": "abc", "size": 10, "checksum": "xyz"}

    mock_s3.upload_file.side_effect = capture_upload

    svc = ExportService(db=async_session, s3_service=mock_s3)
    await svc.export_embeddings_csv(run.id, run.organization_id)

    assert len(captured) == 1
    df = pd.read_csv(captured[0])
    expected_cols = ["cell_id", "umap_1", "umap_2", "tsne_1", "tsne_2"]
    assert list(df.columns) == expected_cols
    assert len(df) == 0


@pytest.mark.asyncio
async def test_export_embeddings_csv_with_h5ad_artifact(async_session, run, h5ad_artifact):
    """When H5AD artifact exists, embeddings and obs metadata are extracted and exported."""
    import shutil

    # Build a real AnnData with UMAP, tSNE, and obs metadata
    n_cells = 5
    obs_names = [f"cell_{i}" for i in range(n_cells)]
    obs_df = pd.DataFrame(
        {
            "cluster": np.array(["0", "1", "0", "1", "2"], dtype=object),
            "cell_type": np.array(["AT2", "T cell", "AT2", "B cell", "NK"], dtype=object),
        },
        index=pd.Index(obs_names, dtype="object"),
    )
    source_adata = ad.AnnData(
        X=np.zeros((n_cells, 3)),
        obs=obs_df,
        var=pd.DataFrame(index=pd.Index([f"gene_{i}" for i in range(3)], dtype="object")),
    )
    source_adata.obsm["X_umap"] = np.random.rand(n_cells, 2)
    source_adata.obsm["X_tsne"] = np.random.rand(n_cells, 2)

    mock_s3 = _make_mock_s3_service()
    captured = []

    def fake_download(bucket, key, local_path):
        _write_adata_safe(source_adata, local_path)

    def capture_upload(file_path, bucket, s3_path, content_type=None):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            dest = f.name
        shutil.copy2(str(file_path), dest)
        captured.append(dest)
        return {"etag": "abc", "size": 200, "checksum": "xyz"}

    mock_s3.s3_client.download_file.side_effect = fake_download
    mock_s3.upload_file.side_effect = capture_upload

    svc = ExportService(db=async_session, s3_service=mock_s3)
    s3_path = await svc.export_embeddings_csv(run.id, run.organization_id)

    assert s3_path.endswith("embeddings.csv")
    assert len(captured) == 1

    df = pd.read_csv(captured[0])
    # Must have base columns
    for col in ["cell_id", "umap_1", "umap_2", "tsne_1", "tsne_2"]:
        assert col in df.columns, f"Missing column: {col}"
    # Must have obs metadata columns
    assert "cluster" in df.columns
    assert "cell_type" in df.columns
    # Correct number of rows
    assert len(df) == n_cells
    # cell_id values match obs_names
    assert df["cell_id"].tolist() == obs_names


@pytest.mark.asyncio
async def test_export_embeddings_csv_missing_embeddings_uses_none(
    async_session, run, h5ad_artifact
):
    """When H5AD has no UMAP/tSNE, embedding columns are present but null."""
    import shutil

    n_cells = 3
    obs_names = [f"cell_{i}" for i in range(n_cells)]
    source_adata = ad.AnnData(
        X=np.zeros((n_cells, 2)),
        obs=pd.DataFrame(index=pd.Index(obs_names, dtype="object")),
        var=pd.DataFrame(index=pd.Index(["g0", "g1"], dtype="object")),
    )
    # No obsm embeddings

    mock_s3 = _make_mock_s3_service()
    captured = []

    def fake_download(bucket, key, local_path):
        _write_adata_safe(source_adata, local_path)

    def capture_upload(file_path, bucket, s3_path, content_type=None):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            dest = f.name
        shutil.copy2(str(file_path), dest)
        captured.append(dest)
        return {"etag": "abc", "size": 50, "checksum": "xyz"}

    mock_s3.s3_client.download_file.side_effect = fake_download
    mock_s3.upload_file.side_effect = capture_upload

    svc = ExportService(db=async_session, s3_service=mock_s3)
    await svc.export_embeddings_csv(run.id, run.organization_id)

    df = pd.read_csv(captured[0])
    for col in ["cell_id", "umap_1", "umap_2", "tsne_1", "tsne_2"]:
        assert col in df.columns
    assert df["umap_1"].isna().all()
    assert df["tsne_1"].isna().all()


@pytest.mark.asyncio
async def test_export_embeddings_csv_wrong_org_raises(async_session, run):
    """Exporting embeddings with wrong org_id raises ValueError."""
    svc = ExportService(db=async_session, s3_service=_make_mock_s3_service())
    with pytest.raises(ValueError, match="not found"):
        await svc.export_embeddings_csv(run.id, uuid4())


@pytest.mark.asyncio
async def test_export_embeddings_csv_download_failure_creates_minimal(
    async_session, run, h5ad_artifact
):
    """When S3 download fails, a minimal embeddings CSV with correct headers is created."""
    import shutil

    mock_s3 = _make_mock_s3_service()
    captured = []

    mock_s3.s3_client.download_file.side_effect = Exception("S3 connection error")

    def capture_upload(file_path, bucket, s3_path, content_type=None):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            dest = f.name
        shutil.copy2(str(file_path), dest)
        captured.append(dest)
        return {"etag": "abc", "size": 10, "checksum": "xyz"}

    mock_s3.upload_file.side_effect = capture_upload

    svc = ExportService(db=async_session, s3_service=mock_s3)
    await svc.export_embeddings_csv(run.id, run.organization_id)

    assert len(captured) == 1
    df = pd.read_csv(captured[0])
    expected_cols = ["cell_id", "umap_1", "umap_2", "tsne_1", "tsne_2"]
    assert list(df.columns) == expected_cols
    assert len(df) == 0


# ---------------------------------------------------------------------------
# Tests: generate_reproducibility_report and _generate_html_report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_reproducibility_report_s3_path_format(async_session, run):
    """Returned S3 path follows org_id/exports/run_id/reproducibility_report.html pattern."""
    mock_s3 = _make_mock_s3_service()
    svc = ExportService(db=async_session, s3_service=mock_s3)

    s3_path = await svc.generate_reproducibility_report(run.id, run.organization_id)

    expected = f"{run.organization_id}/exports/{run.id}/reproducibility_report.html"
    assert s3_path == expected
    mock_s3.upload_file.assert_called_once()
    call_kwargs = mock_s3.upload_file.call_args
    assert call_kwargs.kwargs["s3_path"] == expected
    assert call_kwargs.kwargs["content_type"] == "text/html"


def test_generate_html_report_contains_required_sections(run):
    """HTML report contains run_id, software versions, parameters, and random seed."""
    svc = ExportService(db=MagicMock(), s3_service=_make_mock_s3_service())

    html = svc._generate_html_report(run, [], [])

    assert str(run.id) in html
    # Software versions
    assert "scanpy" in html
    assert "1.9.3" in html
    # Pipeline parameters
    assert "resolution" in html
    assert "0.5" in html
    # Random seed
    assert "42" in html
    # Required structural sections
    assert "<title>" in html
    assert "<h1>" in html
    assert "Software Versions" in html
    assert "Pipeline Parameters" in html
    assert "Random Seeds" in html
    assert "KnowledgePack" in html
    assert "Provenance" in html
    assert "Annotation History" in html


def test_generate_html_report_with_no_software_versions(run):
    """HTML report handles None software_versions gracefully."""
    run.software_versions = None
    svc = ExportService(db=MagicMock(), s3_service=_make_mock_s3_service())

    html = svc._generate_html_report(run, [], [])

    assert "No software versions recorded" in html
    # Report should still be valid HTML with all sections
    assert "<title>" in html
    assert str(run.id) in html


@pytest.mark.asyncio
async def test_generate_reproducibility_report_wrong_org_raises(async_session, run):
    """Generating a report with wrong org_id raises ValueError."""
    svc = ExportService(db=async_session, s3_service=_make_mock_s3_service())

    with pytest.raises(ValueError, match="not found"):
        await svc.generate_reproducibility_report(run.id, uuid4())
