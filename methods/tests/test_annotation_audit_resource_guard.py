"""Unit tests for synchronous annotation-audit resource guards."""

from __future__ import annotations

from pathlib import Path

import anndata as ad
import numpy as np
import pytest

from methods.annotation.audit.resource_guard import (
    AnnotationAuditResourceError,
    assert_h5ad_safe_for_sync_annotation_audit,
)


def test_assert_h5ad_safe_for_sync_annotation_audit_rejects_large_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    h5ad_path = tmp_path / "audit.h5ad"
    ad.AnnData(X=np.eye(3, dtype=np.float32)).write_h5ad(h5ad_path)

    monkeypatch.setattr(
        "methods.annotation.audit.resource_guard._available_memory_bytes",
        lambda: 8 * 1024 * 1024 * 1024,
    )
    monkeypatch.setattr(
        "methods.annotation.audit.resource_guard.estimate_h5ad_in_memory_requirement_bytes",
        lambda path: 12 * 1024 * 1024 * 1024,
    )

    with pytest.raises(AnnotationAuditResourceError, match="too large"):
        assert_h5ad_safe_for_sync_annotation_audit(h5ad_path)


def test_assert_h5ad_safe_for_sync_annotation_audit_allows_small_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    h5ad_path = tmp_path / "audit_small.h5ad"
    ad.AnnData(X=np.eye(3, dtype=np.float32)).write_h5ad(h5ad_path)

    monkeypatch.setattr(
        "methods.annotation.audit.resource_guard._available_memory_bytes",
        lambda: 16 * 1024 * 1024 * 1024,
    )
    monkeypatch.setattr(
        "methods.annotation.audit.resource_guard.estimate_h5ad_in_memory_requirement_bytes",
        lambda path: 2 * 1024 * 1024 * 1024,
    )

    assert_h5ad_safe_for_sync_annotation_audit(h5ad_path)
