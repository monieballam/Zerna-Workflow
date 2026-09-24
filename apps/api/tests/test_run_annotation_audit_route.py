"""Route tests for the synchronous annotation-audit endpoint."""

from __future__ import annotations

from uuid import uuid4

import anndata as ad
import numpy as np
import pytest
from fastapi import status

from apps.api.main import app
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User
from apps.api.routes.runs import get_user_org_id
from methods.annotation.audit.resource_guard import AnnotationAuditResourceError


@pytest.mark.asyncio
async def test_run_annotation_audit_route_returns_json(
    async_client,
    test_user: User,
    test_organization,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    h5ad_path = tmp_path / "audit.h5ad"
    ad.AnnData(X=np.eye(2, dtype=np.float32)).write_h5ad(h5ad_path)

    async def override_get_current_user():
        return test_user

    async def override_get_user_org_id():
        return test_organization.id

    async def fake_get_primary_h5ad_local_path(self, *, run_id, org_id):
        del self, run_id, org_id
        return h5ad_path

    monkeypatch.setattr(
        "apps.api.routes.runs.RunExplorerService.get_primary_h5ad_local_path",
        fake_get_primary_h5ad_local_path,
    )
    monkeypatch.setattr(
        "apps.api.routes.runs.assert_h5ad_safe_for_sync_annotation_audit",
        lambda path: None,
    )
    monkeypatch.setattr(
        "apps.api.routes.runs.run_annotation_audit",
        lambda adata, cluster_key="leiden": {
            "summary": {"n_obs": int(adata.n_obs), "cluster_key": cluster_key}
        },
    )

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_user_org_id] = override_get_user_org_id
    try:
        response = await async_client.get(
            f"/v1/runs/{uuid4()}/annotation-audit",
            params={"cluster_key": "custom_cluster"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_user_org_id, None)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["summary"] == {"n_obs": 2, "cluster_key": "custom_cluster"}


@pytest.mark.asyncio
async def test_run_annotation_audit_route_rejects_large_artifact(
    async_client,
    test_user: User,
    test_organization,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    h5ad_path = tmp_path / "audit_large.h5ad"

    async def override_get_current_user():
        return test_user

    async def override_get_user_org_id():
        return test_organization.id

    async def fake_get_primary_h5ad_local_path(self, *, run_id, org_id):
        del self, run_id, org_id
        return h5ad_path

    monkeypatch.setattr(
        "apps.api.routes.runs.RunExplorerService.get_primary_h5ad_local_path",
        fake_get_primary_h5ad_local_path,
    )
    monkeypatch.setattr(
        "apps.api.routes.runs.assert_h5ad_safe_for_sync_annotation_audit",
        lambda path: (_ for _ in ()).throw(
            AnnotationAuditResourceError("too large for sync audit")
        ),
    )

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_user_org_id] = override_get_user_org_id
    try:
        response = await async_client.get(f"/v1/runs/{uuid4()}/annotation-audit")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_user_org_id, None)

    assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert "too large" in response.json()["detail"]
