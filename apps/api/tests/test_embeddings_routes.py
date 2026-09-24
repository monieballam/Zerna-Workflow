"""Tests for embedding routes."""

import shutil
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import anndata as ad
import numpy as np
import pandas as pd
import pytest
from zerna_contracts.enums import ArtifactType, RunStatus, UserRole
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.main import app
from apps.api.middleware.auth import get_current_user
from apps.api.models.dataset import Dataset, DatasetVersion
from apps.api.models.organization import organization_users
from apps.api.models.pipeline import Artifact, PipelineTemplate, Run
from apps.api.routes.runs import get_user_org_id


@pytest.mark.asyncio
async def test_embedding_route_uses_h5ad_artifact_and_falls_back_to_tsne(
    async_client,
    async_session: AsyncSession,
    test_user,
    test_organization,
    tmp_path: Path,
):
    dataset = Dataset(
        id=uuid4(),
        organization_id=test_organization.id,
        name="Test dataset",
        description=None,
        extra_metadata={},
    )
    template = PipelineTemplate(
        id=uuid4(),
        organization_id=test_organization.id,
        name="Test template",
        version="1.0.0",
        definition={"methods": ["embed"], "dependencies": {}},
        is_active=True,
    )
    dataset_version = DatasetVersion(
        id=uuid4(),
        dataset_id=dataset.id,
        version="v1",
        s3_path="datasets/test/v1.h5ad",
        file_format="h5ad",
        extra_metadata={},
    )
    run = Run(
        id=uuid4(),
        organization_id=test_organization.id,
        dataset_version_id=dataset_version.id,
        template_id=template.id,
        status=RunStatus.COMPLETED,
        parameters={},
        software_versions=None,
        random_seed=42,
    )

    async_session.add_all([dataset, template, dataset_version, run])
    await async_session.execute(
        insert(organization_users).values(
            organization_id=test_organization.id,
            user_id=test_user.id,
            role=UserRole.ADMIN,
        )
    )
    await async_session.commit()

    h5ad_artifact = Artifact(
        id=uuid4(),
        run_id=run.id,
        artifact_type=ArtifactType.H5AD,
        s3_path="runs/test/processed.h5ad",
        size_bytes=456,
        extra_metadata={},
    )
    csv_artifact = Artifact(
        id=uuid4(),
        run_id=run.id,
        artifact_type=ArtifactType.LIANA_RESULTS,
        s3_path="runs/test/liana_results.csv",
        size_bytes=123,
        extra_metadata={},
    )
    async_session.add_all([h5ad_artifact, csv_artifact])
    await async_session.commit()

    source_h5ad = tmp_path / "processed.h5ad"
    adata = ad.AnnData(np.ones((4, 3)))
    adata.obs = pd.DataFrame(
        {
            "cluster": pd.Categorical(["0", "0", "1", "1"]),
            "CellType": ["T cell", "T cell", "B cell", "B cell"],
        },
        index=[f"cell-{i}" for i in range(4)],
    )
    adata.uns["zerna_cluster_annotations"] = {
        "0": {"cell_type": "T cell"},
        "1": {"cell_type": "B cell"},
    }
    adata.obsm["X_tsne"] = np.array(
        [[1.0, 0.0], [0.5, 0.1], [-0.4, -0.2], [-1.0, 0.3]],
        dtype=float,
    )
    adata.write_h5ad(source_h5ad)

    class DummyS3Client:
        def get_object(self, Bucket: str, Key: str):  # noqa: N803
            del Bucket, Key
            raise FileNotFoundError("embedding cache not present")

        def download_file(self, bucket: str, key: str, destination: str) -> None:
            del bucket, key
            shutil.copyfile(source_h5ad, destination)

    async def override_get_current_user():
        return test_user

    async def override_get_user_org_id():
        return test_organization.id

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_user_org_id] = override_get_user_org_id
    try:
        with patch("boto3.client", return_value=DummyS3Client()):
            response = await async_client.get(f"/v1/runs/{run.id}/embedding")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_user_org_id, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["embedding_key"] == "X_tsne"
    assert payload["total_cells"] == 4
    assert payload["available_fields"] == ["cluster", "cellType"]
    assert payload["metadata"][0]["cluster"] == "0"
    assert payload["metadata"][0]["cellType"] == "T cell"
    assert payload["cluster_labels"] == {"0": "T cell", "1": "B cell"}
    assert len(payload["cells"]) == 4
