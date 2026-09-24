"""Seeded template presentation metadata and picker visibility."""

from copy import deepcopy
from datetime import datetime
from uuid import uuid4

import pytest
from zerna_contracts.enums import UserRole
from sqlalchemy import insert

from apps.api.main import app
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import Organization, organization_users
from apps.api.models.pipeline import PipelineTemplate
from apps.api.routes.pipelines import _pipeline_template_response
from apps.api.services.pipeline_catalog import (
    get_seed_template_specs,
    merge_template_presentation_metadata,
)


def test_seed_standard_metadata_flags():
    specs = get_seed_template_specs()
    std = next(s for s in specs if s["name"] == "scRNA-seq Standard")
    meta = std["definition"]["metadata"]
    assert meta["recommended"] is True
    assert meta["deprecated"] is False
    assert meta["visible_in_picker"] is True
    assert meta["template_family"] == "standard"
    assert "concat diagnostics" in meta["description"].lower()
    assert "doublet" in meta["description"].lower()
    assert "ambient" in meta["description"].lower()
    assert "advanced" in meta["description"].lower()


def test_seed_standard_ambient_step_is_gated_and_off_by_default():
    specs = get_seed_template_specs()
    std = next(s for s in specs if s["name"] == "scRNA-seq Standard")
    ambient = next(
        m
        for m in std["definition"]["methods"]
        if isinstance(m, dict) and m.get("name") == "ambient_correction"
    )
    assert ambient.get("enabled_if") == "ambient_correction"
    props = std["definition"]["parameter_schema"]["properties"]
    assert props["ambient_correction"]["default"] is False


def test_seed_legacy_metadata_flags():
    specs = get_seed_template_specs()
    leg = next(s for s in specs if s["name"] == "scRNA-seq Legacy Parity")
    meta = leg["definition"]["metadata"]
    assert meta["recommended"] is False
    assert meta["deprecated"] is True
    assert meta["visible_in_picker"] is False
    assert "deprecated" in meta["description"].lower()


def test_merge_template_presentation_metadata_infers_legacy_by_family():
    definition = {
        "methods": ["qc_filter"],
        "dependencies": {},
        "metadata": {"template_family": "legacy_parity"},
    }
    out = merge_template_presentation_metadata(definition, name="Custom", version="9.9.9")
    m = out["metadata"]
    assert m["deprecated"] is True
    assert m["visible_in_picker"] is False


def test_merge_template_presentation_metadata_does_not_override_explicit():
    definition = {
        "methods": ["qc_filter"],
        "dependencies": {},
        "metadata": {
            "template_family": "legacy_parity",
            "visible_in_picker": True,
        },
    }
    out = merge_template_presentation_metadata(definition, name="x", version="1")
    assert out["metadata"]["visible_in_picker"] is True


def test_pipeline_template_response_includes_presentation_fields():
    now = datetime.utcnow()
    template = PipelineTemplate(
        id=uuid4(),
        organization_id=uuid4(),
        name="scRNA-seq Standard",
        version="1.7.0",
        definition=deepcopy(
            next(s for s in get_seed_template_specs() if s["name"] == "scRNA-seq Standard")[
                "definition"
            ]
        ),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    resp = _pipeline_template_response(template)
    assert resp.recommended is True
    assert resp.deprecated is False
    assert resp.visible_in_picker is True
    assert resp.template_family == "standard"


@pytest.mark.asyncio
async def test_list_pipelines_hides_legacy_by_default(
    async_client,
    async_session,
    test_user,
    test_organization: Organization,
):
    await async_session.execute(
        insert(organization_users).values(
            organization_id=test_organization.id,
            user_id=test_user.id,
            role=UserRole.ADMIN,
        )
    )
    await async_session.commit()

    async def override_get_current_user():
        return test_user

    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        sync_res = await async_client.post("/v1/pipelines/catalog/sync-defaults")
        assert sync_res.status_code == 200
        synced = sync_res.json()
        assert any(t["name"] == "scRNA-seq Standard" for t in synced)
        legacy = next(t for t in synced if t["name"] == "scRNA-seq Legacy Parity")
        assert legacy["deprecated"] is True
        assert legacy["visible_in_picker"] is False

        list_res = await async_client.get("/v1/pipelines", params={"is_active": True})
        assert list_res.status_code == 200
        visible = list_res.json()
        names = {t["name"] for t in visible}
        assert "scRNA-seq Standard" in names
        assert "scRNA-seq Legacy Parity" not in names

        all_res = await async_client.get(
            "/v1/pipelines",
            params={"is_active": True, "include_hidden_in_picker": True},
        )
        assert all_res.status_code == 200
        all_names = {t["name"] for t in all_res.json()}
        assert "scRNA-seq Legacy Parity" in all_names

        leg_id = legacy["id"]
        one = await async_client.get(f"/v1/pipelines/{leg_id}")
        assert one.status_code == 200
        body = one.json()
        assert body["name"] == "scRNA-seq Legacy Parity"
        assert body["deprecated"] is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)
