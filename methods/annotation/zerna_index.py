"""Zerna label index: cross-ontology cell type label mapping.

# Feature: gap-analysis-and-verification

Maps labels across Cell Ontology (CL), common aliases, and project-specific
naming conventions.  Returns canonical label, ontology ID, aliases, and
hierarchy path for any known label.

**Validates: Requirements 22.1, 22.2**
"""

from __future__ import annotations

import logging
from typing import Any

from zerna_contracts.base import ZernaBaseModel
from pydantic import Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ZernaEntry(ZernaBaseModel):
    """A single entry in the Zerna label index."""

    canonical_label: str = Field(description="Canonical cell type name")
    ontology_id: str = Field(description="Cell Ontology ID (CL:XXXXXXX)")
    aliases: list[str] = Field(description="Known aliases for this cell type")
    hierarchy_path: list[str] = Field(description="Hierarchy from root to leaf")


# ---------------------------------------------------------------------------
# Predefined cell type entries
# ---------------------------------------------------------------------------

_ZERNA_ENTRIES: list[dict[str, Any]] = [
    {
        "canonical_label": "T cell",
        "ontology_id": "CL:0000084",
        "aliases": ["T lymphocyte", "T-cell", "Tcell"],
        "hierarchy_path": ["Hematopoietic cell", "Lymphocyte", "T cell"],
    },
    {
        "canonical_label": "B cell",
        "ontology_id": "CL:0000236",
        "aliases": ["B lymphocyte", "B-cell", "Bcell"],
        "hierarchy_path": ["Hematopoietic cell", "Lymphocyte", "B cell"],
    },
    {
        "canonical_label": "NK cell",
        "ontology_id": "CL:0000623",
        "aliases": ["Natural killer cell", "NK-cell", "NKcell"],
        "hierarchy_path": ["Hematopoietic cell", "Lymphocyte", "NK cell"],
    },
    {
        "canonical_label": "Monocyte",
        "ontology_id": "CL:0000576",
        "aliases": ["Mono", "monocyte"],
        "hierarchy_path": ["Hematopoietic cell", "Myeloid cell", "Monocyte"],
    },
    {
        "canonical_label": "Macrophage",
        "ontology_id": "CL:0000235",
        "aliases": ["Macro", "macrophage", "MΦ"],
        "hierarchy_path": ["Hematopoietic cell", "Myeloid cell", "Macrophage"],
    },
    {
        "canonical_label": "Dendritic cell",
        "ontology_id": "CL:0000451",
        "aliases": ["DC", "dendritic cell", "Dendritic"],
        "hierarchy_path": ["Hematopoietic cell", "Myeloid cell", "Dendritic cell"],
    },
    {
        "canonical_label": "Neutrophil",
        "ontology_id": "CL:0000775",
        "aliases": ["Neut", "neutrophil", "PMN"],
        "hierarchy_path": ["Hematopoietic cell", "Myeloid cell", "Neutrophil"],
    },
    {
        "canonical_label": "Fibroblast",
        "ontology_id": "CL:0000057",
        "aliases": ["Fibro", "fibroblast", "CAF"],
        "hierarchy_path": ["Stromal cell", "Fibroblast"],
    },
    {
        "canonical_label": "Endothelial cell",
        "ontology_id": "CL:0000115",
        "aliases": ["Endothelial", "EC", "endothelial"],
        "hierarchy_path": ["Stromal cell", "Endothelial cell"],
    },
    {
        "canonical_label": "Epithelial cell",
        "ontology_id": "CL:0000066",
        "aliases": ["Epithelial", "epithelial cell", "Epi"],
        "hierarchy_path": ["Epithelial cell"],
    },
    {
        "canonical_label": "Pericyte",
        "ontology_id": "CL:0000669",
        "aliases": ["pericyte", "Mural cell"],
        "hierarchy_path": ["Stromal cell", "Pericyte"],
    },
    {
        "canonical_label": "Smooth muscle cell",
        "ontology_id": "CL:0000192",
        "aliases": ["SMC", "smooth muscle", "Smooth Muscle Cell"],
        "hierarchy_path": ["Stromal cell", "Smooth muscle cell"],
    },
    {
        "canonical_label": "Mast cell",
        "ontology_id": "CL:0000097",
        "aliases": ["Mast", "mast cell", "Mastocyte"],
        "hierarchy_path": ["Hematopoietic cell", "Myeloid cell", "Mast cell"],
    },
    {
        "canonical_label": "Plasma cell",
        "ontology_id": "CL:0000786",
        "aliases": ["Plasma", "plasma cell", "Plasmacyte"],
        "hierarchy_path": ["Hematopoietic cell", "Lymphocyte", "B cell", "Plasma cell"],
    },
    {
        "canonical_label": "CD4-positive T cell",
        "ontology_id": "CL:0000624",
        "aliases": ["CD4 T cell", "CD4+ T cell", "Helper T cell", "Th cell"],
        "hierarchy_path": ["Hematopoietic cell", "Lymphocyte", "T cell", "CD4-positive T cell"],
    },
    {
        "canonical_label": "CD8-positive T cell",
        "ontology_id": "CL:0000625",
        "aliases": ["CD8 T cell", "CD8+ T cell", "Cytotoxic T cell", "CTL"],
        "hierarchy_path": ["Hematopoietic cell", "Lymphocyte", "T cell", "CD8-positive T cell"],
    },
    {
        "canonical_label": "Regulatory T cell",
        "ontology_id": "CL:0000815",
        "aliases": ["Treg", "T reg", "regulatory T cell"],
        "hierarchy_path": [
            "Hematopoietic cell",
            "Lymphocyte",
            "T cell",
            "CD4-positive T cell",
            "Regulatory T cell",
        ],
    },
]


