#!/usr/bin/env python3
"""Create and monitor real pipeline-validation runs across option groups."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select

from apps.api.dependencies import _get_session_factory
from apps.api.models.organization import OrganizationUser
from apps.api.models.pipeline import PipelineTemplate, Run
from apps.api.services.run_service import RunService


@dataclass(frozen=True)
class ValidationCase:
    name: str
    template_name: str
    parameters: dict[str, Any]


DEFAULT_ORG_ID = UUID("a0000000-0000-0000-0000-000000000001")
DEFAULT_DATASET_ID = UUID("590a2816-1148-435c-826a-80e1384a49af")
DEFAULT_USER_ID = UUID("b0000000-0000-0000-0000-000000000001")

COMMON_DEFAULTS: dict[str, Any] = {
    "batch_correction": True,
    "batch_method": "harmony",
    "batch_key": "orig.ident",
    "clustering_method": "leiden",
    "embedding_method": "umap",
    "annotation_species": "mouse",
    "annotation_method": "hybrid",
    "annotation_marker_database": "zerna_default",
    "pathway_scoring": False,
    "ligand_receptor": False,
    "random_seed": 42,
    "max_epochs": 0,
}

DOUBLET_CASES = [
    ValidationCase(
        name="doublet_scrublet",
        template_name="scRNA-seq Standard",
        parameters={**COMMON_DEFAULTS, "doublet_method": "scrublet"},
    ),
    ValidationCase(
        name="doublet_solo",
        template_name="scRNA-seq Standard",
        parameters={
            **COMMON_DEFAULTS,
            "doublet_method": "solo",
            "solo_max_epochs": 20,
            "solo_batch_size": 512,
        },
    ),
    ValidationCase(
        name="doublet_doubletdetection",
        template_name="scRNA-seq Standard",
        parameters={**COMMON_DEFAULTS, "doublet_method": "doubletdetection"},
    ),
    ValidationCase(
        name="doublet_scDblFinder",
        template_name="scRNA-seq Standard",
        parameters={**COMMON_DEFAULTS, "doublet_method": "scDblFinder"},
    ),
    ValidationCase(
        name="doublet_DoubletFinder",
        template_name="scRNA-seq Standard",
        parameters={**COMMON_DEFAULTS, "doublet_method": "DoubletFinder"},
    ),
    ValidationCase(
        name="doublet_scds",
        template_name="scRNA-seq Standard",
        parameters={**COMMON_DEFAULTS, "doublet_method": "scds"},
    ),
]

ANNOTATION_METHOD_CASES = [
    ValidationCase(
        name="annotation_celltypist",
        template_name="scRNA-seq Standard",
        parameters={**COMMON_DEFAULTS, "annotation_method": "celltypist"},
    ),
    ValidationCase(
        name="annotation_marker_pack",
        template_name="scRNA-seq Standard",
        parameters={
            **COMMON_DEFAULTS,
            "annotation_method": "marker_pack",
            "annotation_marker_database": "zerna_default",
        },
    ),
    ValidationCase(
        name="annotation_hybrid",
        template_name="scRNA-seq Standard",
        parameters={
            **COMMON_DEFAULTS,
            "annotation_method": "hybrid",
            "annotation_marker_database": "zerna_default",
        },
    ),
]

MARKER_DATABASE_CASES = [
    ValidationCase(
        name=f"annotation_db_{database.lower()}",
        template_name="scRNA-seq Standard",
        parameters={
            **COMMON_DEFAULTS,
            "annotation_method": "hybrid",
            "annotation_marker_database": database,
        },
    )
    for database in [
        "zerna_default",
        "legacy_zerna_taxonomy",
        "legacy_universal_immune",
        "legacy_universal_stromal",
        "legacy_universal_epithelial",
        "legacy_universal_endothelial",
        "legacy_universal_states",
        "legacy_myeloid_hgm_subtypes",
        "legacy_stromal_hgm_subtypes",
    ]
]

PATHWAY_DATABASE_CASES = [
    ValidationCase(
        name=f"pathway_{database.lower()}",
        template_name="scRNA-seq Standard",
        parameters={
            **COMMON_DEFAULTS,
            "pathway_scoring": True,
            "pathway_database": database,
            "pathway_method": "ulm",
        },
    )
    for database in [
        "PROGENy",
        "DoRothEA",
        "Hallmark",
        "KEGG",
        "Reactome",
        "GO_Biological_Process",
    ]
]

STRESS_CASES = [
    ValidationCase(
        name="stress_solo_scvi_legacy_reactome_liana",
        template_name="scRNA-seq Standard",
        parameters={
            **COMMON_DEFAULTS,
            "batch_method": "scvi",
            "doublet_method": "solo",
            "solo_max_epochs": 20,
            "solo_batch_size": 512,
            "annotation_method": "celltypist",
            "pathway_scoring": True,
            "pathway_database": "Reactome",
            "pathway_method": "ulm",
            "ligand_receptor": True,
        },
    ),
]

GROUPS: dict[str, list[ValidationCase]] = {
    "stress": STRESS_CASES,
    "doublet": DOUBLET_CASES,
    "annotation_method": ANNOTATION_METHOD_CASES,
    "annotation_db": MARKER_DATABASE_CASES,
    "pathway_db": PATHWAY_DATABASE_CASES,
}


async def _resolve_user_id(org_id: UUID, requested_user_id: UUID | None) -> UUID:
    if requested_user_id is not None:
        return requested_user_id

    factory = _get_session_factory()
    async with factory() as db:
        user_id = (
            await db.execute(
                select(OrganizationUser.c.user_id)
                .where(OrganizationUser.c.organization_id == org_id)
                .order_by(OrganizationUser.c.user_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if user_id is None:
            raise ValueError(f"No user is attached to organization {org_id}")
        return user_id


async def _resolve_template_id(org_id: UUID, template_name: str) -> UUID:
    factory = _get_session_factory()
    async with factory() as db:
        template = (
            await db.execute(
                select(PipelineTemplate).where(
                    and_(
                        PipelineTemplate.organization_id == org_id,
                        PipelineTemplate.name == template_name,
                        PipelineTemplate.is_active.is_(True),
                    )
                )
            )
        ).scalar_one()
        return template.id


async def _create_and_start_run(
    *,
    org_id: UUID,
    user_id: UUID,
    dataset_version_id: UUID,
    case: ValidationCase,
) -> UUID:
    factory = _get_session_factory()
    template_id = await _resolve_template_id(org_id, case.template_name)
    async with factory() as db:
        service = RunService(db)
        run = await service.create_run(
            org_id=org_id,
            dataset_version_id=dataset_version_id,
            template_id=template_id,
            parameters=case.parameters,
            random_seed=int(case.parameters.get("random_seed", 42)),
            user_id=user_id,
        )
        run = await service.start_run(run.id)
        return run.id


async def _fetch_run(run_id: UUID) -> Run:
    factory = _get_session_factory()
    async with factory() as db:
        return (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()


def _format_progress(run: Run) -> str:
    parameters = run.parameters if isinstance(run.parameters, dict) else {}
    progress = parameters.get("progress", {}) if isinstance(parameters, dict) else {}
    current_step = progress.get("current_step") or progress.get("current_step_name") or "-"
    completed = progress.get("completed_steps", [])
    total = progress.get("total_steps", 0)
    percent = progress.get("percent_complete")
    return (
        f"step={current_step} completed={len(completed)}/{total or '?'} "
        f"percent={percent if percent is not None else '?'}"
    )


async def _monitor_run(run_id: UUID, *, poll_seconds: int, timeout_minutes: int) -> dict[str, Any]:
    deadline = datetime.now(UTC) + timedelta(minutes=timeout_minutes)
    last_signature: tuple[str, str, str] | None = None

    while True:
        run = await _fetch_run(run_id)
        status = getattr(run.status, "value", str(run.status))
        progress_summary = _format_progress(run)
        signature = (status, progress_summary, str(run.error_message or ""))
        if signature != last_signature:
            print(
                json.dumps(
                    {
                        "run_id": str(run_id),
                        "status": status,
                        "progress": progress_summary,
                        "error": run.error_message,
                    }
                )
            )
            last_signature = signature

        if status.lower() in {"completed", "failed", "cancelled"}:
            return {
                "run_id": str(run_id),
                "status": status,
                "error": run.error_message,
                "progress": progress_summary,
            }

        if datetime.now(UTC) >= deadline:
            return {
                "run_id": str(run_id),
                "status": "timeout",
                "error": "Validation monitor timed out",
                "progress": progress_summary,
            }

        await asyncio.sleep(poll_seconds)


def _build_case_list(groups: list[str]) -> list[ValidationCase]:
    ordered: list[ValidationCase] = []
    seen: set[str] = set()
    for group in groups:
        for case in GROUPS[group]:
            if case.name in seen:
                continue
            seen.add(case.name)
            ordered.append(case)
    return ordered


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--groups",
        nargs="+",
        choices=sorted(GROUPS),
        default=["stress"],
        help="Validation groups to execute sequentially.",
    )
    parser.add_argument("--org-id", type=UUID, default=DEFAULT_ORG_ID)
    parser.add_argument("--dataset-version-id", type=UUID, default=DEFAULT_DATASET_ID)
    parser.add_argument("--user-id", type=UUID, default=None)
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument("--timeout-minutes", type=int, default=180)
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop the matrix immediately when a run fails.",
    )
    args = parser.parse_args()

    user_id = await _resolve_user_id(args.org_id, args.user_id or DEFAULT_USER_ID)
    cases = _build_case_list(args.groups)
    print(
        json.dumps(
            {
                "org_id": str(args.org_id),
                "dataset_version_id": str(args.dataset_version_id),
                "user_id": str(user_id),
                "groups": args.groups,
                "cases": [case.name for case in cases],
            }
        )
    )

    results: list[dict[str, Any]] = []
    for case in cases:
        print(
            json.dumps(
                {"event": "starting_case", "case": case.name, "template": case.template_name}
            )
        )
        run_id = await _create_and_start_run(
            org_id=args.org_id,
            user_id=user_id,
            dataset_version_id=args.dataset_version_id,
            case=case,
        )
        result = await _monitor_run(
            run_id,
            poll_seconds=args.poll_seconds,
            timeout_minutes=args.timeout_minutes,
        )
        result["case"] = case.name
        results.append(result)
        print(json.dumps({"event": "case_finished", **result}))
        if args.stop_on_failure and result["status"].lower() != "completed":
            break

    print(json.dumps({"event": "summary", "results": results}, default=str))
    return 0 if all(result["status"].lower() == "completed" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
