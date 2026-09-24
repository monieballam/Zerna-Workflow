"""Tests for support-marker key selection vs explorer hierarchy headlines."""

from __future__ import annotations

from methods.annotation.explorer_annotation_evidence import (
    hierarchy_display_key_candidates,
    pick_support_markers_for_display_headline,
)


def test_hierarchy_candidates_finest_first() -> None:
    assert hierarchy_display_key_candidates("Immune | T cells | CD8") == [
        "CD8",
        "T cells",
        "Immune",
        "Immune | T cells | CD8",
    ]


def test_pick_prefers_finest_segment_key() -> None:
    ann = {
        "supporting_markers": {
            "CD8": ["GZMB", "PRF1"],
            "T cells": ["CD3D"],
        },
        "top_cell_types": [],
    }
    m, k, aligned = pick_support_markers_for_display_headline(ann, "Immune | T cells | CD8")
    assert k == "CD8"
    assert "GZMB" in m
    assert aligned is True


def test_pick_no_arbitrary_unrelated_pack_row() -> None:
    ann = {
        "normalized_label": "Something else",
        "supporting_markers": {"Unrelated": ["X"]},
        "top_cell_types": [],
    }
    m, k, aligned = pick_support_markers_for_display_headline(ann, "Immune | T cells | CD8")
    assert m == []
    assert k is None
    assert aligned is False


def test_pick_coarser_row_when_fine_missing_aligned_false() -> None:
    ann = {
        "supporting_markers": {"T cells": ["CD3D", "CD2"]},
        "top_cell_types": [],
    }
    m, k, aligned = pick_support_markers_for_display_headline(ann, "Immune | T cells | CD8")
    assert k == "T cells"
    assert m
    assert aligned is False