# ---------------------------------------------------------------------------
# Index construction
# ---------------------------------------------------------------------------


class ZernaLabelIndex:
    """In-memory index for cross-ontology cell type label lookup.

    Builds a case-insensitive mapping from canonical labels and all aliases
    to their corresponding ``ZernaEntry``.
    """

    def __init__(self, entries: list[ZernaEntry] | None = None) -> None:
        self._entries: list[ZernaEntry] = entries or self._default_entries()
        self._index: dict[str, ZernaEntry] = {}
        self._build_index()

    # -- construction helpers ------------------------------------------------

    @staticmethod
    def _default_entries() -> list[ZernaEntry]:
        """Build ``ZernaEntry`` objects from the predefined data."""
        return [ZernaEntry(**e) for e in _ZERNA_ENTRIES]

    def _build_index(self) -> None:
        """Populate the case-insensitive lookup index."""
        for entry in self._entries:
            key = entry.canonical_label.lower()
            self._index[key] = entry
            for alias in entry.aliases:
                alias_key = alias.lower()
                # Canonical label takes precedence if there's a collision
                if alias_key not in self._index:
                    self._index[alias_key] = entry

    # -- public API ----------------------------------------------------------

    @property
    def entries(self) -> list[ZernaEntry]:
        """All entries in the index."""
        return list(self._entries)

    def lookup(self, label: str) -> ZernaEntry | None:
        """Look up a cell type label (case-insensitive).

        Works with canonical labels *and* aliases.

        Args:
            label: The cell type label to look up.

        Returns:
            The matching ``ZernaEntry``, or ``None`` if not found.
        """
        return self._index.get(label.lower())

    def harmonize(self, labels: list[str]) -> list[ZernaEntry | None]:
        """Look up multiple labels and return their entries.

        Args:
            labels: List of cell type labels to harmonize.

        Returns:
            List of ``ZernaEntry`` (or ``None`` for unrecognised labels),
            in the same order as the input.
        """
        return [self.lookup(label) for label in labels]


# ---------------------------------------------------------------------------
# Module-level convenience instance
# ---------------------------------------------------------------------------

_default_index: ZernaLabelIndex | None = None


def get_default_index() -> ZernaLabelIndex:
    """Return (and lazily create) the default Zerna label index."""
    global _default_index  # noqa: PLW0603
    if _default_index is None:
        _default_index = ZernaLabelIndex()
    return _default_index


def lookup(label: str) -> ZernaEntry | None:
    """Convenience wrapper around the default index's ``lookup``."""
    return get_default_index().lookup(label)


def harmonize(labels: list[str]) -> list[ZernaEntry | None]:
    """Convenience wrapper around the default index's ``harmonize``."""
    return get_default_index().harmonize(labels)
