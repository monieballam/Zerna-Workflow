"""Unit tests for species-aware QC gene matching helpers."""

import pandas as pd

from methods.preprocessing.qc_species import (
    infer_species_from_var_names,
    mito_gene_mask,
    resolve_effective_species,
)


def test_infer_human_from_mt_prefix_style():
    names = ["MT-ND1", "MT-CO1", "CD3D", "CD8A"]
    eff, meta = infer_species_from_var_names(names)
    assert eff == "human"
    assert meta.get("ambiguous") is False


def test_infer_mouse_from_lowercase_mt():
    names = [f"mt-gene-{i}" for i in range(12)] + ["Cd3d", "Malat1", "Cd8a"]
    eff, meta = infer_species_from_var_names(names)
    assert eff == "mouse"
    # Title-case symbols add a small human prior; strong mt- counts still resolve to mouse.
    assert meta.get("mt_lower_style_count", 0) >= 10


def test_infer_ambiguous_plain_symbols_defaults_human_with_flag():
    names = ["gene_a", "gene_b", "gene_c"]
    eff, meta = infer_species_from_var_names(names)
    assert eff == "human"
    assert meta.get("ambiguous") is True
    assert meta.get("warning")


def test_resolve_explicit_skips_inference():
    eff, meta = resolve_effective_species("mouse", ["MT-FOO"])
    assert eff == "mouse"
    assert meta.get("mode") == "explicit"


def test_mito_mask_human_vs_mouse():
    idx = pd.Index(["MT-ND1", "mt-nd1", "CD3D"])
    h = mito_gene_mask(idx, species_effective="human", legacy_mito_prefix=None)
    assert h.tolist() == [True, False, False]
    m = mito_gene_mask(idx, species_effective="mouse", legacy_mito_prefix=None)
    assert m.tolist() == [True, True, False]


def test_mito_mask_legacy_prefix_overrides_species():
    idx = pd.Index(["mt-foo", "MT-FOO", "other"])
    leg = mito_gene_mask(idx, species_effective="human", legacy_mito_prefix="mt-")
    assert leg.tolist() == [True, True, False]


def test_legacy_prefix_matches_uppercased_var_names():
    idx = pd.Index(["mt-1", "CD3D"])
    m = mito_gene_mask(idx, species_effective="human", legacy_mito_prefix="mt-")
    assert m.tolist() == [True, False]
    idx2 = pd.Index(["MT-ND1", "mt-nd2"])
    m2 = mito_gene_mask(idx2, species_effective="mouse", legacy_mito_prefix="MT-")
    assert m2.tolist() == [True, True]
