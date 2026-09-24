"""Programs registry: cancer-type-specific analysis configuration catalog.

Catalogs cancer-type-specific configs (marker panels, hierarchy mappings,
default parameters).  Includes at least *general* and *prostate*-specific
configurations out of the box.

Interface
---------
- ``get_program(cancer_type) -> ProgramConfig``
- ``list_programs() -> list[ProgramConfig]``
"""

from __future__ import annotations

from typing import Any

from zerna_contracts.base import ZernaBaseModel

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class ProgramConfig(ZernaBaseModel):
    """A cancer-type-specific analysis configuration."""

    cancer_type: str
    marker_panels: dict[str, str]  # panel_name -> file_ref
    hierarchy_mappings: dict[str, str]  # mapping_name -> file_ref
    default_parameters: dict[str, Any]


# ---------------------------------------------------------------------------
# Built-in program configurations
# ---------------------------------------------------------------------------

_GENERAL_PROGRAM = ProgramConfig(
    cancer_type="general",
    marker_panels={
        "immune": "panels/general/immune_v1.yaml",
        "stromal": "panels/general/stromal_v1.yaml",
        "epithelial": "panels/general/epithelial_v1.yaml",
    },
    hierarchy_mappings={
        "L1_L2_L3": "hierarchies/general/l1_l2_l3.yaml",
    },
    default_parameters={
        "min_genes": 200,
        "min_cells": 3,
        "n_top_genes": 2000,
        "n_pcs": 30,
        "resolution": 1.0,
    },
)

_PROSTATE_PROGRAM = ProgramConfig(
    cancer_type="prostate",
    marker_panels={
        "immune": "panels/prostate/immune_v2.yaml",
        "stromal": "panels/prostate/stromal_v2.yaml",
        "epithelial": "panels/prostate/epithelial_prostate_v2.yaml",
        "luminal_PRAD": "panels/prostate/luminal_prad_v1.yaml",
        "NEPC": "panels/prostate/nepc_v1.yaml",
    },
    hierarchy_mappings={
        "L1_L2_L3": "hierarchies/prostate/l1_l2_l3.yaml",
        "myeloid": "hierarchies/prostate/myeloid.yaml",
        "stromal": "hierarchies/prostate/stromal.yaml",
    },
    default_parameters={
        "min_genes": 200,
        "min_cells": 3,
        "n_top_genes": 3000,
        "n_pcs": 40,
        "resolution": 1.2,
        "ar_threshold": 0.5,
        "ne_threshold": 0.3,
    },
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, ProgramConfig] = {
    _GENERAL_PROGRAM.cancer_type: _GENERAL_PROGRAM,
    _PROSTATE_PROGRAM.cancer_type: _PROSTATE_PROGRAM,
}


def get_program(cancer_type: str) -> ProgramConfig:
    """Return the program configuration for *cancer_type*.

    Raises ``KeyError`` if the cancer type is not registered.
    """
    try:
        return _REGISTRY[cancer_type]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY))
        raise KeyError(f"Unknown cancer type {cancer_type!r}. Available: {available}") from None


def list_programs() -> list[ProgramConfig]:
    """Return all registered program configurations."""
    return list(_REGISTRY.values())


def apply_program_defaults(cancer_type: str) -> dict[str, Any]:
    """Return a pipeline configuration dict with the program's marker panels
    and default parameters applied.

    This is the helper used by Property 45 to verify that selecting a cancer
    program yields the correct defaults.
    """
    program = get_program(cancer_type)
    return {
        "cancer_type": program.cancer_type,
        "marker_panels": dict(program.marker_panels),
        "default_parameters": dict(program.default_parameters),
    }
