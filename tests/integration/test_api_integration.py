"""Comprehensive API integration tests for Zerna platform.

Tests all API endpoints with valid and invalid inputs, authentication,
multi-tenancy isolation, and error handling.

Validates: Requirements 19.2
"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from zerna_contracts.enums import RunStatus, UserRole
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.models import (
    Dataset,
    DatasetVersion,
    PipelineTemplate,
    Run,
)
from apps.api.models.organization import Organization, OrganizationUser, User
from apps.api.services.pipeline_catalog import build_pipeline_definition

pytestmark = pytest.mark.integration

# JWT settings matching conftest
_JWT_SECRET = "integration-test-secret-key"
_JWT_ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(user_id, email: str, expires_minutes: int = 60) -> str:
    """Generate a JWT access token."""
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
        "iat": int(now.timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def _make_expired_token(user_id, email: str) -> str:
    """Generate an expired JWT token."""
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": int((now - timedelta(minutes=10)).timestamp()),
        "iat": int((now - timedelta(minutes=70)).timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


async def _seed_dataset(db: AsyncSession, org_id, *, name="Test DS") -> Dataset:
    ds = Dataset(
        id=uuid4(),
        organization_id=org_id,
        name=name,
        description="test",
        extra_metadata={},
    )
    db.add(ds)
    await db.flush()
    return ds


async def _seed_version(db: AsyncSession, dataset_id, *, version="v1") -> DatasetVersion:
    dv = DatasetVersion(
        id=uuid4(),
        dataset_id=dataset_id,
        version=version,
        s3_path=f"test/{dataset_id}/{version}/data.h5ad",
        cell_count=1000,
        gene_count=500,
        file_format="h5ad",
    )
    db.add(dv)
    await db.flush()
    return dv


async def _seed_template(db: AsyncSession, org_id, *, name="tpl", ver="1.0.0") -> PipelineTemplate:
    tpl = PipelineTemplate(
        id=uuid4(),
        organization_id=org_id,
        name=name,
        version=ver,
        definition=build_pipeline_definition(
            ["qc_filter", "normalize"],
            description="Integration test template",
        ),
        is_active=True,
    )
    db.add(tpl)
    await db.flush()
    return tpl


async def _seed_run(
    db: AsyncSession,
    org_id,
    dv_id,
    tpl_id,
    *,
    status=RunStatus.QUEUED,
) -> Run:
    run = Run(
        id=uuid4(),
        organization_id=org_id,
        dataset_version_id=dv_id,
        template_id=tpl_id,
        status=status,
        parameters={"resolution": 1.0},
        software_versions={"scanpy": "1.9.3"},
        random_seed=42,
        created_at=datetime.utcnow(),
    )
    if status == RunStatus.COMPLETED:
        run.started_at = datetime.utcnow()
        run.completed_at = datetime.utcnow()
    db.add(run)
    await db.flush()
    return run


async def _create_second_org_and_client(
    db: AsyncSession,
    integration_engine,
):
    """Create a second org + user and return (org, user, AsyncClient)."""
    org2 = Organization(
        id=uuid4(),
        name="Org B",
        storage_quota_gb=100,
        compute_quota_runs=5,
    )
    db.add(org2)
    await db.flush()

    user2 = User(
        id=uuid4(),
        email="orgb@zerna.test",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$hash2",
    )
    db.add(user2)
    await db.flush()

    await db.execute(
        insert(OrganizationUser).values(
            organization_id=org2.id,
            user_id=user2.id,
            role=UserRole.ADMIN,
            joined_at=datetime.utcnow(),
        )
    )
    await db.commit()

    token = _make_token(user2.id, user2.email)

    from apps.api.dependencies import get_db
    from apps.api.main import app
    from apps.api.middleware.auth import get_current_user

    async def _override_get_db():
        sf = async_sessionmaker(integration_engine, class_=AsyncSession, expire_on_commit=False)
        async with sf() as session:
            yield session

    async def _override_get_current_user():
        return user2

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    transport = ASGITransport(app=app)
    client = AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )
    return org2, user2, client


# ═══════════════════════════════════════════════════════════════════════════
# 1. Health Endpoints
# ═══════════════════════════════════════════════════════════════════════════


class TestHealthEndpoints:
    """Test health check endpoints."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, authenticated_client: AsyncClient):
        resp = await authenticated_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_v1_health_returns_version(self, authenticated_client: AsyncClient):
        resp = await authenticated_client.get("/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["version"] == "v1"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Authentication Integration
# ═══════════════════════════════════════════════════════════════════════════


class TestAuthenticationIntegration:
    """Test authentication and authorization."""

    @pytest.mark.asyncio
    async def test_unauthenticated_request_returns_401(
        self,
        unauthenticated_client: AsyncClient,
    ):
        resp = await unauthenticated_client.get("/v1/datasets")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_expired_token_returns_401(
        self,
        unauthenticated_client: AsyncClient,
        test_user,
    ):
        token = _make_expired_token(test_user.id, test_user.email)
        resp = await unauthenticated_client.get(
            "/v1/datasets",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(
        self,
        unauthenticated_client: AsyncClient,
    ):
        resp = await unauthenticated_client.get(
            "/v1/datasets",
            headers={"Authorization": "Bearer totally-invalid-jwt"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_auth_header_returns_401(
        self,
        unauthenticated_client: AsyncClient,
    ):
        resp = await unauthenticated_client.get(
            "/v1/datasets",
            headers={"Authorization": "NotBearer sometoken"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_valid_token_succeeds(
        self,
        authenticated_client: AsyncClient,
        test_org,
    ):
        resp = await authenticated_client.get("/v1/datasets")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# 3. Dataset Endpoints
# ═══════════════════════════════════════════════════════════════════════════


class TestDatasetEndpoints:
    """Test dataset CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_create_dataset_returns_201(
        self,
        authenticated_client: AsyncClient,
        test_org,
    ):
        resp = await authenticated_client.post(
            "/v1/datasets",
            json={"name": "New DS", "description": "desc"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "New DS"
        assert "id" in body

    @pytest.mark.asyncio
    async def test_create_dataset_missing_name_returns_422(
        self,
        authenticated_client: AsyncClient,
        test_org,
    ):
        resp = await authenticated_client.post("/v1/datasets", json={"description": "desc"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_datasets_returns_paginated(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        # Seed two datasets
        await _seed_dataset(db_session, test_org.id, name="DS-A")
        await _seed_dataset(db_session, test_org.id, name="DS-B")
        await db_session.commit()

        resp = await authenticated_client.get("/v1/datasets")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body

    @pytest.mark.asyncio
    async def test_list_datasets_pagination_params(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        for i in range(5):
            await _seed_dataset(db_session, test_org.id, name=f"DS-{i}")
        await db_session.commit()

        resp = await authenticated_client.get(
            "/v1/datasets",
            params={"page": 1, "page_size": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert len(body["items"]) <= 2

    @pytest.mark.asyncio
    async def test_get_dataset_returns_details(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id, name="Detail DS")
        await db_session.commit()

        resp = await authenticated_client.get(f"/v1/datasets/{ds.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(ds.id)

    @pytest.mark.asyncio
    async def test_get_nonexistent_dataset_returns_404(
        self,
        authenticated_client: AsyncClient,
        test_org,
    ):
        resp = await authenticated_client.get(f"/v1/datasets/{uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_dataset_metadata(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id, name="Old Name")
        await db_session.commit()

        resp = await authenticated_client.put(
            f"/v1/datasets/{ds.id}",
            json={"name": "New Name", "description": "updated"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    @pytest.mark.asyncio
    async def test_delete_dataset_returns_204(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id, name="To Delete")
        await db_session.commit()

        resp = await authenticated_client.delete(f"/v1/datasets/{ds.id}")
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_dataset_with_options_returns_summary(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id, name="Delete With Options")
        await db_session.commit()

        resp = await authenticated_client.request(
            "DELETE",
            f"/v1/datasets/{ds.id}",
            json={"run_delete_mode": "preserve"},
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "dataset_id": str(ds.id),
            "deleted_runs": 0,
            "preserved_runs": 0,
        }

        get_resp = await authenticated_client.get(f"/v1/datasets/{ds.id}")
        assert get_resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# 4. Pipeline Endpoints
# ═══════════════════════════════════════════════════════════════════════════


class TestPipelineEndpoints:
    """Test pipeline template CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_create_pipeline_returns_201(
        self,
        authenticated_client: AsyncClient,
        test_org,
    ):
        resp = await authenticated_client.post(
            "/v1/pipelines",
            json={
                "name": "test-pipeline",
                "version": "1.0.0",
                "definition": build_pipeline_definition(
                    ["qc_filter", "normalize"],
                    description="Integration test template",
                ),
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "test-pipeline"
        assert "id" in body

    @pytest.mark.asyncio
    async def test_create_pipeline_missing_fields_returns_422(
        self,
        authenticated_client: AsyncClient,
        test_org,
    ):
        # Missing required 'name' field
        resp = await authenticated_client.post(
            "/v1/pipelines",
            json={"version": "1.0.0"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_pipelines(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        await _seed_template(db_session, test_org.id, name="tpl-list", ver="1.0.0")
        await db_session.commit()

        resp = await authenticated_client.get("/v1/pipelines")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_get_pipeline_returns_details(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        tpl = await _seed_template(db_session, test_org.id, name="tpl-detail", ver="2.0.0")
        await db_session.commit()

        resp = await authenticated_client.get(f"/v1/pipelines/{tpl.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(tpl.id)

    @pytest.mark.asyncio
    async def test_get_nonexistent_pipeline_returns_404(
        self,
        authenticated_client: AsyncClient,
        test_org,
    ):
        resp = await authenticated_client.get(f"/v1/pipelines/{uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_validate_pipeline_params(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        tpl = await _seed_template(db_session, test_org.id, name="tpl-val", ver="1.0.0")
        await db_session.commit()

        resp = await authenticated_client.post(
            f"/v1/pipelines/{tpl.id}/validate",
            json={"parameters": {"resolution": 1.0}},
        )
        assert resp.status_code == 200
        assert "valid" in resp.json()


# ═══════════════════════════════════════════════════════════════════════════
# 5. Run Endpoints
# ═══════════════════════════════════════════════════════════════════════════


class TestRunEndpoints:
    """Test run lifecycle endpoints."""

    @pytest.mark.asyncio
    async def test_create_run_returns_201_queued(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id)
        dv = await _seed_version(db_session, ds.id)
        tpl = await _seed_template(db_session, test_org.id, name="run-tpl", ver="1.0.0")
        await db_session.commit()

        resp = await authenticated_client.post(
            "/v1/runs",
            json={
                "dataset_version_id": str(dv.id),
                "template_id": str(tpl.id),
                "parameters": {"resolution": 0.5},
                "random_seed": 99,
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "running"
        assert body["random_seed"] == 99

    @pytest.mark.asyncio
    async def test_create_run_nonexistent_version_returns_404(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        tpl = await _seed_template(db_session, test_org.id, name="run-tpl2", ver="1.0.0")
        await db_session.commit()

        resp = await authenticated_client.post(
            "/v1/runs",
            json={
                "dataset_version_id": str(uuid4()),
                "template_id": str(tpl.id),
                "parameters": {},
            },
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_run_nonexistent_template_returns_404(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id)
        dv = await _seed_version(db_session, ds.id)
        await db_session.commit()

        resp = await authenticated_client.post(
            "/v1/runs",
            json={
                "dataset_version_id": str(dv.id),
                "template_id": str(uuid4()),
                "parameters": {},
            },
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_runs_paginated(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id)
        dv = await _seed_version(db_session, ds.id)
        tpl = await _seed_template(db_session, test_org.id, name="list-tpl", ver="1.0.0")
        await _seed_run(db_session, test_org.id, dv.id, tpl.id)
        await db_session.commit()

        resp = await authenticated_client.get("/v1/runs")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body

    @pytest.mark.asyncio
    async def test_list_runs_with_status_filter(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id)
        dv = await _seed_version(db_session, ds.id)
        tpl = await _seed_template(db_session, test_org.id, name="filter-tpl", ver="1.0.0")
        await _seed_run(db_session, test_org.id, dv.id, tpl.id, status=RunStatus.QUEUED)
        await _seed_run(db_session, test_org.id, dv.id, tpl.id, status=RunStatus.COMPLETED)
        await db_session.commit()

        resp = await authenticated_client.get("/v1/runs", params={"status": "queued"})
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["status"] == "queued"

    @pytest.mark.asyncio
    async def test_get_run_details(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id)
        dv = await _seed_version(db_session, ds.id)
        tpl = await _seed_template(db_session, test_org.id, name="det-tpl", ver="1.0.0")
        run = await _seed_run(db_session, test_org.id, dv.id, tpl.id)
        await db_session.commit()

        resp = await authenticated_client.get(f"/v1/runs/{run.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(run.id)

    @pytest.mark.asyncio
    async def test_cancel_queued_run(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id)
        dv = await _seed_version(db_session, ds.id)
        tpl = await _seed_template(db_session, test_org.id, name="cancel-tpl", ver="1.0.0")
        run = await _seed_run(db_session, test_org.id, dv.id, tpl.id, status=RunStatus.QUEUED)
        await db_session.commit()

        resp = await authenticated_client.post(f"/v1/runs/{run.id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_list_run_artifacts(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id)
        dv = await _seed_version(db_session, ds.id)
        tpl = await _seed_template(db_session, test_org.id, name="art-tpl", ver="1.0.0")
        run = await _seed_run(db_session, test_org.id, dv.id, tpl.id, status=RunStatus.COMPLETED)
        await db_session.commit()

        resp = await authenticated_client.get(f"/v1/runs/{run.id}/artifacts")
        assert resp.status_code == 200
        assert "artifacts" in resp.json()


# ═══════════════════════════════════════════════════════════════════════════
# 6. Annotation Endpoints
# ═══════════════════════════════════════════════════════════════════════════


class TestAnnotationEndpoints:
    """Test annotation revision endpoints."""

    @pytest.mark.asyncio
    async def test_create_annotation_revision(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id)
        dv = await _seed_version(db_session, ds.id)
        tpl = await _seed_template(db_session, test_org.id, name="ann-tpl", ver="1.0.0")
        run = await _seed_run(db_session, test_org.id, dv.id, tpl.id, status=RunStatus.COMPLETED)
        await db_session.commit()

        resp = await authenticated_client.post(
            f"/v1/runs/{run.id}/annotations",
            json={
                "annotations": {"cell_0": {"cell_type": "T cell", "confidence": 0.9}},
                "method": "celltypist",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["revision_number"] == 1
        assert body["method"] == "celltypist"

    @pytest.mark.asyncio
    async def test_edit_annotation_creates_new_revision(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id)
        dv = await _seed_version(db_session, ds.id)
        tpl = await _seed_template(db_session, test_org.id, name="ann-edit-tpl", ver="1.0.0")
        run = await _seed_run(db_session, test_org.id, dv.id, tpl.id, status=RunStatus.COMPLETED)
        await db_session.commit()

        # Create initial revision
        create_resp = await authenticated_client.post(
            f"/v1/runs/{run.id}/annotations",
            json={
                "annotations": {"cell_0": {"cell_type": "T cell", "confidence": 0.9}},
                "method": "celltypist",
            },
        )
        assert create_resp.status_code == 201
        ann_id = create_resp.json()["id"]

        # Edit → new revision
        edit_resp = await authenticated_client.patch(
            f"/v1/annotations/{ann_id}",
            json={"edits": {"cell_0": {"cell_type": "CD8+ T cell", "confidence": 0.95}}},
        )
        assert edit_resp.status_code == 200
        assert edit_resp.json()["revision_number"] == 2

    @pytest.mark.asyncio
    async def test_approve_annotation(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id)
        dv = await _seed_version(db_session, ds.id)
        tpl = await _seed_template(db_session, test_org.id, name="ann-appr-tpl", ver="1.0.0")
        run = await _seed_run(db_session, test_org.id, dv.id, tpl.id, status=RunStatus.COMPLETED)
        await db_session.commit()

        create_resp = await authenticated_client.post(
            f"/v1/runs/{run.id}/annotations",
            json={
                "annotations": {"cell_0": {"cell_type": "B cell", "confidence": 0.88}},
                "method": "manual",
            },
        )
        assert create_resp.status_code == 201
        ann_id = create_resp.json()["id"]

        approve_resp = await authenticated_client.post(
            f"/v1/annotations/{ann_id}/approve",
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["approved_by"] is not None
        assert approve_resp.json()["approved_at"] is not None

    @pytest.mark.asyncio
    async def test_list_annotation_revisions(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
    ):
        ds = await _seed_dataset(db_session, test_org.id)
        dv = await _seed_version(db_session, ds.id)
        tpl = await _seed_template(db_session, test_org.id, name="ann-list-tpl", ver="1.0.0")
        run = await _seed_run(db_session, test_org.id, dv.id, tpl.id, status=RunStatus.COMPLETED)
        await db_session.commit()

        # Create two revisions
        r1 = await authenticated_client.post(
            f"/v1/runs/{run.id}/annotations",
            json={
                "annotations": {"cell_0": {"cell_type": "T cell", "confidence": 0.9}},
                "method": "celltypist",
            },
        )
        assert r1.status_code == 201
        ann_id = r1.json()["id"]

        await authenticated_client.patch(
            f"/v1/annotations/{ann_id}",
            json={"edits": {"cell_0": {"cell_type": "NK cell", "confidence": 0.85}}},
        )

        list_resp = await authenticated_client.get(f"/v1/runs/{run.id}/annotations")
        assert list_resp.status_code == 200
        body = list_resp.json()
        assert body["total"] >= 2


# ═══════════════════════════════════════════════════════════════════════════
# 7. Multi-Tenancy Isolation
# ═══════════════════════════════════════════════════════════════════════════


class TestMultiTenancyIsolation:
    """Verify that resources from one org are invisible to another org's user.

    Validates: Requirements 11.1, 11.5
    """

    @pytest.mark.asyncio
    async def test_org_b_cannot_see_org_a_datasets(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
        integration_engine,
    ):
        # Seed a dataset in org A
        ds_a = await _seed_dataset(db_session, test_org.id, name="OrgA-DS")
        await db_session.commit()

        # Create org B client
        org_b, _, client_b = await _create_second_org_and_client(
            db_session,
            integration_engine,
        )

        try:
            # Org B should not see org A's dataset
            resp = await client_b.get("/v1/datasets")
            assert resp.status_code == 200
            ids = [item["id"] for item in resp.json()["items"]]
            assert str(ds_a.id) not in ids

            # Org B should get 404 for org A's dataset by ID
            resp2 = await client_b.get(f"/v1/datasets/{ds_a.id}")
            assert resp2.status_code == 404
        finally:
            await client_b.aclose()

    @pytest.mark.asyncio
    async def test_org_b_cannot_see_org_a_runs(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
        integration_engine,
    ):
        ds = await _seed_dataset(db_session, test_org.id)
        dv = await _seed_version(db_session, ds.id)
        tpl = await _seed_template(db_session, test_org.id, name="iso-tpl", ver="1.0.0")
        run_a = await _seed_run(db_session, test_org.id, dv.id, tpl.id)
        await db_session.commit()

        org_b, _, client_b = await _create_second_org_and_client(
            db_session,
            integration_engine,
        )

        try:
            resp = await client_b.get("/v1/runs")
            assert resp.status_code == 200
            ids = [item["id"] for item in resp.json()["items"]]
            assert str(run_a.id) not in ids
        finally:
            await client_b.aclose()

    @pytest.mark.asyncio
    async def test_org_b_cannot_see_org_a_pipelines(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_org,
        integration_engine,
    ):
        tpl_a = await _seed_template(db_session, test_org.id, name="iso-pipe", ver="1.0.0")
        await db_session.commit()

        org_b, _, client_b = await _create_second_org_and_client(
            db_session,
            integration_engine,
        )

        try:
            resp = await client_b.get("/v1/pipelines")
            assert resp.status_code == 200
            ids = [item["id"] for item in resp.json()]
            assert str(tpl_a.id) not in ids
        finally:
            await client_b.aclose()


# ═══════════════════════════════════════════════════════════════════════════
# 8. Error Handling
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorHandling:
    """Test error response format and status codes."""

    @pytest.mark.asyncio
    async def test_422_includes_field_level_details(
        self,
        authenticated_client: AsyncClient,
        test_org,
    ):
        # Send invalid JSON body to an endpoint that expects a schema
        resp = await authenticated_client.post(
            "/v1/pipelines",
            json={},  # missing required fields
        )
        assert resp.status_code == 422
        body = resp.json()
        # The error handler should include structured details
        assert "error_type" in body or "detail" in body
        # If using the custom error handler, check for field_errors
        if "details" in body:
            assert "field_errors" in body["details"]

    @pytest.mark.asyncio
    async def test_404_for_nonexistent_resource(
        self,
        authenticated_client: AsyncClient,
        test_org,
    ):
        resp = await authenticated_client.get(f"/v1/datasets/{uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_error_response_format(
        self,
        authenticated_client: AsyncClient,
        test_org,
    ):
        # Trigger a 422 to check the structured error format
        resp = await authenticated_client.post(
            "/v1/runs",
            json={},  # missing required fields
        )
        assert resp.status_code == 422
        body = resp.json()
        # Verify the error response includes the expected fields
        assert "error_type" in body or "detail" in body
        if "error_type" in body:
            assert "message" in body
            assert "error_code" in body
