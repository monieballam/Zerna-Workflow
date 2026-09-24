"""Unit tests for annotation vocabulary audit helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from apps.api.services.annotation_audit import (
    build_annotation_audit_table,
    canonicalize_label,
    cells_dataframe_from_anndata_obs,
    compute_annotation_metrics,
    export_annotation_audit_reports,
    load_canonical_vocabulary,
    summarize_structural_by_lineage,
)


@pytest.fixture
def vocab():
    return load_canonical_vocabulary()


def test_canonicalize_synonym_and_allowlist(vocab):
    assert canonicalize_label("Lymphoid", vocab) == "Immune"
    assert canonicalize_label("CD8 eff", vocab) == "CD8"
    assert canonicalize_label("Immune", vocab) == "Immune"
    assert canonicalize_label("unknown_token_xyz", vocab) is None


def test_modern_display_matches_structural(vocab):
    df = pd.DataFrame(
        {
            "auto_level1": ["Immune", "Immune"],
            "auto_level2": ["T cells", "T cells"],
            "auto_level3": ["CD4", "CD8"],
            "final_display": ["Immune | T cells | CD4", "Immune | T cells | CD8"],
            "displayLabel": ["Immune | T cells | CD4", "Immune | T cells | CD8"],
            "lineage": ["Immune", "Immune"],
            "level2": ["T cells", "T cells"],
            "level3": ["CD4", "CD8"],
        }
    )
    out = build_annotation_audit_table(df, vocab=vocab)
    assert out["display_matches_canonical"].all()
    assert not out["noncanonical_token_flag"].any()
    assert not out["legacy_fallback_used"].any()
    m = compute_annotation_metrics(out, vocab=vocab)
    assert m["display_agreement_rate"] == 1.0
    assert m["field_agreement_rate_l1"] == 1.0


def test_cd8_eff_spelling_in_display_is_noncanonical(vocab):
    df = pd.DataFrame(
        {
            "auto_level1": ["Immune"],
            "auto_level2": ["T cells"],
            "auto_level3": ["CD8"],
            "final_display": ["Immune | T cells | CD8 eff"],
            "displayLabel": ["Immune | T cells | CD8 eff"],
        }
    )
    out = build_annotation_audit_table(df, vocab=vocab)
    assert out["noncanonical_token_flag"].iloc[0]


def test_modern_zr_token_in_display_is_noncanonical(vocab):
    df = pd.DataFrame(
        {
            "auto_level1": ["Immune"],
            "auto_level2": ["T cells"],
            "auto_level3": ["CD4"],
            "zr_level2": ["t_cell_zr"],
            "final_display": ["Immune | t_cell_zr | CD4"],
            "displayLabel": ["Immune | t_cell_zr | CD4"],
            "cellType": ["Immune | t_cell_zr | CD4"],
        }
    )
    out = build_annotation_audit_table(df, vocab=vocab)
    assert out["noncanonical_token_flag"].iloc[0]
    assert not out["display_matches_canonical"].iloc[0]


def test_legacy_synonym_mapping(vocab):
    df = pd.DataFrame(
        {
            "lineage": ["Lymphoid", "Lymphoid"],
            "zr_level2": ["t_cell_zr", "b_cell_zr"],
            "level3_final_safe": ["CD8 eff", "B mem"],
            "final_display": [
                "Immune | T cells | CD8",
                "Immune | B cells | Memory B",
            ],
            "displayLabel": [
                "Immune | T cells | CD8",
                "Immune | B cells | Memory B",
            ],
        }
    )
    out = build_annotation_audit_table(df, vocab=vocab)
    assert out["legacy_fallback_used"].all()
    assert out["display_matches_canonical"].all()
    assert out["structural_l1_canonical"].tolist() == ["Immune", "Immune"]
    assert out["structural_l2_canonical"].tolist() == ["T cells", "B cells"]


def test_unresolved_l3_allowed(vocab):
    df = pd.DataFrame(
        {
            "auto_level1": ["Immune"],
            "auto_level2": ["T cells"],
            "auto_level3": [""],
            "final_display": ["Immune | T cells"],
            "displayLabel": ["Immune | T cells"],
        }
    )
    out = build_annotation_audit_table(df, vocab=vocab)
    assert out["is_unresolved_l3"].iloc[0]
    assert out["canonical_display_expected"].iloc[0] == "Immune | T cells"
    assert out["display_matches_canonical"].iloc[0]


def test_forbidden_snake_case_in_user_fields(vocab):
    df = pd.DataFrame(
        {
            "lineage": ["Lymphoid"],
            "zr_level2": ["t_cell_zr"],
            "level3_final_safe": ["CD8"],
            "final_display": ["Immune | T cells | CD8"],
            "displayLabel": ["Immune | T cells | CD8"],
            "cellType": ["some_snake_case_bad"],
        }
    )
    out = build_annotation_audit_table(df, vocab=vocab)
    assert out["noncanonical_token_flag"].iloc[0]


def test_field_disagreement(vocab):
    df = pd.DataFrame(
        {
            "auto_level1": ["Immune"],
            "auto_level2": ["T cells"],
            "auto_level3": ["CD4"],
            "lineage": ["Stromal"],
            "final_display": ["Immune | T cells | CD4"],
            "displayLabel": ["Immune | T cells | CD4"],
            "level2": ["T cells"],
            "level3": ["CD4"],
        }
    )
    out = build_annotation_audit_table(df, vocab=vocab)
    assert out["field_disagreement_flag"].iloc[0]


def test_many_to_one_raw_collision_metric(vocab):
    df = pd.DataFrame(
        {
            "auto_level1": ["Immune", "Immune"],
            "auto_level2": ["T cells", "T cells"],
            "auto_level3": ["CD4", "CD4"],
            "final_display": ["Immune | T cells | CD4", "Immune | T cells | CD4"],
            "displayLabel": ["Immune | T cells | CD4", "Immune|T cells|CD4"],
        }
    )
    out = build_annotation_audit_table(df, vocab=vocab)
    m = compute_annotation_metrics(out, vocab=vocab)
    assert m["many_to_one_collision_count"] >= 1


def test_one_to_many_synonym_mapping_count(vocab):
    m = compute_annotation_metrics(pd.DataFrame(), vocab=vocab)
    assert m["one_to_many_mapping_count"] >= 1


def test_cells_dataframe_from_anndata_obs_maps_lineage_alias(vocab):
    obs = pd.DataFrame(
        {
            "annotation_lineage": ["Immune"],
            "leiden": ["0"],
            "auto_level1": ["Immune"],
            "auto_level2": ["T cells"],
            "auto_level3": ["CD4"],
            "final_display": ["Immune | T cells | CD4"],
        }
    )
    cells = cells_dataframe_from_anndata_obs(obs, cluster_key="leiden")
    assert cells["lineage"].iloc[0] == "Immune"
    assert cells["cluster"].iloc[0] == "0"
    audit = build_annotation_audit_table(cells, vocab=vocab)
    assert audit["display_matches_canonical"].iloc[0]


def test_export_annotation_audit_reports(tmp_path: Path, vocab):
    df = pd.DataFrame(
        {
            "auto_level1": ["Immune"],
            "auto_level2": ["T cells"],
            "auto_level3": ["CD4"],
            "final_display": ["Immune | T cells | CD4"],
            "displayLabel": ["Immune | T cells | CD4"],
        }
    )
    out = build_annotation_audit_table(df, vocab=vocab)
    export_annotation_audit_reports(out, str(tmp_path))
    assert (tmp_path / "annotation_audit_cells.parquet").is_file()
    assert (tmp_path / "annotation_label_inventory.csv").is_file()
    assert (tmp_path / "annotation_disagreements.csv").is_file()
    assert (tmp_path / "annotation_noncanonical_labels.csv").is_file()
    assert (tmp_path / "annotation_unresolved_summary.csv").is_file()
    assert (tmp_path / "structural_lineage_summary.csv").is_file()


def test_summarize_structural_by_lineage_all_lineages(vocab):
    df = pd.DataFrame(
        {
            "auto_level1": ["Immune", "Stromal"],
            "auto_level2": ["T cells", "Fibroblasts"],
            "auto_level3": ["CD4", "CAF_Unknown"],
            "final_display": [
                "Immune | T cells | CD4",
                "Stromal | Fibroblasts | CAF_Unknown",
            ],
            "displayLabel": [
                "Immune | T cells | CD4",
                "Stromal | Fibroblasts | CAF_Unknown",
            ],
        }
    )
    audit = build_annotation_audit_table(df, vocab=vocab)
    s = summarize_structural_by_lineage(audit)
    assert len(s) == 2
    assert set(s["structural_l1_canonical"]) == {"Immune", "Stromal"}
    stromal_row = s[s["structural_l1_canonical"] == "Stromal"].iloc[0]
    assert int(stromal_row["n_cells"]) == 1
    assert float(stromal_row["pct_nonempty_l3"]) == 100.0
    assert float(stromal_row["pct_noninformative_l3_given_nonempty_l3"]) == 100.0
