#!/usr/bin/env python3
"""
Canonical vocabulary / explorer-contract audit for one processed H5AD.

This uses ``apps.api.services.annotation_audit`` (per-cell table + Parquet/CSV exports),
distinct from ``scripts/run_annotation_audit.py`` (methods.annotation.audit — hierarchy/P3 QA).

Pick one source:
  - Local ``path/to/file.h5ad``
  - ``--s3-uri`` or ``--artifact-key`` (same as ``run_annotation_audit.py``)
  - ``--run-id`` + ``--org-id`` — resolves the latest completed-run H5AD like Run Explorer
    (needs ``DATABASE_URL`` and ``S3_*`` in the environment, same as the API).

Examples:
  PYTHONPATH=. uv run python scripts/run_explorer_contract_audit.py ./processed.h5ad --out-dir ./audit_ec
  PYTHONPATH=. uv run python scripts/run_explorer_contract_audit.py \\
    --run-id "$RUN_ID" --org-id "$ORG_ID" --out-dir ./audit_ec --max-cells 50000
  # Stromal-only slice (same engine as full audit; prints per-lineage table for all cells by default):
  PYTHONPATH=. uv run python scripts/run_explorer_contract_audit.py ./processed.h5ad \\
    --lineage Stromal --out-dir ./audit_stromal

API (authenticated): use Run Explorer + client-side export, or add a dedicated route later.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from uuid import UUID

import anndata as ad
import pandas as pd


def _download_h5ad_from_s3(path_spec: str, *, artifacts_bucket: str) -> Path:
    from apps.api.config import get_settings
    from apps.api.services.s3_service import S3Service
    from methods.annotation.audit.s3_h5ad import resolve_s3_bucket_and_key

    settings = get_settings()
    bucket, key = resolve_s3_bucket_and_key(
        path_spec, default_bucket=artifacts_bucket or settings.s3_artifacts_bucket
    )
    s3 = S3Service(settings)
    fd, tmp = tempfile.mkstemp(suffix=".h5ad", prefix="explorer_contract_audit_")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        s3.s3_client.download_file(bucket, key, str(tmp_path))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path


async def _h5ad_path_from_run(*, run_id: UUID, org_id: UUID) -> Path:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from apps.api.services.run_explorer_service import RunExplorerService

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("DATABASE_URL must be set when using --run-id / --org-id")

    engine = create_async_engine(db_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            svc = RunExplorerService(session)
            return await svc.get_primary_h5ad_local_path(run_id=run_id, org_id=org_id)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explorer canonical-vocabulary audit (per-cell table + exports)"
    )
    parser.add_argument(
        "h5ad",
        nargs="?",
        type=Path,
        default=None,
        help="Local .h5ad path",
    )
    parser.add_argument("--s3-uri", default=None, metavar="URI")
    parser.add_argument("--artifact-key", default=None, metavar="KEY")
    parser.add_argument(
        "--artifacts-bucket",
        default=None,
        help="Override bucket for --artifact-key",
    )
    parser.add_argument("--run-id", default=None, help="Completed run UUID")
    parser.add_argument("--org-id", default=None, help="Organization UUID (required with --run-id)")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("explorer_contract_audit_out"),
        help="Directory for Parquet + CSV reports",
    )
    parser.add_argument(
        "--cluster-key",
        default="leiden",
        help="obs column used as ``cluster`` in the audit frame",
    )
    parser.add_argument(
        "--max-cells",
        type=int,
        default=None,
        help="Random subsample size (default: all cells)",
    )
    parser.add_argument(
        "--vocabulary-yaml",
        type=Path,
        default=None,
        help="Override path to annotation_canonical_vocabulary.yaml",
    )
    parser.add_argument(
        "--lineage",
        default=None,
        metavar="L1",
        help='Keep only cells where --auto-l1-col equals this value after strip (e.g. "Stromal")',
    )
    parser.add_argument(
        "--auto-l1-col",
        default="auto_level1",
        help="obs column used with --lineage (default: auto_level1)",
    )
    args = parser.parse_args()

    run_mode = bool(args.run_id or args.org_id)
    if run_mode and (not args.run_id or not args.org_id):
        print("Both --run-id and --org-id are required together.", file=sys.stderr)
        return 2

    n_src = sum(
        1
        for x in (
            args.h5ad is not None,
            bool(args.s3_uri),
            bool(args.artifact_key),
            run_mode,
        )
        if x
    )
    if n_src != 1:
        print(
            "Specify exactly one of: local h5ad path, --s3-uri, --artifact-key, or (--run-id and --org-id)",
            file=sys.stderr,
        )
        return 2

    from apps.api.services.annotation_audit import (
        build_annotation_audit_table,
        cells_dataframe_from_anndata_obs,
        compute_annotation_metrics,
        export_annotation_audit_reports,
        load_canonical_vocabulary,
        summarize_structural_by_lineage,
    )

    vocab = load_canonical_vocabulary(args.vocabulary_yaml)
    tmp_download: Path | None = None
    try:
        if args.run_id:
            h5 = asyncio.run(
                _h5ad_path_from_run(run_id=UUID(args.run_id), org_id=UUID(args.org_id))
            )
        elif args.s3_uri:
            from apps.api.config import get_settings

            tmp_download = _download_h5ad_from_s3(
                args.s3_uri,
                artifacts_bucket=get_settings().s3_artifacts_bucket,
            )
            h5 = tmp_download
        elif args.artifact_key:
            bucket = args.artifacts_bucket
            if not bucket:
                from apps.api.config import get_settings

                bucket = get_settings().s3_artifacts_bucket
            tmp_download = _download_h5ad_from_s3(args.artifact_key, artifacts_bucket=bucket)
            h5 = tmp_download
        else:
            h5 = args.h5ad.expanduser().resolve()
            if not h5.is_file():
                print(f"File not found: {h5}", file=sys.stderr)
                return 2

        adata = ad.read_h5ad(h5)
        try:
            if args.lineage is not None:
                col = args.auto_l1_col
                if col not in adata.obs.columns:
                    print(
                        f"--lineage requires column {col!r}; not in obs.",
                        file=sys.stderr,
                    )
                    return 3
                mask = adata.obs[col].astype(str).str.strip().eq(args.lineage)
                n_before = int(adata.n_obs)
                adata = adata[mask].copy()
                print(
                    f"Filtered {col}=={args.lineage!r}: {adata.n_obs} / {n_before} cells",
                    file=sys.stderr,
                )
            cells_df = cells_dataframe_from_anndata_obs(
                adata.obs,
                cluster_key=args.cluster_key,
                max_cells=args.max_cells,
            )
            audit_df = build_annotation_audit_table(cells_df, vocab=vocab)
            metrics = compute_annotation_metrics(audit_df, vocab=vocab)
        finally:
            del adata

        args.out_dir.mkdir(parents=True, exist_ok=True)
        export_annotation_audit_reports(audit_df, str(args.out_dir))
        metrics_path = args.out_dir / "annotation_audit_metrics.json"
        metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

        print(json.dumps(metrics, indent=2))
        lineage_summary = summarize_structural_by_lineage(audit_df)
        if not lineage_summary.empty:
            print("\nStructural summary by canonical L1 (all cell types in this slice):")
            # Wide table: use pandas string representation for readable CLI output
            with pd.option_context("display.max_rows", None, "display.width", 200):
                print(lineage_summary.to_string(index=False))
        print("Wrote reports under:", args.out_dir.resolve())
        print("  metrics:", metrics_path)
        return 0
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    finally:
        if tmp_download is not None:
            tmp_download.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
