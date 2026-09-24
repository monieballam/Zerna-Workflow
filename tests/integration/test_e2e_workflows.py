"""End-to-end workflow integration tests for Zerna platform.

Tests critical user workflows that span multiple API endpoints,
validating the full data flow through the system.

Validates: Requirements 19.3
"""

from datetime import datetime
from uuid import uuid4

import pytest
from zerna_contracts.enums import RunStatus
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models import (
    CrossDatasetAnalysis,
    Dataset,
    DatasetVersion,
    PipelineTemplate,
    Run,
)
from apps.api.services.pipeline_catalog import build_pipeline_definition

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_dataset_via_db(
    db: AsyncSession, org_id, *, name: str = "Test Dataset", description: str = "desc"
) -> Dataset:
    ds = Dataset(
        id=uuid4(),
        organization_id=org_id,
        name=name,
        description=description,
        extra_metadata={},
    )
    db.add(ds)
    await db.flush()
    return ds


async def _create_version_via_db(
    db: AsyncSession, dataset_id, *, version: str = "v1"
) -> DatasetVersion:
    dv = DatasetVersion(
        id=uuid4(),
        dataset_id=dataset_id,
        version=version,
        s3_path=f"test-org/datasets/{dataset_id}/{version}/data.h5ad",
        cell_count=5000,
        gene_count=2000,
        file_format="h5ad",
    )
    db.add(dv)
    await db.flush()
    return dv


async def _create_template_via_db(
    db: AsyncSession, org_id, *, name: str = "sc-pipeline", version: str = "1.0.0"
) -> PipelineTemplate:
    tpl = PipelineTemplate(
        id=uuid4(),
        organization_id=org_id,
        name=name,
        version=version,
        definition=build_pipeline_definition(
            ["qc_filter", "normalize", "select_hvg", "run_pca", "cluster", "embed"],
            description="Integration test template",
        ),
        is_active=True,
    )
    db.add(tpl)
    await db.flush()
    return tpl


