#!/usr/bin/env python3
"""Generate small synthetic single-cell datasets for integration tests.

Creates an AnnData object with ~1000 cells and ~500 genes containing
realistic metadata (cell types, batch labels, QC metrics).

Usage:
    python scripts/generate_test_data.py [--output PATH] [--n-cells N] [--n-genes N]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

# Pandas 3.x uses Arrow-backed strings by default, which anndata's h5ad
# writer does not yet support.  Disable for this script.
pd.options.future.infer_string = False  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_N_CELLS = 1000
DEFAULT_N_GENES = 500
DEFAULT_OUTPUT = "tests/integration/fixtures/synthetic_1k.h5ad"

CELL_TYPES = [
    "T cell",
    "B cell",
    "Monocyte",
    "NK cell",
    "Dendritic cell",
    "Macrophage",
    "Fibroblast",
    "Epithelial",
]

BATCHES = ["batch_1", "batch_2", "batch_3"]

TISSUES = ["PBMC", "Tumor", "Normal"]


def generate_synthetic_dataset(
    n_cells: int = DEFAULT_N_CELLS,
    n_genes: int = DEFAULT_N_GENES,
    seed: int = 42,
) -> ad.AnnData:
    """Generate a synthetic single-cell AnnData object.

    Parameters
    ----------
    n_cells : int
        Number of cells to generate.
    n_genes : int
        Number of genes to generate.
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    ad.AnnData
        Annotated data matrix with realistic metadata.
    """
    rng = np.random.default_rng(seed)

    # --- Expression matrix (sparse, UMI-like counts) ---
    # Use a negative binomial to mimic real scRNA-seq count distributions
    data = rng.negative_binomial(n=2, p=0.3, size=(n_cells, n_genes)).astype(np.float32)
    # Make ~70 % of entries zero (dropout)
    mask = rng.random((n_cells, n_genes)) < 0.7
    data[mask] = 0.0
    X = sparse.csr_matrix(data)

    # --- Gene names ---
    # Mix of realistic prefixes; first 20 are mitochondrial for QC testing
    mt_genes = [f"MT-{chr(65 + i)}{j}" for i, j in enumerate(range(20))]
    regular_genes = [f"GENE{i:04d}" for i in range(n_genes - len(mt_genes))]
    gene_names = mt_genes + regular_genes
    var = pd.DataFrame(index=pd.Index(gene_names[:n_genes], dtype="object"))
    var.index.name = "gene"

    # --- Cell metadata ---
    cell_ids = [f"CELL_{i:05d}" for i in range(n_cells)]
    obs = pd.DataFrame(index=pd.Index(cell_ids, dtype="object"))
    obs.index.name = "cell"

    # Assign cell types with realistic proportions
    type_probs = rng.dirichlet(np.ones(len(CELL_TYPES)))
    obs["cell_type"] = np.array(rng.choice(CELL_TYPES, size=n_cells, p=type_probs), dtype=object)

    # Batch labels
    obs["batch"] = np.array(rng.choice(BATCHES, size=n_cells), dtype=object)

    # Tissue of origin
    obs["tissue"] = np.array(rng.choice(TISSUES, size=n_cells), dtype=object)

    # QC metrics
    obs["n_genes_by_counts"] = np.asarray((X > 0).sum(axis=1)).flatten()
    obs["total_counts"] = np.asarray(X.sum(axis=1)).flatten()

    # Mitochondrial fraction (based on first 20 genes)
    mt_idx = min(20, n_genes)
    mt_counts = np.asarray(X[:, :mt_idx].sum(axis=1)).flatten()
    total = obs["total_counts"].values.copy()
    total[total == 0] = 1  # avoid division by zero
    obs["pct_counts_mt"] = (mt_counts / total) * 100

    # Doublet score (synthetic)
    obs["doublet_score"] = rng.beta(2, 10, size=n_cells)
    obs["predicted_doublet"] = obs["doublet_score"] > 0.25

    # --- Assemble AnnData ---
    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.uns["dataset_id"] = "synthetic_integration_test"
    adata.uns["organism"] = "human"
    adata.uns["n_cells_original"] = n_cells
    adata.uns["n_genes_original"] = n_genes

    return adata


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic scRNA-seq test data")
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT,
        help=f"Output h5ad file path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--n-cells",
        type=int,
        default=DEFAULT_N_CELLS,
        help=f"Number of cells (default: {DEFAULT_N_CELLS})",
    )
    parser.add_argument(
        "--n-genes",
        type=int,
        default=DEFAULT_N_GENES,
        help=f"Number of genes (default: {DEFAULT_N_GENES})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42)",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Generating synthetic dataset: {args.n_cells} cells × {args.n_genes} genes ...")
    adata = generate_synthetic_dataset(
        n_cells=args.n_cells,
        n_genes=args.n_genes,
        seed=args.seed,
    )

    adata.write_h5ad(output_path)
    print(f"Saved to {output_path}  ({output_path.stat().st_size / 1024:.1f} KB)")
    print(f"  Cell types: {adata.obs['cell_type'].value_counts().to_dict()}")
    print(f"  Batches:    {adata.obs['batch'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
