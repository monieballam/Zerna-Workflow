"""Helpers for resolving dataset species from gene naming conventions."""

from __future__ import annotations

from collections.abc import Iterable


def infer_species_from_var_names(var_names: Iterable[object], default: str = "human") -> str:
    """Infer whether gene symbols look human- or mouse-like.

    This is intentionally lightweight and only meant to catch the common
    10x-symbol cases:
    - human: ``CXCL13``, ``MT-ND1``
    - mouse: ``Cxcl13``, ``mt-Nd1``
    """

    human_like = 0
    mouse_like = 0

    for raw_gene in list(var_names)[:1000]:
        gene = str(raw_gene).strip()
        if not gene:
            continue

        if gene.startswith("ENSMUSG"):
            mouse_like += 1
            continue
        if gene.startswith("ENSG"):
            human_like += 1
            continue

        if gene.startswith("mt-") or gene.startswith("Mt-"):
            mouse_like += 1
            continue
        if gene.startswith("MT-"):
            human_like += 1
            continue

        alpha = [char for char in gene if char.isalpha()]
        if not alpha:
            continue

        if gene == gene.upper():
            human_like += 1
            continue

        if gene[0].isupper() and any(char.islower() for char in gene[1:]):
            mouse_like += 1

    if mouse_like >= 2 and mouse_like >= human_like * 2:
        return "mouse"
    if human_like >= 2 and human_like >= mouse_like * 2:
        return "human"
    return default


def resolve_species(requested_species: str | None, var_names: Iterable[object]) -> str:
    """Resolve the species, preserving explicit non-human requests."""

    normalized = str(requested_species or "").strip().lower()
    if normalized == "auto":
        normalized = ""
    if normalized == "mouse":
        return "mouse"
    if normalized not in {"", "human"}:
        return normalized
    return infer_species_from_var_names(var_names, default="human")
