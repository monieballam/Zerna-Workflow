"""Canonical pipeline step names and import paths for method execution.

Shared by the API (template validation) and the Temporal worker so catalog steps
and runtime resolution stay aligned.
"""

from __future__ import annotations

# Map template / resolved step names → (module_path, class_name) for MethodDefinition classes.
METHOD_REGISTRY: dict[str, tuple[str, str]] = {
    "qc_filter": ("methods.preprocessing.qc_filter", "QCFilterMethod"),
    "ambient_correction": (
        "methods.preprocessing.ambient_correction",
        "AmbientCorrectionMethod",
    ),
    "doublet_detection": ("methods.preprocessing.doublet_detection", "DoubletDetectionMethod"),
    "normalize": ("methods.preprocessing.normalization", "NormalizationMethod"),
    "select_hvg": ("methods.preprocessing.hvg_selection", "HVGSelectionMethod"),
    "run_pca": ("methods.dimensionality_reduction.pca", "PCAMethod"),
    "batch_correction_harmony": (
        "methods.dimensionality_reduction.batch_correction",
        "HarmonyMethod",
    ),
    "batch_correction_scvi": ("methods.dimensionality_reduction.batch_correction", "ScVIMethod"),
    "cluster": ("methods.dimensionality_reduction.clustering", "LeidenMethod"),
    "embed": ("methods.dimensionality_reduction.embedding", "UMAPMethod"),
    "annotate": ("methods.annotation.cell_type_annotation", "CellTypistMethod"),
    "differential_expression": (
        "methods.annotation.differential_expression",
        "MultiModeDifferentialExpressionMethod",
    ),
    "pathway_scoring": ("methods.annotation.pathway_scoring", "PathwayScoringMethod"),
    "ligand_receptor_analysis": ("methods.annotation.ligand_receptor", "LigandReceptorMethod"),
}

# User-facing / legacy template aliases → normalized name before batch-method expansion.
METHOD_ALIASES: dict[str, str] = {
    "qc": "qc_filter",
    "pca": "run_pca",
    "umap": "embed",
    "tsne": "embed",
    "batch_correction": "batch_correct",
    "ligand_receptor": "ligand_receptor_analysis",
}
