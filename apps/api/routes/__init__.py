"""API routes for Zerna API."""

from apps.api.routes.admin import router as admin_router
from apps.api.routes.annotations import router as annotations_router
from apps.api.routes.audit import router as audit_router
from apps.api.routes.auth import router as auth_router
from apps.api.routes.datasets import router as datasets_router
from apps.api.routes.embeddings import router as embeddings_router
from apps.api.routes.exports import router as exports_router
from apps.api.routes.feedback import router as feedback_router
from apps.api.routes.knowledge_packs import router as knowledge_packs_router
from apps.api.routes.nextflow import router as nextflow_router
from apps.api.routes.pathway import router as pathway_router
from apps.api.routes.pipelines import router as pipelines_router
from apps.api.routes.quotas import router as quotas_router
from apps.api.routes.results import router as results_router
from apps.api.routes.runs import router as runs_router
from apps.api.routes.uploads import router as uploads_router

__all__ = [
    "audit_router",
    "admin_router",
    "auth_router",
    "datasets_router",
    "embeddings_router",
    "exports_router",
    "feedback_router",
    "nextflow_router",
    "pipelines_router",
    "runs_router",
    "results_router",
    "knowledge_packs_router",
    "annotations_router",
    "pathway_router",
    "quotas_router",
    "uploads_router",
]
