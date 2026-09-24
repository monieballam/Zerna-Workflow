"""Preserve existing annotation columns before a rewrite."""

from __future__ import annotations

from typing import Any


def preserve_annotation_columns_before_rewrite(adata: Any) -> None:
    """No-op: Zerna annotation writes CellTypist columns without a hierarchy rewrite."""
    return None
