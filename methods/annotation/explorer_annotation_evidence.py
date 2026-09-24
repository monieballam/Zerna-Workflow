"""Explorer-facing evidence backfill for annotation artifacts (H5AD ``uns``).

Zerna / AnnotationAgentV3_0 often stores ``top_cell_types`` as tuples
``(cell_type_id, score, n_markers)``. The run explorer API expects dict-shaped
entries; this module normalizes both at read time (API) and optionally at save
time (annotation pipeline) so payloads stay JSON- and H5AD-safe.
"""

from __future__ import annotations

from typing import Any

import anndata as ad

from methods.annotation.cluster_marker_de import _compute_cluster_markers


def normalize_top_cell_types_entry(entry: Any) -> dict[str, Any] | None:
    """Coerce tuple/list/dict shapes into ``{cell_type, score, n_markers}``."""
    if entry is None:
        return None
    if isinstance(entry, dict):
        ct = entry.get("cell_type") or entry.get("cell_type_id")
        if ct is None:
            return None
        return {
            "cell_type": str(ct),
            "score": float(entry.get("adjusted_score", entry.get("score", 0.0)) or 0.0),
            "n_markers": int(entry.get("n_markers", 0) or 0),
        }
    if isinstance(entry, (list, tuple)) and len(entry) >= 1:
        ct = entry[0]
        score = float(entry[1]) if len(entry) > 1 else 0.0
        n_markers = int(entry[2]) if len(entry) > 2 else 0
        return {"cell_type": str(ct), "score": score, "n_markers": n_markers}
    return None


