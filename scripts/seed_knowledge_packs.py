#!/usr/bin/env python3
"""Seed initial knowledge packs into the Zerna platform.

Supports two modes:
  - Local (direct DB): seeds packs via KnowledgePackService directly
  - Remote (API):      seeds packs via POST /v1/knowledge-packs

Usage:
  python scripts/seed_knowledge_packs.py                     # local mode (default)
  python scripts/seed_knowledge_packs.py --dry-run           # preview only
  python scripts/seed_knowledge_packs.py --api-url http://localhost:8000  # remote mode
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data" / "knowledge_packs"

# Each entry: (json_filename, pack_name, version, pack_type)
KNOWLEDGE_PACKS: list[tuple[str, str, str, str]] = [
    ("cell_type_markers_v1.json", "cell_type_markers", "1.0.0", "cell_type_markers"),
    ("msigdb_hallmark_v1.json", "msigdb_hallmark", "1.0.0", "pathway_database"),
    ("go_biological_process_v1.json", "go_biological_process", "1.0.0", "pathway_database"),
    ("kegg_pathways_v1.json", "kegg_pathways", "1.0.0", "pathway_database"),
    ("ligand_receptor_pairs_v1.json", "ligand_receptor_pairs", "1.0.0", "ligand_receptor_pairs"),
]


def load_pack_data(filename: str) -> dict[str, Any]:
    """Load and return JSON data from the data directory."""
    filepath = DATA_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Seed data file not found: {filepath}")
    with open(filepath) as f:
        return json.load(f)


def summarize_pack(data: dict[str, Any], pack_type: str) -> str:
    """Return a human-readable summary of pack contents."""
    if pack_type == "cell_type_markers":
        markers = data.get("markers", {})
        return f"{len(markers)} cell types, {sum(len(v) for v in markers.values())} total markers"
    elif pack_type == "pathway_database":
        pathways = data.get("pathways", {})
        return f"{len(pathways)} pathways, {sum(len(v) for v in pathways.values())} total genes"
    elif pack_type == "ligand_receptor_pairs":
        pairs = data.get("pairs", [])
        return f"{len(pairs)} ligand-receptor pairs"
    return "unknown format"


def dry_run() -> None:
    """Preview what would be created without making changes."""
    print("=== DRY RUN — no changes will be made ===\n")
    for filename, name, version, pack_type in KNOWLEDGE_PACKS:
        data = load_pack_data(filename)
        summary = summarize_pack(data, pack_type)
        print(f"  [{pack_type}] {name} v{version}")
        print(f"    source: {filename}")
        print(f"    contents: {summary}")
        print()
    print(f"Total: {len(KNOWLEDGE_PACKS)} knowledge packs would be created.")


# ---------------------------------------------------------------------------
# Remote mode — seed via HTTP API
# ---------------------------------------------------------------------------


def seed_remote(api_url: str) -> None:
    """Seed knowledge packs via the REST API."""
    try:
        import httpx
    except ImportError:
        print("ERROR: httpx is required for remote mode. Install with: pip install httpx")
        sys.exit(1)

    base = api_url.rstrip("/")
    created = 0
    skipped = 0

    for filename, name, version, pack_type in KNOWLEDGE_PACKS:
        data = load_pack_data(filename)
        summary = summarize_pack(data, pack_type)
        s3_path = f"knowledge-packs/{name}/{version}/data"

        payload = {
            "name": name,
            "version": version,
            "pack_type": pack_type,
            "s3_path": s3_path,
            "schema_version": "1.0",
            "metadata": {"source": filename, "description": summary},
        }

        resp = httpx.post(f"{base}/v1/knowledge-packs", json=payload, timeout=30)
        if resp.status_code == 201:
            print(f"  ✓ Created {name} v{version} ({summary})")
            created += 1
        elif resp.status_code == 409:
            print(f"  – Skipped {name} v{version} (already exists)")
            skipped += 1
        else:
            print(f"  ✗ Failed {name} v{version}: {resp.status_code} {resp.text}")

    print(f"\nDone. Created: {created}, Skipped: {skipped}")


# ---------------------------------------------------------------------------
# Local mode — seed directly via service + DB
# ---------------------------------------------------------------------------


def seed_local() -> None:
    """Seed knowledge packs directly through the service layer."""
    import asyncio

    async def _seed() -> None:
        # Import here so the script can still --dry-run without a running DB
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker

        from apps.api.config import settings
        from apps.api.services.knowledge_pack_service import KnowledgePackService

        engine = create_async_engine(settings.database_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        created = 0
        skipped = 0

        async with async_session() as session:
            service = KnowledgePackService(db=session)

            for filename, name, version, pack_type in KNOWLEDGE_PACKS:
                data = load_pack_data(filename)
                summary = summarize_pack(data, pack_type)
                s3_path = f"knowledge-packs/{name}/{version}/data"

                # Check if already exists
                existing = await service.get_knowledge_pack_by_name_version(name, version)
                if existing is not None:
                    print(f"  – Skipped {name} v{version} (already exists)")
                    skipped += 1
                    continue

                from zerna_contracts.enums import KnowledgePackType

                pack_type_enum = KnowledgePackType(pack_type)
                await service.create_knowledge_pack(
                    name=name,
                    version=version,
                    pack_type=pack_type_enum,
                    s3_path=s3_path,
                    schema_version="1.0",
                    metadata={"source": filename, "description": summary},
                )
                print(f"  ✓ Created {name} v{version} ({summary})")
                created += 1

        await engine.dispose()
        print(f"\nDone. Created: {created}, Skipped: {skipped}")

    asyncio.run(_seed())


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed initial knowledge packs into Zerna.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be created without making changes.",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=None,
        help="Base URL for remote API mode (e.g. http://localhost:8000). "
        "If omitted, seeds directly via the database.",
    )
    args = parser.parse_args()

    print("Zerna Knowledge Pack Seeder")
    print("=" * 40)

    if args.dry_run:
        dry_run()
    elif args.api_url:
        print(f"Mode: Remote API ({args.api_url})\n")
        seed_remote(args.api_url)
    else:
        print("Mode: Local (direct DB)\n")
        seed_local()


if __name__ == "__main__":
    main()
