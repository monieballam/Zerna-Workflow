"""Tests for run results and artifact preview routes."""

import shutil
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import anndata as ad
import numpy as np
import pandas as pd
import pytest
from zerna_contracts.enums import ArtifactType, RunStatus, UserRole
from botocore.exceptions import ClientError, EndpointConnectionError
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.main import app
from apps.api.middleware.auth import get_current_user
from apps.api.models.dataset import Dataset, DatasetVersion
from apps.api.models.organization import organization_users
from apps.api.models.pipeline import Artifact, PipelineTemplate, Run
from apps.api.routes.runs import get_user_org_id


@pytest.mark.asyncio
class TestResultsRoutes:
    async def test_results_route_uses_h5ad_metrics_when_multiple_artifacts_exist(
        self,
        async_client,
        async_session: AsyncSession,
        test_user,
        test_organization,
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
            definition={"methods": ["qc_filter"], "dependencies": {}},
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

        async_session.add_all(
            [
                Artifact(
                    id=uuid4(),
                    run_id=run.id,
                    artifact_type=ArtifactType.DE_RESULTS,
                    s3_path="runs/test/de_results.csv",
                    size_bytes=123,
                    extra_metadata={"n_rows": 50},
                ),
                Artifact(
                    id=uuid4(),
                    run_id=run.id,
                    artifact_type=ArtifactType.H5AD,
                    s3_path="runs/test/processed.h5ad",
                    size_bytes=456,
                    extra_metadata={
                        "step_metrics": {"qc_filter": {"n_cells_after": 10}},
                        "software_versions": {"scanpy": "1.11.5"},
                    },
                ),
                Artifact(
                    id=uuid4(),
                    run_id=run.id,
                    artifact_type=ArtifactType.LIANA_RESULTS,
                    s3_path="runs/test/liana.csv",
                    size_bytes=789,
                    extra_metadata={"n_rows": 100},
                ),
            ]
        )
        await async_session.commit()

        async def override_get_current_user():
            return test_user

        async def override_get_user_org_id():
            return test_organization.id

        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_user_org_id] = override_get_user_org_id
        try:
            response = await async_client.get(f"/v1/runs/{run.id}/results")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_user_org_id, None)

        assert response.status_code == 200
        payload = response.json()
        assert payload["artifact_size_bytes"] == 456
        assert payload["step_metrics"]["qc_filter"]["n_cells_after"] == 10
        assert payload["software_versions"]["scanpy"] == "1.11.5"

    async def test_results_route_backfills_cluster_labels_from_h5ad(
        self,
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
            definition={"methods": ["cluster", "annotate"], "dependencies": {}},
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
        artifact = Artifact(
            id=uuid4(),
            run_id=run.id,
            artifact_type=ArtifactType.H5AD,
            s3_path="runs/test/processed.h5ad",
            size_bytes=456,
            extra_metadata={
                "step_metrics": {
                    "cluster": {"n_clusters": 2, "cluster_sizes": [2, 2]},
                    "annotate": {"n_cells_annotated": 4},
                }
            },
        )

        async_session.add_all([dataset, template, dataset_version, run, artifact])
        await async_session.execute(
            insert(organization_users).values(
                organization_id=test_organization.id,
                user_id=test_user.id,
                role=UserRole.ADMIN,
            )
        )
        await async_session.commit()

        source_h5ad = tmp_path / "processed.h5ad"
        adata = ad.AnnData(np.ones((4, 3)))
        adata.obs["leiden"] = pd.Categorical(["0", "0", "1", "1"])
        adata.obs["annotation_cell_type"] = ["T cell", "T cell", "B cell", "B cell"]
        adata.uns["zerna_cluster_annotations"] = {
            "0": {"normalized_label": "T cell"},
            "1": {"normalized_label": "B cell"},
        }
        adata.write_h5ad(source_h5ad)

        class DummyS3Client:
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
                response = await async_client.get(f"/v1/runs/{run.id}/results")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_user_org_id, None)

        assert response.status_code == 200
        payload = response.json()
        assert payload["step_metrics"]["cluster"]["cluster_key"] == "leiden"
        assert payload["step_metrics"]["cluster"]["clusters"] == [
            {"cluster_id": "0", "label": "T cell", "n_cells": 2},
            {"cluster_id": "1", "label": "B cell", "n_cells": 2},
        ]

    async def test_preview_route_returns_csv_rows(
        self,
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
            definition={"methods": ["differential_expression"], "dependencies": {}},
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
        artifact = Artifact(
            id=uuid4(),
            run_id=run.id,
            artifact_type=ArtifactType.DE_RESULTS,
            s3_path="runs/test/de_results.csv",
            size_bytes=123,
            extra_metadata={"n_rows": 2},
        )

        async_session.add_all([dataset, template, dataset_version, run, artifact])
        await async_session.execute(
            insert(organization_users).values(
                organization_id=test_organization.id,
                user_id=test_user.id,
                role=UserRole.ADMIN,
            )
        )
        await async_session.commit()

        source_csv = tmp_path / "de_results.csv"
        source_csv.write_text(
            "cluster,gene,log_fold_change,p_value,adjusted_p_value\n"
            "0,Cxcl9,1.25,0.001,0.005\n"
            "1,Ifit1,0.84,0.02,0.04\n",
            encoding="utf-8",
        )

        class DummyS3Client:
            def download_file(self, bucket: str, key: str, destination: str) -> None:
                del bucket, key
                shutil.copyfile(source_csv, destination)

        async def override_get_current_user():
            return test_user

        async def override_get_user_org_id():
            return test_organization.id

        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_user_org_id] = override_get_user_org_id
        try:
            with patch("boto3.client", return_value=DummyS3Client()):
                response = await async_client.get(
                    f"/v1/runs/{run.id}/artifacts/{artifact.id}/preview?limit=1"
                )
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_user_org_id, None)

        assert response.status_code == 200
        payload = response.json()
        assert payload["artifact_type"] == "de_results"
        assert payload["columns"] == [
            "cluster",
            "gene",
            "log_fold_change",
            "p_value",
            "adjusted_p_value",
        ]
        assert len(payload["rows"]) == 1
        assert payload["rows"][0]["gene"] == "Cxcl9"
        assert payload["total_rows"] == 2
        assert payload["truncated"] is True

    async def test_preview_route_returns_structured_error_on_storage_unreachable(
        self,
        async_client,
        async_session: AsyncSession,
        test_user,
        test_organization,
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
            definition={"methods": ["differential_expression"], "dependencies": {}},
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
        artifact = Artifact(
            id=uuid4(),
            run_id=run.id,
            artifact_type=ArtifactType.DE_RESULTS,
            s3_path="runs/test/de_results.csv",
            size_bytes=123,
            extra_metadata={"n_rows": 2},
        )

        async_session.add_all([dataset, template, dataset_version, run, artifact])
        await async_session.execute(
            insert(organization_users).values(
                organization_id=test_organization.id,
                user_id=test_user.id,
                role=UserRole.ADMIN,
            )
        )
        await async_session.commit()

        class FailingS3Client:
            def download_file(self, bucket: str, key: str, destination: str) -> None:
                del bucket, key, destination
                raise EndpointConnectionError(endpoint_url="http://minio:9000")

        async def override_get_current_user():
            return test_user

        async def override_get_user_org_id():
            return test_organization.id

        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_user_org_id] = override_get_user_org_id
        try:
            with patch("boto3.client", return_value=FailingS3Client()):
                response = await async_client.get(
                    f"/v1/runs/{run.id}/artifacts/{artifact.id}/preview?limit=5"
                )
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_user_org_id, None)

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["code"] == "storage_unreachable"
        assert "endpoint" in detail

    async def test_preview_route_returns_structured_error_on_missing_object(
        self,
        async_client,
        async_session: AsyncSession,
        test_user,
        test_organization,
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
            definition={"methods": ["differential_expression"], "dependencies": {}},
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
        artifact = Artifact(
            id=uuid4(),
            run_id=run.id,
            artifact_type=ArtifactType.DE_RESULTS,
            s3_path="runs/test/de_results.csv",
            size_bytes=123,
            extra_metadata={"n_rows": 2},
        )

        async_session.add_all([dataset, template, dataset_version, run, artifact])
        await async_session.execute(
            insert(organization_users).values(
                organization_id=test_organization.id,
                user_id=test_user.id,
                role=UserRole.ADMIN,
            )
        )
        await async_session.commit()

        class MissingKeyS3Client:
            def download_file(self, bucket: str, key: str, destination: str) -> None:
                del bucket, key, destination
                raise ClientError(
                    {"Error": {"Code": "NoSuchKey", "Message": "not found"}},
                    "GetObject",
                )

        async def override_get_current_user():
            return test_user

        async def override_get_user_org_id():
            return test_organization.id

        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_user_org_id] = override_get_user_org_id
        try:
            with patch("boto3.client", return_value=MissingKeyS3Client()):
                response = await async_client.get(
                    f"/v1/runs/{run.id}/artifacts/{artifact.id}/preview?limit=5"
                )
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_user_org_id, None)

        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["code"] == "artifact_missing"
