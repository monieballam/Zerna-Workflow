#!/usr/bin/env python3
"""
Delete S3/MinIO objects under a prefix (default: pipeline runs) to free space.

Use when MinIO returns XMinioStorageFull / "minimum free drive threshold" — that is a
real disk/quota condition; application code cannot fix it without deleting objects or
expanding storage.

Examples (from repo root, with boto3 available e.g. apps/api venv):

  export S3_ENDPOINT_URL=http://127.0.0.1:19000
  export S3_ACCESS_KEY_ID=minioadmin
  export S3_SECRET_ACCESS_KEY=minioadmin
  python scripts/prune_artifacts_bucket.py --dry-run
  python scripts/prune_artifacts_bucket.py

  # Only a single run prefix:
  python scripts/prune_artifacts_bucket.py --prefix runs/e0072b70-ad9d-45ae-801d-f54c914e2716/
"""

from __future__ import annotations

import argparse
import os
import sys

try:
    import boto3
    from botocore.client import Config
except ImportError:
    print("Install boto3: pip install boto3", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--bucket",
        default=os.environ.get("S3_ARTIFACTS_BUCKET", "zerna-artifacts-dev"),
        help="Bucket name (default: S3_ARTIFACTS_BUCKET or zerna-artifacts-dev)",
    )
    p.add_argument(
        "--prefix",
        default="runs/",
        help="Key prefix to delete (default: runs/)",
    )
    p.add_argument(
        "--endpoint-url",
        default=os.environ.get("S3_ENDPOINT_URL", "http://127.0.0.1:19000"),
        help="S3 API endpoint (default: S3_ENDPOINT_URL or local MinIO)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List objects that would be deleted, do not delete",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print every object key (can be very large)",
    )
    args = p.parse_args()

    client = boto3.client(
        "s3",
        endpoint_url=args.endpoint_url,
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY_ID", "minioadmin"),
        aws_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY", "minioadmin"),
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        config=Config(
            signature_version="s3v4", s3={"addressing_style": "path"} if args.endpoint_url else {}
        ),
    )

    paginator = client.get_paginator("list_objects_v2")
    n = 0
    for page in paginator.paginate(Bucket=args.bucket, Prefix=args.prefix):
        for obj in page.get("Contents") or []:
            key = obj["Key"]
            n += 1
            if args.dry_run:
                if args.verbose:
                    print("dry-run:", key)
            else:
                client.delete_object(Bucket=args.bucket, Key=key)
                if args.verbose:
                    print("deleted:", key)

    action = "Would delete" if args.dry_run else "Deleted"
    print(f"{action} {n} object(s) under s3://{args.bucket}/{args.prefix}", file=sys.stderr)


if __name__ == "__main__":
    main()
