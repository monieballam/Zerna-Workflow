"""H5AD-safe serialization for ``adata.uns`` (nested dicts / list-of-dicts / numpy).

Used by the annotation agent temp write, partition evidence, and workflow snapshots.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from uuid import UUID

__all__ = [
    "NESTED_UNS_EXPLICIT_KEYS",
    "UNS_SKIP_BROAD_SERIALIZE",
    "is_h5ad_scalar",
    "serialize_uns_for_h5ad",
    "sanitize_explorer_uns_for_h5ad",
]


def is_h5ad_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _pack_h5ad_uns_structure(value: object) -> object:
    """After numpy/pandas coercion, flatten list-of-dicts (and similar) to JSON strings for h5py."""
    if isinstance(value, dict):
        return {str(key): _pack_h5ad_uns_structure(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        converted = [_pack_h5ad_uns_structure(item) for item in list(value)]
        if all(is_h5ad_scalar(item) for item in converted):
            return converted
        return json.dumps(converted, allow_nan=False, default=str)
    return value


def serialize_uns_for_h5ad(value: object) -> object:
    """Convert nested annotation / explorer payloads into H5AD-safe values.

    AnnData maps heterogeneous Python lists in ``uns`` groups onto h5py vlen UTF-8
    datasets; lists of dicts, tuples, numpy scalars, UUIDs, etc. raise
    ``Can't implicitly convert non-string objects to strings``. Non-scalar lists
    become JSON strings; dicts recurse.

    Normalization reuses ``methods.h5ad_uns_coercion._sanitize_for_h5ad_uns`` so pandas
    objects, numpy scalars, and object arrays are coerced before list packing.
    """
    from methods.h5ad_uns_coercion import _sanitize_for_h5ad_uns

    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    cleaned = _sanitize_for_h5ad_uns(value)
    return _pack_h5ad_uns_structure(cleaned)


# Keys known to hold nested dict/list structures from annotation / cluster summaries.
NESTED_UNS_EXPLICIT_KEYS: frozenset[str] = frozenset(
    {
        "zerna_cluster_annotations",
        "cluster_retrieval_evidence",
        "cluster_markers",
        "conservative_annotation_audit",
        "annotation_benchmark",
        "label_merge_report",
        "explorer_partition_inspector_v1",
        "cluster_marker_evidence_v1",
        "lineage_subcluster_marker_evidence_v1",
        "fine_subcluster_marker_evidence_v1",
        # Scanpy DE output (structured arrays / nested dicts break h5py string conversion).
        "rank_genes_groups",
    }
)
# Skip: handled by dedicated migrations (list-shaped legacy fields).
UNS_SKIP_BROAD_SERIALIZE: frozenset[str] = frozenset({"zerna_qc_report", "zerna_provenance"})


def sanitize_explorer_uns_for_h5ad(adata) -> None:
    """Ensure nested ``uns`` payloads (annotation, cluster evidence, benchmarks) survive h5ad write.

    Every dict/list/ndarray under ``uns`` is serialized except ``zerna_qc_report`` and
    ``zerna_provenance``, which have dedicated migrations in the workflow snapshot path.
    Prefix-only coverage missed Scanpy keys like ``neighbors`` and custom nested blobs.
    """
    import numpy as np

    for key in list(adata.uns.keys()):
        if key in UNS_SKIP_BROAD_SERIALIZE:
            continue
        val = adata.uns[key]
        if isinstance(val, (np.ndarray, dict, list)):
            adata.uns[key] = serialize_uns_for_h5ad(val)