def _coerce_top_cell_types_list(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        norm = normalize_top_cell_types_entry(item)
        if norm is not None:
            out.append(norm)
    return out


def ensure_explorer_annotation_evidence(
    adata: ad.AnnData,
    cluster_key: str,
    *,
    top_n: int = 50,
    coerce_top_cell_types: bool = True,
) -> None:
    """Ensure ``uns['cluster_markers']`` and per-cluster ``cluster_markers`` exist.

    After AnnotationAgentV3_0 merge, ``cluster_markers`` can be missing or empty
    (e.g. upstream skipped DEGs). Recompute with the same helper used by legacy
    annotation paths. Optionally rewrite ``top_cell_types`` to dict lists for
    stable serialization.
    """
    ck = str(cluster_key)
    if ck not in adata.obs.columns:
        return

    cm_raw = adata.uns.get("cluster_markers")
    needs_compute = True
    if isinstance(cm_raw, dict) and cm_raw:
        cluster_ids = set(adata.obs[ck].astype(str).unique())
        needs_compute = False
        for cid in cluster_ids:
            genes = cm_raw.get(cid)
            if genes is None and str(cid).isdigit():
                genes = cm_raw.get(str(int(str(cid))))
            if not isinstance(genes, (list, tuple)) or len(genes) == 0:
                needs_compute = True
                break
    if needs_compute:
        cluster_markers, _rows = _compute_cluster_markers(adata, cluster_key=ck, top_n=top_n)
        if cluster_markers:
            adata.uns["cluster_markers"] = {
                str(k): [str(g) for g in genes[:top_n]] for k, genes in cluster_markers.items()
            }

    cm = adata.uns.get("cluster_markers")
    if not isinstance(cm, dict):
        return

    annotations = adata.uns.get("zerna_cluster_annotations")
    if not isinstance(annotations, dict):
        return

    for cid, ann in list(annotations.items()):
        if not isinstance(ann, dict):
            continue
        cid_s = str(cid)
        genes = cm.get(cid_s)
        if genes is None and cid_s.isdigit():
            genes = cm.get(str(int(cid_s)))
        genes_list: list[str] = []
        if isinstance(genes, (list, tuple)):
            genes_list = [str(g) for g in genes[:top_n]]
        if not ann.get("cluster_markers") and genes_list:
            ann["cluster_markers"] = genes_list
        if coerce_top_cell_types:
            tct = ann.get("top_cell_types")
            coerced = _coerce_top_cell_types_list(tct if isinstance(tct, list) else [])
            if coerced:
                ann["top_cell_types"] = coerced


def hierarchy_display_key_candidates(display_headline: str) -> list[str]:
    """
    Segments of a hierarchy headline for matching ``supporting_markers`` pack keys,
    **finest / right-most first** (e.g. ``Immune | T cells | CD8`` → CD8, T cells, Immune), then full string.
    """
    t = str(display_headline or "").strip()
    if not t or t.lower() in {"unknown", "nan", "none"}:
        return []
    parts = [p.strip() for p in t.split("|") if p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for p in reversed(parts):
        if p not in seen:
            seen.add(p)
            out.append(p)
    if t not in seen:
        out.append(t)
    return out


def _supporting_markers_get(
    sm: dict[str, Any], key: str, *, max_markers: int
) -> tuple[list[str], str] | None:
    if not key:
        return None
    if key in sm:
        raw = sm[key]
        if isinstance(raw, (list, tuple)) and len(raw) > 0:
            return [str(x) for x in list(raw)[:max_markers]], str(key)
    k_low = key.strip().lower()
    for sk, raw in sm.items():
        if str(sk).strip().lower() != k_low:
            continue
        if isinstance(raw, (list, tuple)) and len(raw) > 0:
            return [str(x) for x in list(raw)[:max_markers]], str(sk)
    return None


def pick_support_markers_for_display_headline(
    annotation: dict[str, Any],
    display_headline_label: str,
    *,
    max_markers: int = 15,
) -> tuple[list[str], str | None, bool]:
    """
    Resolve ``supporting_markers`` pack rows for the explorer headline / label.

    Returns ``(markers, matched_pack_key, aligned_with_finest_headline_segment)``.
    Does **not** fall back to an arbitrary unrelated pack key — returns empty markers if none match.

    Candidate order: hierarchy segments (fine → broad), full headline, ``normalized_label``,
    then ``top_cell_types`` (first several), matching case-insensitively on dict keys.
    """
    sm = annotation.get("supporting_markers")
    if not isinstance(sm, dict) or not sm:
        return [], None, True

    candidates: list[str] = []
    seen_keys: set[str] = set()

    def add(x: str | None) -> None:
        if x is None:
            return
        s = str(x).strip()
        if not s or s in seen_keys:
            return
        seen_keys.add(s)
        candidates.append(s)

    for seg in hierarchy_display_key_candidates(display_headline_label):
        add(seg)

    add(str(display_headline_label).strip() if display_headline_label else None)

    norm = annotation.get("normalized_label")
    if norm is not None and str(norm).strip():
        add(str(norm).strip())

    top_ct = annotation.get("top_cell_types") or []
    if isinstance(top_ct, list):
        for entry in top_ct[:8]:
            co = normalize_top_cell_types_entry(entry)
            if co and co.get("cell_type"):
                add(str(co["cell_type"]))

    finest_segments = hierarchy_display_key_candidates(display_headline_label)
    finest0 = (
        finest_segments[0] if finest_segments else str(display_headline_label).strip()
    ).strip()

    for key in candidates:
        got = _supporting_markers_get(sm, key, max_markers=max_markers)
        if not got:
            continue
        markers, matched_key = got
        mk_low = matched_key.strip().lower()
        aligned = mk_low == finest0.lower() if finest0 else False
        if not aligned and str(display_headline_label).strip():
            aligned = mk_low == str(display_headline_label).strip().lower()
        if not aligned and norm is not None and str(norm).strip():
            aligned = mk_low == str(norm).strip().lower()

        return markers, matched_key, aligned

    return [], None, False


__all__ = [
    "ensure_explorer_annotation_evidence",
    "hierarchy_display_key_candidates",
    "normalize_top_cell_types_entry",
    "pick_support_markers_for_display_headline",
]
