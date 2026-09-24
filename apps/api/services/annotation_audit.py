"""
Annotation contract audit: canonical vocabulary, structural vs display integrity, explorer payloads.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

# --- Paths -----------------------------------------------------------------

# ``apps/api/config/`` holds YAML only (no ``__init__.py``) so it does not shadow ``apps.api.config`` from ``config.py``.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VOCABULARY_PATH = _PACKAGE_ROOT / "config" / "annotation_canonical_vocabulary.yaml"


@dataclass(frozen=True)
class CanonicalVocabulary:
    level1: frozenset[str]
    level2: frozenset[str]
    level3: frozenset[str]
    level2_by_level1: dict[str, frozenset[str]]
    level3_by_level2: dict[str, frozenset[str]]
    synonyms: dict[str, str]  # normalized key -> canonical
    forbidden_patterns: tuple[tuple[str, str], ...]  # (id, regex)


def _norm_key(s: str) -> str:
    return str(s).strip().casefold()


def _cell_str(val: object) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    t = str(val).strip()
    if not t or t.lower() in {"nan", "none", "nat"}:
        return None
    return t


def load_canonical_vocabulary(path: Path | str | None = None) -> CanonicalVocabulary:
    """Load YAML vocabulary from disk (cached per resolved path)."""
    p = Path(path) if path else DEFAULT_VOCABULARY_PATH
    return _load_canonical_vocabulary_resolved(str(p.resolve()))


@lru_cache(maxsize=8)
def _load_canonical_vocabulary_resolved(path_str: str) -> CanonicalVocabulary:
    path = Path(path_str)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raw = {}
    l1 = frozenset(str(x) for x in raw.get("level1_allowlist", []))
    l2_by_l1: dict[str, frozenset[str]] = {}
    all_l2: set[str] = set()
    for k, v in (raw.get("level2_by_level1") or {}).items():
        s = frozenset(str(x) for x in (v or []))
        l2_by_l1[str(k)] = s
        all_l2.update(s)
    l3_by_l2: dict[str, frozenset[str]] = {}
    all_l3: set[str] = set()
    for k, v in (raw.get("level3_by_level2") or {}).items():
        s = frozenset(str(x) for x in (v or []))
        l3_by_l2[str(k)] = s
        all_l3.update(s)
    syn: dict[str, str] = {}
    for raw_k, raw_v in (raw.get("synonyms") or {}).items():
        syn[_norm_key(str(raw_k))] = str(raw_v)
    patterns: list[tuple[str, str]] = []
    for entry in raw.get("forbidden_label_patterns") or []:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("id", "pattern"))
        pat = str(entry.get("pattern", ""))
        if pat:
            patterns.append((pid, pat))
    compiled = tuple(patterns)
    return CanonicalVocabulary(
        level1=l1,
        level2=frozenset(all_l2),
        level3=frozenset(all_l3),
        level2_by_level1=l2_by_l1,
        level3_by_level2=l3_by_l2,
        synonyms=syn,
        forbidden_patterns=compiled,
    )


def get_default_vocabulary() -> CanonicalVocabulary:
    return load_canonical_vocabulary()


def canonicalize_label(label: str | None, vocab: CanonicalVocabulary | None = None) -> str | None:
    """Map a raw label to canonical display text, or None if unknown."""
    v = vocab or get_default_vocabulary()
    s = _cell_str(label)
    if s is None:
        return None
    if s in v.level1 or s in v.level2 or s in v.level3:
        return s
    hit = v.synonyms.get(_norm_key(s))
    if hit:
        return hit
    for pool in (v.level1, v.level2, v.level3):
        for allowed in pool:
            if allowed.casefold() == s.casefold():
                return allowed
    return None


def _display_segment_is_canonical_spelling(segment: str, vocab: CanonicalVocabulary) -> bool:
    """True when ``segment`` is already the canonical token (not a raw synonym spelling)."""
    c = canonicalize_label(segment, vocab)
    return c is not None and segment == c


def _forbidden_match(text: str, vocab: CanonicalVocabulary) -> bool:
    if not text:
        return False
    for _pid, pat in vocab.forbidden_patterns:
        if re.search(pat, text):
            return True
    return False


def _split_display_pipe(s: str | None) -> list[str]:
    if not s:
        return []
    return [p.strip() for p in str(s).split("|") if p.strip()]


def _structural_from_auto(row: pd.Series) -> tuple[str | None, str | None, str | None]:
    return (
        _cell_str(row.get("auto_level1")),
        _cell_str(row.get("auto_level2")),
        _cell_str(row.get("auto_level3")),
    )


def _structural_from_legacy(row: pd.Series) -> tuple[str | None, str | None, str | None]:
    l1 = _cell_str(row.get("lineage")) or _cell_str(row.get("zr_level1"))
    l2 = _cell_str(row.get("zr_level2")) or _cell_str(row.get("level2"))
    l3 = (
        _cell_str(row.get("level3_final_safe"))
        or _cell_str(row.get("zr_level3"))
        or _cell_str(row.get("level3"))
    )
    return l1, l2, l3


def _row_has_auto_hierarchy(row: pd.Series, auto_cols_present: bool) -> bool:
    if not auto_cols_present:
        return False
    return _cell_str(row.get("auto_level1")) is not None


def _canonical_triplet(
    l1: str | None, l2: str | None, l3: str | None, vocab: CanonicalVocabulary
) -> tuple[str | None, str | None, str | None]:
    c1 = canonicalize_label(l1, vocab) if l1 else None
    c2 = canonicalize_label(l2, vocab) if l2 else None
    c3 = canonicalize_label(l3, vocab) if l3 else None
    return c1, c2, c3


def _expected_display(
    c1: str | None, c2: str | None, c3: str | None, l3_raw_empty: bool
) -> str | None:
    if not c1:
        return None
    if c2 and c3:
        return f"{c1} | {c2} | {c3}"
    if c2 and l3_raw_empty and c3 is None:
        return f"{c1} | {c2}"
    if c2:
        return f"{c1} | {c2}"
    return c1


def _display_source(row: pd.Series) -> str | None:
    return _cell_str(row.get("displayLabel")) or _cell_str(row.get("final_display"))


def _zr_leak_in_display_when_auto(
    row: pd.Series, has_auto: bool, vocab: CanonicalVocabulary
) -> bool:
    if not has_auto:
        return False
    disp = _display_source(row)
    if not disp:
        return False
    zr_vals = [
        x
        for x in (
            _cell_str(row.get("zr_level1")),
            _cell_str(row.get("zr_level2")),
            _cell_str(row.get("zr_level3")),
            _cell_str(row.get("zr_display")),
        )
        if x
    ]
    for z in zr_vals:
        if z in disp:
            return True
    return _forbidden_match(disp, vocab)


def build_annotation_audit_table(
    cells_df: pd.DataFrame,
    *,
    vocab: CanonicalVocabulary | None = None,
) -> pd.DataFrame:
    """
    Add audit columns. Expects optional columns listed in the task spec; missing columns are ignored.
    """
    v = vocab or get_default_vocabulary()
    df = cells_df.copy()
    auto_cols_present = all(c in df.columns for c in ("auto_level1", "auto_level2", "auto_level3"))

    s1l: list[str | None] = []
    s2l: list[str | None] = []
    s3l: list[str | None] = []
    has_auto: list[bool] = []
    l3_raw_empty: list[bool] = []
    legacy_fb: list[bool] = []
    canon_disp: list[str | None] = []
    disp_match: list[bool] = []
    unresolved: list[bool] = []
    noncanon: list[bool] = []
    disagree: list[bool] = []
    c1s: list[str | None] = []
    c2s: list[str | None] = []
    c3s: list[str | None] = []

    for _, row in df.iterrows():
        ha = _row_has_auto_hierarchy(row, auto_cols_present)
        if ha:
            r1, r2, r3 = _structural_from_auto(row)
            legacy_fb.append(False)
        else:
            r1, r2, r3 = _structural_from_legacy(row)
            legacy_fb.append(True)
        has_auto.append(ha)
        s1l.append(r1)
        s2l.append(r2)
        s3l.append(r3)
        l3_empty = r3 is None
        l3_raw_empty.append(l3_empty)

        c1, c2, c3 = _canonical_triplet(r1, r2, r3, v)
        c1s.append(c1)
        c2s.append(c2)
        c3s.append(c3)

        expected = _expected_display(c1, c2, c3, l3_empty)
        canon_disp.append(expected)

        disp = _display_source(row)
        disp_parts = _split_display_pipe(disp)
        exp_parts = _split_display_pipe(expected)
        match = bool(expected and disp) and disp_parts == exp_parts
        disp_match.append(match)

        unresolved.append(bool(c1 and c2 and c3 is None and l3_empty))

        nc = False
        for key in ("displayLabel", "cellType"):
            if key not in df.columns:
                continue
            t = _cell_str(row.get(key))
            if not t:
                continue
            if _forbidden_match(t, v):
                nc = True
                break
            parts_k = _split_display_pipe(t) if "|" in t else [t]
            for part in parts_k:
                if part and not _display_segment_is_canonical_spelling(part, v):
                    nc = True
                    break
            if nc:
                break
        if not nc:
            for key in ("lineage", "level2", "level3"):
                if key not in df.columns:
                    continue
                t = _cell_str(row.get(key))
                if t and _forbidden_match(t, v):
                    nc = True
                    break
        if ha and _zr_leak_in_display_when_auto(row, ha, v):
            nc = True
        noncanon.append(nc)

        fd = False
        if "lineage" in df.columns and c1:
            lg = canonicalize_label(_cell_str(row.get("lineage")), v)
            if lg is not None and lg != c1:
                fd = True
        if "level2" in df.columns and c2:
            l2c = canonicalize_label(_cell_str(row.get("level2")), v)
            if l2c is not None and l2c != c2:
                fd = True
        if "level3" in df.columns and c3:
            l3c = canonicalize_label(_cell_str(row.get("level3")), v)
            if l3c is not None and l3c != c3:
                fd = True
        disagree.append(fd)

    df["has_auto_hierarchy"] = has_auto
    df["structural_l1_final"] = s1l
    df["structural_l2_final"] = s2l
    df["structural_l3_final"] = s3l
    df["structural_l1_canonical"] = c1s
    df["structural_l2_canonical"] = c2s
    df["structural_l3_canonical"] = c3s
    df["canonical_display_expected"] = canon_disp
    df["display_matches_canonical"] = disp_match
    df["is_unresolved_l3"] = unresolved
    df["legacy_fallback_used"] = legacy_fb
    df["noncanonical_token_flag"] = noncanon
    df["field_disagreement_flag"] = disagree
    return df


def _synonym_collision_counts(vocab: CanonicalVocabulary) -> tuple[int, int]:
    target_to_sources: dict[str, list[str]] = {}
    for raw_k, can in vocab.synonyms.items():
        target_to_sources.setdefault(can, []).append(raw_k)
    one_to_many = sum(1 for _t, srcs in target_to_sources.items() if len(srcs) >= 2)
    return one_to_many, len(target_to_sources)


def _many_to_one_raw_collisions(audit_df: pd.DataFrame) -> int:
    """Distinct raw display strings that map to the same canonical display expected."""
    if audit_df.empty or "canonical_display_expected" not in audit_df.columns:
        return 0
    raw_key: dict[str, set[str]] = {}
    for _, row in audit_df.iterrows():
        exp = _cell_str(row.get("canonical_display_expected"))
        raw_disp = _cell_str(row.get("displayLabel")) or _cell_str(row.get("final_display"))
        if not exp or not raw_disp:
            continue
        raw_key.setdefault(exp, set()).add(raw_disp)
    return sum(1 for _e, raws in raw_key.items() if len(raws) > 1)


def compute_annotation_metrics(
    audit_df: pd.DataFrame,
    *,
    vocab: CanonicalVocabulary | None = None,
) -> dict[str, Any]:
    v = vocab or get_default_vocabulary()
    n = int(len(audit_df))
    otm, _ = _synonym_collision_counts(v)
    mto = _many_to_one_raw_collisions(audit_df)
    if n == 0:
        return {
            "n_cells": 0,
            "field_agreement_rate_l1": 0.0,
            "field_agreement_rate_l2": 0.0,
            "field_agreement_rate_l3": 0.0,
            "display_agreement_rate": 0.0,
            "noncanonical_display_rate": 0.0,
            "unresolved_l3_rate": 0.0,
            "legacy_drift_rate": 0.0,
            "one_to_many_mapping_count": otm,
            "many_to_one_collision_count": mto,
        }

    def _field_rate(col: str, structural: str) -> float:
        if col not in audit_df.columns or structural not in audit_df.columns:
            return 0.0
        base = audit_df[col].map(_cell_str).notna()
        if not bool(base.any()):
            return 0.0
        ok = []
        for _, row in audit_df.loc[base].iterrows():
            obs_c = canonicalize_label(_cell_str(row.get(col)), v)
            want = row.get(structural)
            ok.append(obs_c is not None and want is not None and obs_c == want)
        return float(sum(ok) / len(ok)) if ok else 0.0

    disp_ok = audit_df["display_matches_canonical"]
    noncanon = audit_df["noncanonical_token_flag"]
    unres = audit_df["is_unresolved_l3"]
    legacy = audit_df["legacy_fallback_used"]
    drift_mask = legacy & (~disp_ok | audit_df["field_disagreement_flag"])

    return {
        "n_cells": n,
        "field_agreement_rate_l1": _field_rate("lineage", "structural_l1_canonical"),
        "field_agreement_rate_l2": _field_rate("level2", "structural_l2_canonical"),
        "field_agreement_rate_l3": _field_rate("level3", "structural_l3_canonical"),
        "display_agreement_rate": float(disp_ok.mean()) if n else 0.0,
        "noncanonical_display_rate": float(noncanon.mean()) if n else 0.0,
        "unresolved_l3_rate": float(unres.mean()) if n else 0.0,
        "legacy_drift_rate": float(drift_mask.mean()) if n else 0.0,
        "one_to_many_mapping_count": otm,
        "many_to_one_collision_count": mto,
    }


def summarize_structural_by_lineage(audit_df: pd.DataFrame) -> pd.DataFrame:
    """
    One row per canonical structural L1: fill rates, unresolved L3, explorer-style non-informative L3.

    Uses columns produced by :func:`build_annotation_audit_table`. Empty/missing L1 is bucketed as
    ``〈empty〉`` so every cell is counted.
    """
    from methods.annotation.hierarchy_columns import level3_non_informative

    required = ("structural_l1_canonical", "structural_l2_final", "structural_l3_final")
    if audit_df.empty or any(c not in audit_df.columns for c in required):
        return pd.DataFrame(
            columns=[
                "structural_l1_canonical",
                "n_cells",
                "pct_nonempty_l2",
                "pct_nonempty_l3",
                "pct_unresolved_l3",
                "pct_display_matches_canonical",
                "pct_noninformative_l3_given_nonempty_l3",
            ]
        )

    l1_key = audit_df["structural_l1_canonical"].map(lambda x: _cell_str(x) or "〈empty〉")
    l2_ok = audit_df["structural_l2_final"].map(lambda x: _cell_str(x) is not None)
    l3_ok = audit_df["structural_l3_final"].map(lambda x: _cell_str(x) is not None)
    l3_noninfo = audit_df["structural_l3_final"].map(
        lambda x: (_cell_str(x) is not None) and level3_non_informative(str(_cell_str(x)))
    )
    unres = (
        audit_df["is_unresolved_l3"].astype(bool)
        if "is_unresolved_l3" in audit_df.columns
        else pd.Series([False] * len(audit_df), index=audit_df.index)
    )
    disp_ok = (
        audit_df["display_matches_canonical"].astype(bool)
        if "display_matches_canonical" in audit_df.columns
        else pd.Series([False] * len(audit_df), index=audit_df.index)
    )

    work = pd.DataFrame(
        {
            "_l1": l1_key,
            "_l2_ok": l2_ok,
            "_l3_ok": l3_ok,
            "_l3_noninfo": l3_noninfo,
            "_unres": unres,
            "_disp_ok": disp_ok,
        },
        index=audit_df.index,
    )

    rows: list[dict[str, Any]] = []
    for name, sub in work.groupby("_l1", sort=True):
        n = int(len(sub))
        ne2 = int(sub["_l2_ok"].sum())
        ne3 = int(sub["_l3_ok"].sum())
        noninfo_among_ne3 = int(sub.loc[sub["_l3_ok"], "_l3_noninfo"].sum()) if ne3 else 0
        rows.append(
            {
                "structural_l1_canonical": str(name),
                "n_cells": n,
                "pct_nonempty_l2": round(100.0 * ne2 / n, 2) if n else 0.0,
                "pct_nonempty_l3": round(100.0 * ne3 / n, 2) if n else 0.0,
                "pct_unresolved_l3": round(100.0 * int(sub["_unres"].sum()) / n, 2) if n else 0.0,
                "pct_display_matches_canonical": round(100.0 * int(sub["_disp_ok"].sum()) / n, 2)
                if n
                else 0.0,
                "pct_noninformative_l3_given_nonempty_l3": round(
                    100.0 * noninfo_among_ne3 / ne3, 2
                )
                if ne3
                else 0.0,
            }
        )

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("n_cells", ascending=False).reset_index(drop=True)
    return out


def export_annotation_audit_reports(audit_df: pd.DataFrame, outdir: str) -> None:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    audit_df.to_parquet(out / "annotation_audit_cells.parquet")

    inv_rows: list[dict[str, Any]] = []
    inv_cols = [
        c
        for c in (
            "structural_l1_final",
            "structural_l2_final",
            "structural_l3_final",
            "structural_l1_canonical",
            "structural_l2_canonical",
            "structural_l3_canonical",
            "lineage",
            "level2",
            "level3",
            "displayLabel",
            "final_display",
            "cellType",
            "auto_level1",
            "auto_level2",
            "auto_level3",
            "zr_level1",
            "zr_level2",
            "zr_level3",
        )
        if c in audit_df.columns
    ]
    for col in inv_cols:
        vc = audit_df[col].dropna().astype(str).value_counts()
        for val, cnt in vc.items():
            inv_rows.append({"column": col, "value": val, "count": int(cnt)})
    pd.DataFrame(inv_rows).to_csv(out / "annotation_label_inventory.csv", index=False)

    dis = audit_df[audit_df["field_disagreement_flag"] | (~audit_df["display_matches_canonical"])]
    dis.to_csv(out / "annotation_disagreements.csv", index=False)

    audit_df[audit_df["noncanonical_token_flag"]].to_csv(
        out / "annotation_noncanonical_labels.csv", index=False
    )

    if "is_unresolved_l3" in audit_df.columns:
        g = (
            audit_df[audit_df["is_unresolved_l3"]]
            .groupby(["structural_l1_canonical", "structural_l2_canonical"], dropna=False)
            .size()
            .reset_index(name="n_cells")
        )
        g.to_csv(out / "annotation_unresolved_summary.csv", index=False)
    else:
        pd.DataFrame(
            columns=["structural_l1_canonical", "structural_l2_canonical", "n_cells"]
        ).to_csv(out / "annotation_unresolved_summary.csv", index=False)

    summarize_structural_by_lineage(audit_df).to_csv(
        out / "structural_lineage_summary.csv", index=False
    )


def iter_explorer_user_facing_strings(payload: dict[str, Any]) -> Iterator[str]:
    """
    Yield primary explorer display strings (headline / summary coloring).

    Per-cell ``lineage`` / ``level2`` / ``level3`` are omitted here: they may still
    reflect raw obs columns on legacy artifacts while ``displayLabel`` / ``cellType``
    stay canonical.
    """
    for row in payload.get("metadata") or []:
        if not isinstance(row, dict):
            continue
        for k in ("displayLabel", "cellType"):
            v = row.get(k)
            if v is not None and str(v).strip():
                yield str(v).strip()
    for s in payload.get("cluster_summaries") or []:
        if not isinstance(s, dict):
            continue
        lab = s.get("label")
        if lab:
            yield str(lab).strip()
        sec = s.get("display_label_secondary")
        if sec:
            yield str(sec).strip()
    # Omit ``filter_values`` here: they include sample IDs, conditions, cluster ids, etc.

    for entry in (payload.get("overview") or {}).get("top_cell_types") or []:
        if isinstance(entry, dict) and entry.get("label"):
            yield str(entry["label"]).strip()


def explorer_payload_audit_flags(
    payload: dict[str, Any],
    *,
    vocab: CanonicalVocabulary | None = None,
    has_auto_hierarchy: bool,
) -> dict[str, Any]:
    """
    Summarize canonical / forbidden-token checks for a RunExplorerService-style payload.

    ``has_auto_hierarchy`` should reflect the artifact (True for modern auto_level* runs).
    """
    v = vocab or get_default_vocabulary()
    texts = list(iter_explorer_user_facing_strings(payload))
    zr_hits = [t for t in texts if re.search(r"_zr\b", t) or "_zr" in t]
    snake_patterns = [pat for pid, pat in v.forbidden_patterns if pid == "snake_case_token"]
    snake_hits = [t for t in texts if any(re.search(pat, t) for pat in snake_patterns)]

    def _segment_canonical(seg: str) -> bool:
        return bool(seg) and _display_segment_is_canonical_spelling(seg, v)

    def _segments_ok_for_modern() -> bool:
        if not has_auto_hierarchy:
            return True
        for t in texts:
            for seg in _split_display_pipe(t):
                if seg and not _segment_canonical(seg):
                    return False
        return True

    legacy_ok = True
    if not has_auto_hierarchy:
        for t in texts:
            if _forbidden_match(t, v):
                legacy_ok = False
                break
            for seg in _split_display_pipe(t):
                if seg and not _segment_canonical(seg):
                    legacy_ok = False
                    break
            if not legacy_ok:
                break

    return {
        "has_zr_in_user_facing": bool(zr_hits),
        "zr_hits": zr_hits,
        "snake_case_hits": snake_hits,
        "modern_segments_all_canonical": _segments_ok_for_modern(),
        "legacy_mapped_display_canonical": bool(legacy_ok),
        "n_strings_checked": len(texts),
    }


def modern_unresolved_cluster_label_parts(payload: dict[str, Any], cluster_id: str) -> list[str]:
    """Return pipe segments for a cluster summary label (for unresolved L1|L2 assertions)."""
    for s in payload.get("cluster_summaries") or []:
        if not isinstance(s, dict):
            continue
        if str(s.get("cluster_id")) != str(cluster_id):
            continue
        return _split_display_pipe(_cell_str(s.get("label")))
    return []


# --- AnnData / run artifact ingest -----------------------------------------


_OBS_COLUMN_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("annotation_label", ("annotation_label",)),
    ("auto_level1", ("auto_level1",)),
    ("auto_level2", ("auto_level2",)),
    ("auto_level3", ("auto_level3",)),
    ("level3_final_safe", ("level3_final_safe",)),
    ("zr_level1", ("zr_level1",)),
    ("zr_level2", ("zr_level2",)),
    ("zr_level3", ("zr_level3",)),
    ("zr_display", ("zr_display",)),
    ("final_display", ("final_display",)),
    ("lineage", ("lineage", "annotation_lineage")),
    ("level2", ("level2",)),
    ("level3", ("level3",)),
    ("displayLabel", ("displayLabel",)),
    ("cellType", ("cellType",)),
    ("rawAnnotationLabel", ("rawAnnotationLabel",)),
    ("globalCluster", ("globalCluster", "global_cluster")),
    ("sample_id", ("sample_id",)),
    ("sample", ("sample",)),
    ("condition", ("condition",)),
    ("timepoint", ("timepoint",)),
)


def cells_dataframe_from_anndata_obs(
    obs: pd.DataFrame,
    *,
    cluster_key: str = "leiden",
    max_cells: int | None = None,
    random_seed: int = 42,
) -> pd.DataFrame:
    """
    Project ``AnnData.obs`` onto columns expected by :func:`build_annotation_audit_table`.

    Uses ``cluster_key`` (default ``leiden``) for the ``cluster`` audit column when present.
    Optionally subsample rows for large artifacts.
    """
    idx = obs.index.to_numpy()
    if max_cells is not None and len(idx) > max_cells:
        rng = np.random.default_rng(random_seed)
        pick = rng.choice(len(idx), size=max_cells, replace=False)
        idx = idx[pick]
    sub = obs.loc[idx]

    out = pd.DataFrame()
    for dst, sources in _OBS_COLUMN_ALIASES:
        for src in sources:
            if src in sub.columns:
                out[dst] = sub[src].to_numpy()
                break

    cluster_candidates = (cluster_key, "leiden", "cluster", "cluster_id")
    ck = next((c for c in cluster_candidates if c in sub.columns), None)
    if ck is not None:
        out["cluster"] = sub[ck].to_numpy()

    return out.reset_index(drop=True)
