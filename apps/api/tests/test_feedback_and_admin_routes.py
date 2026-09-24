"""Tests for feedback and admin routes."""

from uuid import uuid4

import pytest
from zerna_contracts.enums import RunStatus, UserRole
from sqlalchemy import insert

from apps.api.dependencies import get_auth_service
from apps.api.main import app
from apps.api.middleware.auth import get_current_user
from apps.api.models.dataset import Dataset, DatasetVersion
from apps.api.models.organization import Organization, User, organization_users
from apps.api.models.pipeline import PipelineTemplate, Run
from apps.api.services.auth_service import AuthService


async def _seed_org(async_session):
    org = Organization(
        id=uuid4(),
        name="Zerna",
        storage_quota_gb=1000,
        compute_quota_runs=10,
    )
    admin_user = User(
        id=uuid4(),
        email="admin@zerna.local",
        hashed_password="hash-admin",
    )
    member_user = User(
        id=uuid4(),
        email="member@example.com",
        hashed_password="hash-member",
    )
    dataset = Dataset(
        id=uuid4(),
        organization_id=org.id,
        name="PBMC reference",
        description="test dataset",
        extra_metadata={},
    )
    dataset_version = DatasetVersion(
        id=uuid4(),
        dataset_id=dataset.id,
        version="v1",
        s3_path="s3://datasets/pbmc/v1.h5ad",
        cell_count=1000,
        gene_count=2000,
        file_format="h5ad",
        extra_metadata={},
    )
    template = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name="scRNA-seq Standard",
        version="1.0.0",
        definition={"steps": []},
    )
    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=dataset_version.id,
        dataset_id_snapshot=dataset.id,
        dataset_version_id_snapshot=dataset_version.id,
        dataset_name_snapshot=dataset.name,
        dataset_version_label_snapshot=dataset_version.version,
        template_id=template.id,
        status=RunStatus.COMPLETED,
        parameters={"resolution": 0.6, "annotation_method": "celltypist"},
    )

    async_session.add_all([org, admin_user, member_user, dataset, dataset_version, template, run])
    await async_session.flush()
    await async_session.execute(
        insert(organization_users).values(
            organization_id=org.id,
            user_id=admin_user.id,
            role=UserRole.ADMIN,
        )
    )
    await async_session.execute(
        insert(organization_users).values(
            organization_id=org.id,
            user_id=member_user.id,
            role=UserRole.MEMBER,
        )
    )
    await async_session.commit()

    return {
        "org": org,
        "admin_user": admin_user,
        "member_user": member_user,
        "dataset": dataset,
        "dataset_version": dataset_version,
        "template": template,
        "run": run,
    }


def _override_auth_service(async_session, fake_redis):
    async def override_get_auth_service():
        return AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret_key_for_testing_only",
            jwt_algorithm="HS256",
        )

    return override_get_auth_service


@pytest.mark.asyncio
async def test_me_includes_active_role_and_org_membership(async_client, async_session, fake_redis):
    seeded = await _seed_org(async_session)

    async def override_get_current_user():
        return seeded["admin_user"]

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_auth_service] = _override_auth_service(async_session, fake_redis)
    try:
        response = await async_client.get("/v1/auth/me")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_auth_service, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "admin@zerna.local"
    assert payload["active_role"] == "admin"
    assert payload["active_organization_name"] == "Zerna"
    assert payload["organizations"][0]["organization_name"] == "Zerna"


@pytest.mark.asyncio
async def test_run_feedback_captures_run_snapshots_and_is_visible_to_admin(
    async_client, async_session, fake_redis
):
    seeded = await _seed_org(async_session)

    app.dependency_overrides[get_auth_service] = _override_auth_service(async_session, fake_redis)
    try:

        async def override_member_user():
            return seeded["member_user"]

        app.dependency_overrides[get_current_user] = override_member_user
        create_response = await async_client.post(
            "/v1/feedback",
            json={
                "scope": "run",
                "category": "science",
                "run_id": str(seeded["run"].id),
                "title": "Subtype labels need review",
                "message": "The automatic annotations look too coarse for the T-cell branch.",
            },
        )

        async def override_admin_user():
            return seeded["admin_user"]

        app.dependency_overrides[get_current_user] = override_admin_user
        list_response = await async_client.get("/v1/admin/feedback")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_auth_service, None)

    assert create_response.status_code == 201
    created_payload = create_response.json()
    assert created_payload["run_id"] == str(seeded["run"].id)
    assert created_payload["dataset_name_snapshot"] == "PBMC reference"
    assert created_payload["run_parameters_snapshot"]["resolution"] == 0.6

    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] == 1
    item = list_payload["items"][0]
    assert item["user_email"] == "member@example.com"
    assert item["run_id"] == str(seeded["run"].id)
    assert item["dataset_name_snapshot"] == "PBMC reference"
    assert item["run_parameters_snapshot"]["annotation_method"] == "celltypist"


@pytest.mark.asyncio
async def test_admin_can_create_and_promote_members(async_client, async_session, fake_redis):
    seeded = await _seed_org(async_session)

    async def override_admin_user():
        return seeded["admin_user"]

    app.dependency_overrides[get_current_user] = override_admin_user
    app.dependency_overrides[get_auth_service] = _override_auth_service(async_session, fake_redis)
    try:
        create_response = await async_client.post(
            "/v1/admin/members",
            json={
                "email": "new.admin@example.com",
                "password": "SuperSecure123!",
                "role": "admin",
            },
        )
        update_response = await async_client.patch(
            f"/v1/admin/members/{seeded['member_user'].id}",
            json={"role": "admin"},
        )
        list_response = await async_client.get("/v1/admin/members")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_auth_service, None)

    assert create_response.status_code == 201
    assert create_response.json()["role"] == "admin"

    assert update_response.status_code == 200
    assert update_response.json()["role"] == "admin"

    assert list_response.status_code == 200
    emails = {item["email"]: item["role"] for item in list_response.json()["items"]}
    assert emails["new.admin@example.com"] == "admin"
    assert emails["member@example.com"] == "admin"


@pytest.mark.asyncio
async def test_non_admin_cannot_access_admin_routes(async_client, async_session, fake_redis):
    seeded = await _seed_org(async_session)

    async def override_member_user():
        return seeded["member_user"]

    app.dependency_overrides[get_current_user] = override_member_user
    app.dependency_overrides[get_auth_service] = _override_auth_service(async_session, fake_redis)
    try:
        response = await async_client.get("/v1/admin/members")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_auth_service, None)

    assert response.status_code == 403