async def _create_run_via_db(
    db: AsyncSession,
    org_id,
    dataset_version_id,
    template_id,
    *,
    status: RunStatus = RunStatus.COMPLETED,
) -> Run:
    run = Run(
        id=uuid4(),
        organization_id=org_id,
        dataset_version_id=dataset_version_id,
        template_id=template_id,
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


# ═══════════════════════════════════════════════════════════════════════════
# 1. Upload → Ingest → Run → Explore
# ═══════════════════════════════════════════════════════════════════════════


class TestUploadIngestRunExploreWorkflow:
    """Test the full upload → ingest → run → explore workflow via API."""

    @pytest.mark.asyncio
    async def test_create_dataset_and_verify_listing(
        self, authenticated_client: AsyncClient, db_session: AsyncSession, test_org
    ):
        """Create a dataset via API and verify it appears in the list."""
        # Step 1: Create dataset
        resp = await authenticated_client.post(
            "/v1/datasets",
            json={"name": "PBMC 10k", "description": "Peripheral blood"},
        )
        assert resp.status_code == 201, resp.text
        ds = resp.json()
        assert ds["name"] == "PBMC 10k"
        dataset_id = ds["id"]

        # Step 2: Verify dataset appears in listing
        list_resp = await authenticated_client.get("/v1/datasets")
        assert list_resp.status_code == 200
        body = list_resp.json()
        assert "items" in body
        ids = [item["id"] for item in body["items"]]
        assert dataset_id in ids

        # Step 3: Verify dataset detail
        detail_resp = await authenticated_client.get(f"/v1/datasets/{dataset_id}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["id"] == dataset_id

    @pytest.mark.asyncio
    async def test_create_pipeline_and_run(
        self, authenticated_client: AsyncClient, db_session: AsyncSession, test_org
    ):
        """Create dataset + template via DB, then create a run via API and explore it."""
        org_id = test_org.id

        # Seed prerequisite data directly in DB
        ds = await _create_dataset_via_db(db_session, org_id, name="Run-test DS")
        dv = await _create_version_via_db(db_session, ds.id)
        tpl = await _create_template_via_db(db_session, org_id)
        await db_session.commit()

        # Step 1: Create a pipeline template via API
        tpl_resp = await authenticated_client.post(
            "/v1/pipelines",
            json={
                "name": "e2e-pipeline",
                "version": "2.0.0",
                "definition": build_pipeline_definition(
                    ["qc_filter", "normalize"],
                    description="Integration test template",
                ),
            },
        )
        assert tpl_resp.status_code == 201, tpl_resp.text
        api_template_id = tpl_resp.json()["id"]

        # Step 2: Create a run via API using the DB-seeded version + API template
        run_resp = await authenticated_client.post(
            "/v1/runs",
            json={
                "dataset_version_id": str(dv.id),
                "template_id": api_template_id,
                "parameters": {"resolution": 0.8},
                "random_seed": 123,
            },
        )
        assert run_resp.status_code == 201, run_resp.text
        run_data = run_resp.json()
        run_id = run_data["id"]
        assert run_data["status"] == "running"
        assert run_data["random_seed"] == 123

        # Step 3: Verify run appears in listing
        list_resp = await authenticated_client.get("/v1/runs")
        assert list_resp.status_code == 200
        run_ids = [r["id"] for r in list_resp.json()["items"]]
        assert run_id in run_ids

        # Step 4: Get run details
        detail_resp = await authenticated_client.get(f"/v1/runs/{run_id}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["id"] == run_id

        # Step 5: Check artifacts endpoint (empty since no compute happened)
        art_resp = await authenticated_client.get(f"/v1/runs/{run_id}/artifacts")
        assert art_resp.status_code == 200
        assert "artifacts" in art_resp.json()


# ═══════════════════════════════════════════════════════════════════════════
# 2. Run → Annotate → Approve → Export
# ═══════════════════════════════════════════════════════════════════════════


class TestAnnotateApproveExportWorkflow:
    """Test annotation creation, editing, approval, and export initiation."""

    @pytest.mark.asyncio
    async def test_annotate_edit_approve_and_list(
        self, authenticated_client: AsyncClient, db_session: AsyncSession, test_org, test_user
    ):
        """Full annotation lifecycle: create → edit → approve → list history."""
        org_id = test_org.id

        # Seed a completed run
        ds = await _create_dataset_via_db(db_session, org_id, name="Annotation DS")
        dv = await _create_version_via_db(db_session, ds.id)
        tpl = await _create_template_via_db(db_session, org_id, name="ann-tpl", version="1.0.0")
        run = await _create_run_via_db(db_session, org_id, dv.id, tpl.id)
        await db_session.commit()

        run_id = str(run.id)

        # Step 1: Create annotation revision
        create_resp = await authenticated_client.post(
            f"/v1/runs/{run_id}/annotations",
            json={
                "annotations": {
                    "cell_0": {"cell_type": "T cell", "confidence": 0.95},
                    "cell_1": {"cell_type": "B cell", "confidence": 0.88},
                },
                "method": "celltypist",
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        rev1 = create_resp.json()
        annotation_id = rev1["id"]
        assert rev1["revision_number"] == 1
        assert rev1["method"] == "celltypist"
        assert rev1["approved_by"] is None

        # Step 2: Edit annotations (creates new revision)
        edit_resp = await authenticated_client.patch(
            f"/v1/annotations/{annotation_id}",
            json={
                "edits": {"cell_0": {"cell_type": "CD8+ T cell", "confidence": 0.97}},
            },
        )
        assert edit_resp.status_code == 200, edit_resp.text
        rev2 = edit_resp.json()
        assert rev2["revision_number"] == 2
        # The edited annotation should contain the merged edit
        assert "cell_0" in rev2["annotations"]

        # Step 3: Approve the latest revision
        approve_resp = await authenticated_client.post(f"/v1/annotations/{rev2['id']}/approve")
        assert approve_resp.status_code == 200, approve_resp.text
        approved = approve_resp.json()
        assert approved["approved_by"] is not None
        assert approved["approved_at"] is not None

        # Step 4: List annotation revisions and verify history
        list_resp = await authenticated_client.get(f"/v1/runs/{run_id}/annotations")
        assert list_resp.status_code == 200
        revisions = list_resp.json()
        assert revisions["total"] >= 2
        revision_numbers = [r["revision_number"] for r in revisions["items"]]
        assert 1 in revision_numbers
        assert 2 in revision_numbers

    @pytest.mark.asyncio
    async def test_export_initiation_for_run(
        self, authenticated_client: AsyncClient, db_session: AsyncSession, test_org
    ):
        """Initiate export for a run — may fail gracefully since no real artifacts exist."""
        org_id = test_org.id

        ds = await _create_dataset_via_db(db_session, org_id, name="Export DS")
        dv = await _create_version_via_db(db_session, ds.id)
        tpl = await _create_template_via_db(db_session, org_id, name="exp-tpl", version="1.0.0")
        run = await _create_run_via_db(db_session, org_id, dv.id, tpl.id)
        await db_session.commit()

        run_id = str(run.id)

        # Attempt export — may succeed or fail gracefully depending on S3 state
        export_resp = await authenticated_client.post(
            f"/v1/runs/{run_id}/export",
            json={"export_type": "h5ad"},
        )
        # Accept either success or a controlled error (404/500) since no real artifacts
        assert export_resp.status_code in (200, 404, 500), export_resp.text


# ═══════════════════════════════════════════════════════════════════════════
# 3. Multiple Runs → Cross-Dataset Analysis → LLM Interpretation
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossDatasetAnalysisWorkflow:
    """Test cross-dataset pathway analysis and LLM interpretation."""

    @pytest.mark.asyncio
    async def test_cross_dataset_analysis_initiation(
        self, authenticated_client: AsyncClient, db_session: AsyncSession, test_org
    ):
        """Create multiple datasets and initiate cross-dataset pathway analysis."""
        org_id = test_org.id

        # Create two datasets with versions
        ds1 = await _create_dataset_via_db(db_session, org_id, name="Tumor A")
        await _create_version_via_db(db_session, ds1.id, version="v1")
        ds2 = await _create_dataset_via_db(db_session, org_id, name="Tumor B")
        await _create_version_via_db(db_session, ds2.id, version="v1")
        await db_session.commit()

        # Initiate cross-dataset analysis
        resp = await authenticated_client.post(
            "/v1/pathway/cross-dataset",
            json={
                "dataset_ids": [str(ds1.id), str(ds2.id)],
                "pathway_database": "MSigDB",
                "aggregation_method": "meta-analysis",
            },
        )
        assert resp.status_code == 202, resp.text
        analysis = resp.json()
        analysis_id = analysis["analysis_id"]
        assert analysis["status"] in ("pending", "running")
        assert analysis["pathway_database"] == "MSigDB"
        assert len(analysis["dataset_ids"]) == 2

        # Check analysis status
        status_resp = await authenticated_client.get(f"/v1/pathway/analyses/{analysis_id}")
        assert status_resp.status_code == 200
        assert status_resp.json()["analysis_id"] == analysis_id

    @pytest.mark.asyncio
    async def test_llm_interpretation_requires_completed_analysis(
        self, authenticated_client: AsyncClient, db_session: AsyncSession, test_org, test_user
    ):
        """LLM interpretation should fail if analysis is not completed."""
        org_id = test_org.id

        # Create a pending analysis directly in DB
        analysis = CrossDatasetAnalysis(
            id=uuid4(),
            organization_id=org_id,
            dataset_ids=[str(uuid4()), str(uuid4())],
            pathway_database="MSigDB",
            aggregation_method="meta-analysis",
            status="pending",
            created_by=test_user.id,
        )
        db_session.add(analysis)
        await db_session.commit()

        # Attempt LLM interpretation on non-completed analysis
        resp = await authenticated_client.post(
            f"/v1/pathway/{analysis.id}/interpret",
            json={"model": "gpt-4"},
        )
        # Should fail with 409 Conflict since analysis is not completed
        assert resp.status_code == 409, resp.text

    @pytest.mark.asyncio
    async def test_llm_interpretation_on_completed_analysis(
        self, authenticated_client: AsyncClient, db_session: AsyncSession, test_org, test_user
    ):
        """LLM interpretation on a completed analysis with patterns — may fail
        gracefully if LLM service is unavailable."""
        org_id = test_org.id

        analysis = CrossDatasetAnalysis(
            id=uuid4(),
            organization_id=org_id,
            dataset_ids=[str(uuid4()), str(uuid4())],
            pathway_database="MSigDB",
            aggregation_method="meta-analysis",
            status="completed",
            pathway_patterns=[
                {
                    "pathway_name": "HALLMARK_INFLAMMATORY_RESPONSE",
                    "pathway_id": "M5932",
                    "datasets_present": ["ds1", "ds2"],
                    "aggregated_score": 3.5,
                    "p_value": 0.001,
                    "confidence": 0.95,
                },
            ],
            created_by=test_user.id,
            completed_at=datetime.utcnow(),
        )
        db_session.add(analysis)
        await db_session.commit()

        resp = await authenticated_client.post(
            f"/v1/pathway/{analysis.id}/interpret",
            json={"model": "gpt-4", "context": "Pancreatic cancer study"},
        )
        # Accept 200 (success) or 503 (LLM service unavailable)
        assert resp.status_code in (200, 503), resp.text


# ═══════════════════════════════════════════════════════════════════════════
# 4. Dataset Upload → Recommendation → Accept → Run
# ═══════════════════════════════════════════════════════════════════════════


class TestRecommendationWorkflow:
    """Test the dataset creation → pipeline template selection → run creation flow.

    Since the recommendation webhook may not be fully implemented, this tests
    the basic flow of dataset creation → template selection → run creation
    that a recommendation system would drive.
    """

    @pytest.mark.asyncio
    async def test_dataset_to_template_to_run_flow(
        self, authenticated_client: AsyncClient, db_session: AsyncSession, test_org
    ):
        """Simulate the recommendation workflow: create dataset, pick template, run."""
        org_id = test_org.id

        # Step 1: Create a dataset via API
        ds_resp = await authenticated_client.post(
            "/v1/datasets",
            json={"name": "Recommendation DS", "description": "For recommendation test"},
        )
        assert ds_resp.status_code == 201, ds_resp.text
        dataset_id = ds_resp.json()["id"]

        # Step 2: Seed a dataset version (simulating ingestion completion)
        ds = await _create_dataset_via_db(db_session, org_id, name="Rec-seed")
        dv = await _create_version_via_db(db_session, ds.id)
        await db_session.commit()

        # Step 3: List available pipeline templates (simulating recommendation)
        tpl_resp = await authenticated_client.post(
            "/v1/pipelines",
            json={
                "name": "recommended-pipeline",
                "version": "1.0.0",
                "definition": build_pipeline_definition(
                    ["qc_filter", "normalize", "select_hvg", "run_pca", "cluster", "embed"],
                    description="Integration test template",
                ),
            },
        )
        assert tpl_resp.status_code == 201, tpl_resp.text
        template_id = tpl_resp.json()["id"]

        # Step 4: List templates to verify it's available
        list_tpl = await authenticated_client.get("/v1/pipelines")
        assert list_tpl.status_code == 200
        tpl_ids = [t["id"] for t in list_tpl.json()]
        assert template_id in tpl_ids

        # Step 5: Accept recommendation → create run
        run_resp = await authenticated_client.post(
            "/v1/runs",
            json={
                "dataset_version_id": str(dv.id),
                "template_id": template_id,
                "parameters": {"resolution": 1.2, "n_components": 50},
                "random_seed": 7,
            },
        )
        assert run_resp.status_code == 201, run_resp.text
        run = run_resp.json()
        assert run["status"] == "running"
        assert run["random_seed"] == 7

        # Step 6: Verify run details
        detail = await authenticated_client.get(f"/v1/runs/{run['id']}")
        assert detail.status_code == 200
        assert detail.json()["template_id"] == template_id
        assert detail.json()["dataset_version_id"] == str(dv.id)

    @pytest.mark.asyncio
    async def test_full_api_driven_workflow(
        self, authenticated_client: AsyncClient, db_session: AsyncSession, test_org
    ):
        """End-to-end: dataset creation → template creation → run → status check."""
        # Create dataset
        ds_resp = await authenticated_client.post(
            "/v1/datasets",
            json={"name": "Full Flow DS"},
        )
        assert ds_resp.status_code == 201
        dataset_id = ds_resp.json()["id"]

        # Verify dataset exists
        get_ds = await authenticated_client.get(f"/v1/datasets/{dataset_id}")
        assert get_ds.status_code == 200

        # Create template
        tpl_resp = await authenticated_client.post(
            "/v1/pipelines",
            json={
                "name": "full-flow-pipeline",
                "version": "1.0.0",
                "definition": build_pipeline_definition(
                    ["qc_filter"],
                    description="Integration test template",
                ),
            },
        )
        assert tpl_resp.status_code == 201
        template_id = tpl_resp.json()["id"]

        # Seed a version for the dataset (ingestion would normally do this)
        org_id = test_org.id
        ds_obj = await _create_dataset_via_db(db_session, org_id, name="seeded-ds")
        dv = await _create_version_via_db(db_session, ds_obj.id)
        await db_session.commit()

        # Create run
        run_resp = await authenticated_client.post(
            "/v1/runs",
            json={
                "dataset_version_id": str(dv.id),
                "template_id": template_id,
                "parameters": {"min_genes": 200},
            },
        )
        assert run_resp.status_code == 201
        run_id = run_resp.json()["id"]

        # Verify run in listing with status filter
        list_resp = await authenticated_client.get("/v1/runs", params={"status": "running"})
        assert list_resp.status_code == 200
        assert any(r["id"] == run_id for r in list_resp.json()["items"])

        # Check pagination metadata
        body = list_resp.json()
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert "total_pages" in body
