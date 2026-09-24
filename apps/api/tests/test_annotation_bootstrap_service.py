"""Tests for bootstrapping annotation revisions from completed run artifacts."""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import anndata as ad
import numpy as np
import pytest
import pytest_asyncio
from zerna_contracts.enums import ArtifactType, RunStatus
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.models import (
    Artifact,
    Base,
    Dataset,
    DatasetVersion,
    Organization,
    PipelineTemplate,
    Run,
    User,
)
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


class DummyAuditService:
    async def audit_log(self, *args, **kwargs) -> None:
        return None


class DummyS3Client:
    def __init__(self, source_path: Path) -> None:
        self.source_path = source_path

    def download_file(self, bucket: str, key: str, destination: str) -> None:
        del bucket, key
        shutil.copyfile(self.source_path, destination)


class DummyS3Service:
    def __init__(self, source_path: Path) -> None:
        self.s3_client = DummyS3Client(source_path)
        self.artifacts_bucket = "zerna-artifacts-dev"


async def _make_run_with_artifact(
    session: AsyncSession, artifact_path: str
) -> tuple[Organization, User, Run]:
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
        id=uuid4(),
        dataset_id=dataset.id,
        version="v1",
        s3_path="s3://datasets/source.h5ad",
    )
    session.add(version)
    await session.flush()

    template = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name="robust",
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
    await session.flush()

    artifact = Artifact(
        id=uuid4(),
        run_id=run.id,
        artifact_type=ArtifactType.H5AD,
        s3_path=artifact_path,
        size_bytes=123,
        extra_metadata={},
    )
    session.add(artifact)
    await session.commit()
    return org, user, run


def _write_h5ad(path: Path, obs_columns: dict[str, list[object]]) -> None:
    adata = ad.AnnData(X=np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32))
    adata.obs_names = ["cell_0", "cell_1"]
    adata.var_names = ["CD3E", "LYZ"]
    for column, values in obs_columns.items():
        adata.obs[column] = values
    adata.write_h5ad(path)


@pytest.mark.asyncio
async def test_bootstrap_revision_uses_hierarchical_obs_columns(async_engine, tmp_path: Path):
    source = tmp_path / "hierarchical.h5ad"
    _write_h5ad(
        source,
        {
            "annotation_tissue": ["blood", "blood"],
            "annotation_lineage": ["Lymphoid", "Myeloid"],
            "annotation_cell_type": ["T cell", "Monocyte"],
            "annotation_confidence": [0.93, 0.87],
        },
    )

    session = await get_clean_session(async_engine)
    org, user, run = await _make_run_with_artifact(session, "runs/test/processed.h5ad")

    svc = AnnotationService(
        session,
        audit_service=DummyAuditService(),
        s3_service=DummyS3Service(source),
    )
    revision = await svc.bootstrap_revision_from_run(run.id, user.id, org.id)

    assert revision.method == "run_bootstrap"
    assert revision.annotations["cell_0"]["cell_type"] == "T cell"
    assert revision.annotations["cell_0"]["lineage"] == "Lymphoid"
    assert revision.annotations["cell_1"]["confidence"] == pytest.approx(0.87)
    await session.close()


@pytest.mark.asyncio
async def test_bootstrap_revision_falls_back_to_celltypist_columns(async_engine, tmp_path: Path):
    source = tmp_path / "celltypist_only.h5ad"
    _write_h5ad(
        source,
        {
            "celltypist_cell_type": ["T-cell", "Macrophage"],
            "celltypist_conf_score": [0.91, 0.76],
        },
    )

    session = await get_clean_session(async_engine)
    org, user, run = await _make_run_with_artifact(
        session, "s3://artifact-bucket/runs/test/processed.h5ad"
    )

    svc = AnnotationService(
        session,
        audit_service=DummyAuditService(),
        s3_service=DummyS3Service(source),
    )
    revision = await svc.bootstrap_revision_from_run(run.id, user.id, org.id)

    assert revision.annotations["cell_0"]["cell_type"] == "T cell"
    assert revision.annotations["cell_0"]["lineage"] == "Lymphoid"
    assert revision.annotations["cell_1"]["cell_type"] == "Macrophage"
    assert revision.annotations["cell_1"]["lineage"] == "Myeloid"
    await session.close()
