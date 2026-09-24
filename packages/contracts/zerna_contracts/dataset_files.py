"""Shared dataset file heuristics used across API and workflow code."""

from __future__ import annotations

from pathlib import Path

METADATA_FILENAMES: tuple[str, ...] = (
    "meta.txt",
    "metadata.tsv",
    "metadata.csv",
    "cell_metadata.tsv",
    "cell_metadata.csv",
    "barcode_metadata.tsv",
    "barcode_metadata.csv",
    "cells_metadata.tsv",
    "cells_metadata.csv",
)

TENX_BUNDLE_SUFFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("matrix", ("matrix.mtx", "matrix.mtx.gz")),
    ("genes", ("genes.tsv", "genes.tsv.gz", "features.tsv", "features.tsv.gz")),
    ("barcodes", ("barcodes.tsv", "barcodes.tsv.gz")),
)


def looks_like_metadata_filename(path: str) -> bool:
    """Return whether a file path likely points at cell-level metadata."""
    filename = Path(path).name.strip().lower()
    if not filename:
        return False
    if filename in METADATA_FILENAMES:
        return True

    suffixes = (".txt", ".tsv", ".csv")
    if not filename.endswith(suffixes):
        return False

    stem = filename.removesuffix(".txt").removesuffix(".tsv").removesuffix(".csv")
    return "meta" in stem or "metadata" in stem


def _is_probably_temp_upload_dir_segment(name: str) -> bool:
    """True for multipart temp dirs (0,1,…) or generic temp roots — not a biological sample id."""
    if not name:
        return True
    if name.isdigit():
        return True
    lower = name.lower()
    return lower.startswith("zerna_") or lower.startswith("tmp") or lower in {"temp", "upload"}


def detect_10x_bundle_member(path: str) -> tuple[str | None, str | None, str | None]:
    """Return the 10x role, shared prefix / folder sample id, and canonical suffix for a file path.

    For standard GEO-style filenames (``matrix.mtx``, ``barcodes.tsv``, … with no sample token in
    the basename), the parent directory name is used as the bundle key when it is not a temp
    upload segment (e.g. ``…/GSM5793824/matrix.mtx.gz`` → prefix ``GSM5793824``).
    """
    p = Path(path)
    filename = p.name.lower()
    for role, suffixes in TENX_BUNDLE_SUFFIXES:
        for suffix in suffixes:
            if filename.endswith(suffix):
                stem_prefix = filename[: -len(suffix)].rstrip("._- ")
                if stem_prefix:
                    return role, stem_prefix, suffix
                parent = p.parent.name
                if parent and not _is_probably_temp_upload_dir_segment(parent):
                    return role, parent, suffix
                return role, None, suffix
    return None, None, None


def sanitize_storage_relative_path(raw: str) -> str:
    """Normalize a client-supplied relative path for nested dataset object keys.

    Rejects empty segments and path traversal. Uses forward slashes in the returned key.
    """
    p = raw.replace("\\", "/").strip().strip("/")
    if not p:
        raise ValueError("Empty storage relative path")
    parts: list[str] = []
    for seg in p.split("/"):
        seg = seg.strip()
        if not seg or seg in (".", "..") or ".." in seg:
            raise ValueError(f"Invalid storage path segment in {raw!r}")
        parts.append(seg)
    out = "/".join(parts)
    if len(out) > 512:
        raise ValueError("Storage relative path exceeds maximum length (512).")
    return out
