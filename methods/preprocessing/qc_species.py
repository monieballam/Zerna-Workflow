"""Species-aware QC gene matching (mitochondrial, ribosomal, hemoglobin, housekeeping).

Used by ``qc_filter`` so users do not need to configure raw gene prefixes in the dashboard.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default gene sets (symbols; matching is case-insensitive on var names)
# ---------------------------------------------------------------------------

DEFAULT_HB_GENES_HUMAN: tuple[str, ...] = (
    "HBA1",
    "HBA2",
    "HBB",
    "HBD",
    "HBM",
    "HBQ1",
    "HBZ",
)

DEFAULT_HB_GENES_MOUSE: tuple[str, ...] = (
    "Hba-a1",
    "Hba-a2",
    "Hbb-bs",
    "Hbb-bt",
    "Hbq1a",
    "Hbq1b",
)

DEFAULT_HK_GENES_HUMAN: tuple[str, ...] = ("MALAT1", "NEAT1")
DEFAULT_HK_GENES_MOUSE: tuple[str, ...] = ("Malat1", "Neat1")

# RPS/RPL prefixes work for both species when matching uppercased names
DEFAULT_RIBO_PREFIXES: tuple[str, ...] = ("RPS", "RPL")


def infer_species_from_var_names(var_names: Sequence[str]) -> tuple[str, dict[str, Any]]:
    """Return ``(effective_species, inference_meta)`` with ``effective_species`` in ``human`` | ``mouse``.

    Heuristics: MT- vs mt-/Mt- mitochondrial style; human hemoglobin symbols; Gm-prefixed IDs (mouse).
    On ambiguity or no signal, defaults to ``human`` and sets ``ambiguous`` with a warning message.
    """
    names = [str(x).strip() for x in var_names if str(x).strip()]
    n = len(names)
    if n == 0:
        meta: dict[str, Any] = {
            "ambiguous": True,
            "warning": "No gene symbols in var_names; defaulting QC species to human.",
            "score_human": 0,
            "score_mouse": 0,
        }
        return "human", meta

    mt_upper = sum(1 for g in names if g.startswith("MT-"))
    mt_lower = sum(1 for g in names if g.startswith("mt-") or g.startswith("Mt-"))
    hb_human_hits = sum(
        1 for g in names if g.upper() in {x.upper() for x in DEFAULT_HB_GENES_HUMAN}
    )
    hb_mouse_hits = sum(
        1
        for g in names
        if g in set(DEFAULT_HB_GENES_MOUSE)
        or g.upper() in {x.upper() for x in DEFAULT_HB_GENES_MOUSE}
    )
    gm_like = sum(1 for g in names if re.match(r"^Gm\d+", g) is not None)
    title_like = sum(
        1
        for g in names
        if len(g) > 3 and g[0].isupper() and g[1:].lower() == g[1:] and g[1].islower()
    )

    score_human = mt_upper * 3 + hb_human_hits * 6 + hb_mouse_hits * 0
    score_mouse = mt_lower * 4 + gm_like * 2 + title_like * 0.05 + hb_mouse_hits * 6

    ambiguous = False
    warning: str | None = None
    if score_human >= score_mouse * 1.35 and (score_human >= 3 or mt_upper >= 3):
        eff = "human"
    elif score_mouse > score_human * 1.35 and (score_mouse >= 3 or mt_lower >= 3):
        eff = "mouse"
    elif (
        mt_upper == 0
        and mt_lower == 0
        and hb_human_hits == 0
        and hb_mouse_hits == 0
        and gm_like == 0
    ):
        ambiguous = True
        eff = "human"
        warning = (
            "Could not infer species from gene symbols (no clear mito/HB/Gm signal); "
            "defaulting QC species to human. Set QC species explicitly if needed."
        )
    else:
        ambiguous = True
        eff = "human" if score_human >= score_mouse else "mouse"
        warning = (
            f"Species autodetect was ambiguous (human_score={score_human:.2f}, mouse_score={score_mouse:.2f}); "
            f"chose {eff}. Set QC species explicitly if this is wrong."
        )

    if ambiguous and warning:
        logger.warning("Zerna QC species inference: %s", warning)

    meta = {
        "ambiguous": ambiguous,
        "warning": warning,
        "score_human": float(score_human),
        "score_mouse": float(score_mouse),
        "mt_upper_style_count": mt_upper,
        "mt_lower_style_count": mt_lower,
        "hb_human_hits": hb_human_hits,
        "hb_mouse_hits": hb_mouse_hits,
        "gm_like_count": gm_like,
    }
    return eff, meta


def resolve_effective_species(
    species_request: str, var_names: Sequence[str]
) -> tuple[str, dict[str, Any]]:
    """Normalize request (auto/human/mouse) and run autodetect when ``auto``."""
    req = str(species_request or "auto").strip().lower()
    if req not in ("auto", "human", "mouse"):
        req = "auto"
    if req == "human":
        return "human", {"mode": "explicit", "ambiguous": False, "warning": None}
    if req == "mouse":
        return "mouse", {"mode": "explicit", "ambiguous": False, "warning": None}
    eff, inf = infer_species_from_var_names(var_names)
    inf["mode"] = "auto"
    return eff, inf


def mito_gene_mask(
    var_names: pd.Index | Sequence[str], *, species_effective: str, legacy_mito_prefix: str | None
) -> np.ndarray:
    """Boolean mask over genes: mitochondrial.

    If ``legacy_mito_prefix`` is a non-empty string, use only that single prefix (uppercase match).
    Otherwise use species-aware rules: human → ``MT-``; mouse → ``mt-``, ``Mt-``, and ``MT-``.
    """
    s = pd.Index(np.asarray(var_names, dtype=object).astype(str))
    u = s.str.upper()
    legacy = str(legacy_mito_prefix).strip() if legacy_mito_prefix is not None else ""
    if legacy:
        mp = legacy.upper()
        return np.asarray(u.str.startswith(mp), dtype=bool)

    if species_effective == "mouse":
        m = s.str.startswith("mt-") | s.str.startswith("Mt-") | u.str.startswith("MT-")
        return np.asarray(m, dtype=bool)

    # human: GENCODE / 10x-style ``MT-`` prefix (case-sensitive on the symbol, not uppercased matching)
    return np.asarray(s.str.startswith("MT-"), dtype=bool)


def default_hb_gene_list(species_effective: str) -> list[str]:
    return list(DEFAULT_HB_GENES_MOUSE if species_effective == "mouse" else DEFAULT_HB_GENES_HUMAN)


def default_hk_gene_list(species_effective: str) -> list[str]:
    return list(DEFAULT_HK_GENES_MOUSE if species_effective == "mouse" else DEFAULT_HK_GENES_HUMAN)


def default_ribo_prefixes(_species_effective: str) -> list[str]:
    """Ribosomal prefixes; uppercased during matching — works for human and mouse symbols."""
    return list(DEFAULT_RIBO_PREFIXES)


def build_gene_matching_report(
    *,
    species_request: str,
    species_effective: str,
    species_inference: dict[str, Any],
    legacy_mito_prefix: str | None,
    ribo_prefixes: list[str],
    hb_gene_names: list[str] | None,
    hk_gene_names: list[str] | None,
) -> dict[str, Any]:
    return {
        "species_request": species_request,
        "species_effective": species_effective,
        "species_inference": species_inference,
        "mito": (
            {"mode": "legacy_single_prefix", "prefix": legacy_mito_prefix}
            if legacy_mito_prefix
            else {"mode": "species_aware", "species": species_effective}
        ),
        "ribo_prefixes": list(ribo_prefixes),
        "hb_genes": list(hb_gene_names) if hb_gene_names else [],
        "hk_genes": list(hk_gene_names) if hk_gene_names else [],
    }
