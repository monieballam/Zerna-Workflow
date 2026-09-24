"""S3 path resolution for annotation audit (matches API artifact paths)."""

from __future__ import annotations

import pytest

from methods.annotation.audit.s3_h5ad import resolve_s3_bucket_and_key


def test_resolve_full_uri():
    b, k = resolve_s3_bucket_and_key(
        "s3://zerna-artifacts-dev/org-1/runs/run-1/h5ad/processed.h5ad",
        default_bucket="ignored",
    )
    assert b == "zerna-artifacts-dev"
    assert k == "org-1/runs/run-1/h5ad/processed.h5ad"


def test_resolve_bucket_relative_key():
    b, k = resolve_s3_bucket_and_key(
        "org-1/runs/run-1/h5ad/processed.h5ad",
        default_bucket="zerna-artifacts-dev",
    )
    assert b == "zerna-artifacts-dev"
    assert k == "org-1/runs/run-1/h5ad/processed.h5ad"


def test_resolve_rejects_empty():
    with pytest.raises(ValueError):
        resolve_s3_bucket_and_key("", default_bucket="b")
