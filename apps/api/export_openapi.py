"""Script to export the OpenAPI specification to a JSON file.

Usage:
    uv run python -m apps.api.export_openapi
    # or
    python apps/api/export_openapi.py

Output: openapi.json in the project root (or packages/sdk/openapi.json when --sdk is passed).
"""

import argparse
import json
import sys
from pathlib import Path


def export_spec(output_path: Path) -> None:
    """Generate and write the OpenAPI spec to disk."""
    # Import after path setup so relative imports resolve correctly
    from apps.api.main import app  # noqa: PLC0415

    schema = app.openapi()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schema, indent=2, default=str))
    print(f"OpenAPI spec written to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export Zerna OpenAPI specification")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("openapi.json"),
        help="Output file path (default: openapi.json)",
    )
    args = parser.parse_args()

    try:
        export_spec(args.output)
    except Exception as exc:
        print(f"Error exporting OpenAPI spec: {exc}", file=sys.stderr)
        sys.exit(1)
