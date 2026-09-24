# Zerna Scientific Methods

All scientific methods extend the `MethodDefinition` base class (`methods/base.py`) and declare explicit Pydantic input/output schemas. Methods are executed within the Nextflow pipeline and can optionally leverage GPU acceleration via the heterogeneous compute abstraction layer.

## Method Contract

```python
class MethodDefinition(ABC):
    name: str                                    # Unique method identifier
    version: str                                 # Semantic version
    compute_preference: ComputePreference        # CPU_ONLY | GPU_PREFERRED | GPU_REQUIRED

    def input_schema(self) -> Type[BaseModel]: ...   # Pydantic input model
    def output_schema(self) -> Type[BaseModel]: ...  # Pydantic output model
    def execute(self, input, compute) -> BaseModel: ...
```

All methods support OpenTelemetry tracing via `execute_traced()`, which records method name, version, run_id, and org_id as span attributes.

---

## Preprocessing Methods

### QC Filter

**Module**: `methods/preprocessing/qc_filter.py`
**Class**: `QCFilterMethod`
**Compute**: CPU only
**Version**: 1.0.0

Filters low-quality cells based on gene count, mitochondrial percentage, and minimum cell count per gene. Uses scanpy's QC metrics calculation.

**Input Schema** (`QCFilterInput`):

| Parameter      | Type    | Default    | Description                           |
| -------------- | ------- | ---------- | ------------------------------------- |
| `adata`        | AnnData | _required_ | Input single-cell dataset             |
| `min_genes`    | int     | 200        | Minimum genes per cell                |
| `max_genes`    | int     | 5000       | Maximum genes per cell                |
| `min_cells`    | int     | 3          | Minimum cells per gene                |
| `max_mito_pct` | float   | 20.0       | Maximum mitochondrial gene percentage |
| `mito_prefix`  | str     | "MT-"      | Mitochondrial gene name prefix        |

**Output Schema** (`QCFilterOutput`):

| Field                            | Type    | Description                                |
| -------------------------------- | ------- | ------------------------------------------ |
| `adata`                          | AnnData | Filtered dataset                           |
| `metrics.n_cells_before`         | int     | Cell count before filtering                |
| `metrics.n_cells_after`          | int     | Cell count after filtering                 |
| `metrics.n_genes_before`         | int     | Gene count before filtering                |
| `metrics.n_genes_after`          | int     | Gene count after filtering                 |
| `metrics.median_genes_per_cell`  | float   | Median genes per cell after filtering      |
| `metrics.median_counts_per_cell` | float   | Median UMI counts per cell after filtering |

**Recommendations**: Start with defaults. Increase `max_mito_pct` to 25-30% for tissues with high mitochondrial content (e.g., heart, muscle). Use `mito_prefix="mt-"` for mouse data.

**References**: [Scanpy preprocessing tutorial](https://scanpy-tutorials.readthedocs.io/en/latest/pbmc3k.html)

---

### Doublet Detection

**Module**: `methods/preprocessing/doublet_detection.py`
**Class**: `DoubletDetectionMethod`
**Compute**: CPU only
**Version**: 1.0.0

Identifies cell doublets using Scrublet. Assigns per-cell doublet scores and binary predictions.

**Input Schema** (`DoubletDetectionInput`):

| Parameter               | Type    | Default    | Description                          |
| ----------------------- | ------- | ---------- | ------------------------------------ |
| `adata`                 | AnnData | _required_ | Input dataset (post-QC)              |
| `expected_doublet_rate` | float   | 0.05       | Expected fraction of doublets [0, 1] |
| `random_state`          | int     | 0          | Random seed for reproducibility      |

**Output Schema** (`DoubletDetectionOutput`):

| Field                          | Type    | Description                                                 |
| ------------------------------ | ------- | ----------------------------------------------------------- |
| `adata`                        | AnnData | Dataset with `doublet_score` and `predicted_doublet` in obs |
| `metrics.n_cells`              | int     | Total cell count                                            |
| `metrics.n_predicted_doublets` | int     | Number of predicted doublets                                |
| `metrics.doublet_rate`         | float   | Fraction of predicted doublets                              |
| `metrics.mean_doublet_score`   | float   | Mean doublet score across all cells                         |

**Recommendations**: Use `expected_doublet_rate=0.06` for 10x Chromium data with ~6k cells loaded. Scale rate proportionally with cell loading density.

**References**: [Scrublet (Wolock et al., 2019)](https://doi.org/10.1016/j.cels.2018.11.005)

---

### Normalization

**Module**: `methods/preprocessing/normalization.py`
**Class**: `NormalizationMethod`
**Compute**: GPU preferred (CPU fallback)
**Version**: 1.0.0

Library-size normalization to a target sum, log1p transformation, and optional zero-mean unit-variance scaling. GPU-accelerated scaling is available via PyTorch when a GPU backend is detected.

**Input Schema** (`NormalizationInput`):

| Parameter    | Type          | Default    | Description                           |
| ------------ | ------------- | ---------- | ------------------------------------- |
| `adata`      | AnnData       | _required_ | Input dataset                         |
| `target_sum` | float         | 10000      | Target library size per cell          |
| `scale`      | bool          | True       | Apply zero-mean unit-variance scaling |
| `max_value`  | float \| None | 10.0       | Clip scaled values to [-max, max]     |

**Output Schema** (`NormalizationOutput`):

| Field   | Type    | Description        |
| ------- | ------- | ------------------ |
| `adata` | AnnData | Normalized dataset |

**Recommendations**: Default `target_sum=1e4` is standard for most scRNA-seq. Set `scale=False` if downstream methods (e.g., scVI) expect log-normalized but unscaled data.

**References**: [Scanpy normalization](https://scanpy.readthedocs.io/en/stable/api/scanpy.pp.normalize_total.html)

---

### HVG Selection

**Module**: `methods/preprocessing/hvg_selection.py`
**Class**: `HVGSelectionMethod`
**Compute**: CPU only
**Version**: 1.0.0

Selects highly variable genes for downstream dimensionality reduction.

**Input Schema** (`HVGSelectionInput`):

| Parameter     | Type        | Default     | Description                            |
| ------------- | ----------- | ----------- | -------------------------------------- |
| `adata`       | AnnData     | _required_  | Normalized dataset                     |
| `n_top_genes` | int         | 2000        | Number of HVGs to select (≥ 1)         |
| `flavor`      | str         | "seurat_v3" | HVG selection method                   |
| `batch_key`   | str \| None | None        | Batch column for batch-aware selection |

**Output Schema** (`HVGSelectionOutput`):

| Field                     | Type    | Description                                  |
| ------------------------- | ------- | -------------------------------------------- |
| `adata`                   | AnnData | Dataset with `highly_variable` column in var |
| `metrics.n_genes_total`   | int     | Total gene count                             |
| `metrics.n_hvgs_selected` | int     | Number of HVGs selected                      |

**Recommendations**: 2000-3000 HVGs is typical. Use `batch_key` when integrating multiple samples to avoid selecting batch-specific genes.

**References**: [Stuart et al., 2019 (Seurat v3)](https://doi.org/10.1016/j.cell.2019.05.031)

---

## Dimensionality Reduction Methods

### PCA

**Module**: `methods/dimensionality_reduction/pca.py`
**Class**: `PCAMethod`
**Compute**: GPU preferred (CPU fallback)
**Version**: 1.0.0

Principal component analysis for dimensionality reduction. GPU-accelerated via PyTorch SVD when available.

**Input Schema** (`PCAInput`):

| Parameter             | Type    | Default    | Description                       |
| --------------------- | ------- | ---------- | --------------------------------- |
| `adata`               | AnnData | _required_ | Dataset with HVGs selected        |
| `n_components`        | int     | 50         | Number of PCs to compute [2, 500] |
| `use_highly_variable` | bool    | True       | Restrict to HVGs                  |
| `random_state`        | int     | 0          | Random seed                       |

**Output Schema** (`PCAOutput`):

| Field                           | Type        | Description                      |
| ------------------------------- | ----------- | -------------------------------- |
| `adata`                         | AnnData     | Dataset with `X_pca` in obsm     |
| `metrics.n_components_computed` | int         | Actual number of PCs             |
| `metrics.variance_ratio_top10`  | list[float] | Variance explained by top 10 PCs |

**Recommendations**: 50 PCs is standard. Check the elbow plot of variance ratios to determine optimal dimensionality.

---

### Batch Correction — Harmony

**Module**: `methods/dimensionality_reduction/batch_correction.py`
**Class**: `HarmonyMethod`
**Compute**: GPU preferred
**Version**: 1.0.0

Harmony batch correction operating on PCA embeddings. Fast and effective for moderate batch effects.

**Input Schema** (`HarmonyInput`):

| Parameter          | Type        | Default    | Description                          |
| ------------------ | ----------- | ---------- | ------------------------------------ |
| `adata`            | AnnData     | _required_ | Dataset with PCA computed            |
| `batch_key`        | str \| None | None       | Batch column (auto-detected if None) |
| `n_components`     | int         | 50         | PCA components                       |
| `random_state`     | int         | 0          | Random seed                          |
| `max_iter_harmony` | int         | 10         | Maximum Harmony iterations           |

**Output Schema** (`HarmonyOutput`):

| Field                | Type    | Description                                             |
| -------------------- | ------- | ------------------------------------------------------- |
| `adata`              | AnnData | Dataset with `X_pca_harmony` and `X_pca_before` in obsm |
| `metrics.batch_key`  | str     | Detected or provided batch key                          |
| `metrics.n_batches`  | int     | Number of batches                                       |
| `metrics.kbet_score` | float   | kBET-like mixing score [0, 1]                           |
| `metrics.lisi_score` | float   | LISI-like diversity score [1, n_batches]                |

**Recommendations**: Harmony is the default choice — fast and works well for most datasets. Use scVI for severe batch effects or when raw count modeling is preferred.

**References**: [Korsunsky et al., 2019](https://doi.org/10.1038/s41592-019-0619-0)

---

### Batch Correction — scVI

**Module**: `methods/dimensionality_reduction/batch_correction.py`
**Class**: `ScVIMethod`
**Compute**: GPU preferred
**Version**: 1.0.0

Variational autoencoder-based batch correction using scVI. Learns a latent representation that removes batch effects while preserving biological variation.

**Input Schema** (`ScVIInput`):

| Parameter      | Type        | Default    | Description                          |
| -------------- | ----------- | ---------- | ------------------------------------ |
| `adata`        | AnnData     | _required_ | Dataset (raw integer counts in X)    |
| `batch_key`    | str \| None | None       | Batch column (auto-detected if None) |
| `n_latent`     | int         | 30         | Latent space dimensions [2+]         |
| `n_layers`     | int         | 2          | Neural network layers [1+]           |
| `max_epochs`   | int         | 400        | Training epochs [1+]                 |
| `random_state` | int         | 0          | Random seed                          |

**Output Schema** (`ScVIOutput`):

| Field                | Type    | Description                                      |
| -------------------- | ------- | ------------------------------------------------ |
| `adata`              | AnnData | Dataset with `X_scVI` and `X_pca_before` in obsm |
| `metrics.batch_key`  | str     | Detected or provided batch key                   |
| `metrics.n_batches`  | int     | Number of batches                                |
| `metrics.kbet_score` | float   | kBET-like mixing score [0, 1]                    |
| `metrics.lisi_score` | float   | LISI-like diversity score [1, n_batches]         |

**Recommendations**: Requires raw counts in `adata.X`. Use for large datasets with severe batch effects. GPU strongly recommended for training speed.

**References**: [Lopez et al., 2018](https://doi.org/10.1038/s41592-018-0229-2)

---

### Clustering — Leiden

**Module**: `methods/dimensionality_reduction/clustering.py`
**Class**: `LeidenMethod`
**Compute**: CPU only
**Version**: 1.0.0

Leiden community detection algorithm for cell clustering. Produces more connected communities than Louvain.

**Input Schema** (`ClusteringInput`):

| Parameter      | Type    | Default    | Description                          |
| -------------- | ------- | ---------- | ------------------------------------ |
| `adata`        | AnnData | _required_ | Dataset with PCA/corrected embedding |
| `resolution`   | float   | 1.0        | Clustering resolution (> 0)          |
| `n_neighbors`  | int     | 15         | k-NN graph neighbors (≥ 2)           |
| `use_rep`      | str     | "X_pca"    | Embedding key for neighbor graph     |
| `random_state` | int     | 0          | Random seed                          |

**Output Schema** (`ClusteringOutput`):

| Field                   | Type      | Description                         |
| ----------------------- | --------- | ----------------------------------- |
| `adata`                 | AnnData   | Dataset with `leiden` column in obs |
| `metrics.n_clusters`    | int       | Number of clusters found            |
| `metrics.cluster_sizes` | list[int] | Cell count per cluster              |

**Recommendations**: Start with `resolution=1.0`. Lower values (0.3-0.8) produce fewer, larger clusters; higher values (1.5-3.0) produce more, smaller clusters. Use `use_rep="X_pca_harmony"` after batch correction.

**References**: [Traag et al., 2019](https://doi.org/10.1038/s41598-019-41695-z)

---

### Clustering — Louvain

**Module**: `methods/dimensionality_reduction/clustering.py`
**Class**: `LouvainMethod`
**Compute**: CPU only
**Version**: 1.0.0

Louvain community detection. Faster than Leiden but may produce disconnected communities.

Uses the same `ClusteringInput` and `ClusteringOutput` schemas as Leiden. Stores results in `adata.obs["louvain"]`.

---

### Embedding — UMAP

**Module**: `methods/dimensionality_reduction/embedding.py`
**Class**: `UMAPMethod`
**Compute**: GPU preferred
**Version**: 1.0.0

UMAP embedding for 2D/3D visualization with reproducible random seeds.

**Input Schema** (`UMAPInput`):

| Parameter      | Type    | Default    | Description                           |
| -------------- | ------- | ---------- | ------------------------------------- |
| `adata`        | AnnData | _required_ | Dataset with PCA/corrected embedding  |
| `n_components` | int     | 2          | Embedding dimensions [2, 3]           |
| `n_neighbors`  | int     | 15         | k-NN neighbors (≥ 2)                  |
| `min_dist`     | float   | 0.5        | Minimum distance between points (≥ 0) |
| `use_rep`      | str     | "X_pca"    | Embedding key for neighbor graph      |
| `random_state` | int     | 0          | Random seed                           |

**Output Schema** (`EmbeddingOutput`):

| Field           | Type    | Description                   |
| --------------- | ------- | ----------------------------- |
| `adata`         | AnnData | Dataset with `X_umap` in obsm |
| `embedding_key` | str     | "X_umap"                      |

**Recommendations**: `min_dist=0.1` for tighter clusters, `min_dist=0.5` for more spread. Use `n_components=3` for 3D visualization.

**References**: [McInnes et al., 2018](https://doi.org/10.21105/joss.00861)

---

### Embedding — t-SNE

**Module**: `methods/dimensionality_reduction/embedding.py`
**Class**: `TSNEMethod`
**Compute**: GPU preferred
**Version**: 1.0.0

t-SNE embedding for 2D/3D visualization.

**Input Schema** (`TSNEInput`):

| Parameter      | Type    | Default    | Description                 |
| -------------- | ------- | ---------- | --------------------------- |
| `adata`        | AnnData | _required_ | Dataset with PCA            |
| `n_components` | int     | 2          | Embedding dimensions [2, 3] |
| `n_neighbors`  | int     | 15         | k-NN neighbors (≥ 2)        |
| `perplexity`   | float   | 30.0       | Perplexity parameter (> 0)  |
| `use_rep`      | str     | "X_pca"    | Embedding key               |
| `random_state` | int     | 0          | Random seed                 |

**Output Schema** (`EmbeddingOutput`):

| Field           | Type    | Description                   |
| --------------- | ------- | ----------------------------- |
| `adata`         | AnnData | Dataset with `X_tsne` in obsm |
| `embedding_key` | str     | "X_tsne"                      |

**Recommendations**: `perplexity` should be roughly 1/100th of cell count (min 5, max 50). t-SNE is better for local structure; UMAP preserves more global structure.

**References**: [van der Maaten & Hinton, 2008](https://www.jmlr.org/papers/v9/vandermaaten08a.html)

---

## Annotation & Analysis Methods

### CellTypist Annotation

**Module**: `methods/annotation/cell_type_annotation.py`
**Class**: `CellTypistMethod`
**Compute**: CPU only
**Version**: 1.0.0

Automated cell type annotation. The default engine is CellTypist. Conservative, marker-pack, and hybrid modes are also available.

**Input Schema** (`CellTypistInput`):

| Parameter                     | Type         | Default               | Description                                                                                                                       |
| ----------------------------- | ------------ | --------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `adata`                       | AnnData      | _required_            | Clustered dataset                                                                                                                 |
| `annotation_method`           | str          | "celltypist"          | CellTypist (default), conservative, marker-pack, or hybrid |
| `model_name`                  | str          | "auto"                | CellTypist model name or path                                                                                                     |
| `majority_voting`             | bool         | True                  | Smooth predictions within clusters                                                                                                |
| `cluster_key`                 | str \| None  | None                  | Cluster column for voting (auto-detected)                                                                                         |
| `min_prob`                    | float        | 0.0                   | Minimum confidence threshold [0, 1]                                                                                               |
| `marker_pack`                 | dict \| None | None                  | Optional inline marker pack for cluster-level scoring                                                                             |
| `marker_pack_path`            | str \| None  | None                  | Optional JSON marker pack path                                                                                                    |
| `cluster_prior_path`          | str \| None  | None                  | Optional JSONL similar-cluster prior index                                                                                        |
| `tissue_context`              | str          | ""                    | Optional tissue context for retrieval priors                                                                                      |
| `cancer_type`                 | str \| None  | None                  | Optional cancer context for retrieval priors                                                                                      |
| `species`                     | str          | "human"               | Species context for marker/retrieval support                                                                                      |
| `cluster_marker_top_n`        | int          | 50                    | Number of marker genes to compute per cluster                                                                                     |
| `min_marker_overlap`          | int          | 2                     | Minimum marker overlap for marker-pack scoring                                                                                    |
| `cluster_markers_export_path` | str \| None  | None                  | Optional CSV export path for cluster markers                                                                                      |
| `benchmark_reference_key`     | str \| None  | None                  | Optional obs column for benchmarking final labels                                                                                 |
| `knowledge_pack_version`      | str \| None  | None                  | KnowledgePack version for provenance                                                                                              |

**Output Schema** (`CellTypistOutput`):

| Field                            | Type    | Description                                                           |
| -------------------------------- | ------- | --------------------------------------------------------------------- |
| `adata`                          | AnnData | Dataset with annotation columns in obs and probability matrix in obsm |
| `metrics.n_cells_annotated`      | int     | Total cells annotated                                                 |
| `metrics.n_cell_types_predicted` | int     | Unique cell types found                                               |
| `metrics.mean_confidence`        | float   | Mean prediction confidence                                            |
| `metrics.model_used`             | str     | CellTypist model name                                                 |

Annotations are stored as:

- `obs["celltypist_cell_type"]` — predicted cell type label
- `obs["celltypist_conf_score"]` — confidence score [0, 1]
- `obs["celltypist_majority_voting"]` — majority-voted label (if enabled)
- `obs["celltypist_provenance"]` — JSON provenance string
- `obsm["celltypist_prob_matrix"]` — full probability matrix
- `obs["annotation_tissue"]` / `obs["annotation_lineage"]` / `obs["annotation_cell_type"]` — canonical hierarchical labels
- `obs["annotation_label"]` — cluster-level legacy-style label derived from marker-pack scoring or cluster consensus
- `obs["annotation_confidence"]` — cluster-level confidence bucket
- `obs["annotation_status"]` / `obs["annotation_resolution"]` / `obs["annotation_uncertainty"]` — conservative decision status, label granularity, and residual uncertainty
- `uns["zerna_cluster_annotations"]` — per-cluster summaries with top candidates and supporting markers
- `uns["conservative_annotation_audit"]` — full per-cluster audit trail with evidence, thresholds, and abstention reasons
- `uns["annotation_benchmark"]` — optional benchmark report when `benchmark_reference_key` is provided
- `uns["cluster_retrieval_evidence"]` — optional similar-cluster prior/evidence bundle
- `uns["cluster_markers"]` — top marker genes per cluster
- `uns["cluster_markers_path"]` — optional exported cluster marker CSV path

**Recommendations**: Use the default `celltypist` mode. Switch to `conservative` when you want auditable abstentions. Use `Immune_All_Low.pkl` for immune-focused datasets if you override the reference model, and set `min_prob=0.5` to suppress weak votes.

**References**: [Domínguez Conde et al., 2022](https://doi.org/10.1126/science.abl5197)

---

### Differential Expression

**Module**: `methods/annotation/differential_expression.py`
**Class**: `DifferentialExpressionMethod`
**Compute**: CPU only
**Version**: 1.0.0

One-vs-rest differential expression analysis between all clusters using scanpy's `rank_genes_groups`.

**Input Schema** (`DifferentialExpressionInput`):

| Parameter                | Type    | Default              | Description                                                    |
| ------------------------ | ------- | -------------------- | -------------------------------------------------------------- |
| `adata`                  | AnnData | _required_           | Clustered dataset                                              |
| `cluster_key`            | str     | "leiden"             | obs column with cluster assignments                            |
| `method`                 | str     | "wilcoxon"           | Statistical test: `wilcoxon`, `t-test`, `t-test_overestim_var` |
| `n_genes`                | int     | 0                    | Top genes per cluster to return (0 = all)                      |
| `min_in_group_fraction`  | float   | 0.1                  | Min fraction of cells expressing gene in group                 |
| `min_fold_change`        | float   | 1.0                  | Min log fold change                                            |
| `max_out_group_fraction` | float   | 0.5                  | Max fraction expressing in out-group                           |
| `corr_method`            | str     | "benjamini-hochberg" | Multiple testing correction                                    |

**Output Schema** (`DifferentialExpressionOutput`):

| Field                    | Type      | Description                                                       |
| ------------------------ | --------- | ----------------------------------------------------------------- |
| `adata`                  | AnnData   | Dataset with `rank_genes_groups` in uns                           |
| `results_df`             | DataFrame | Tidy results: cluster, gene, logfoldchange, pval, pval_adj, score |
| `metrics.n_clusters`     | int       | Number of clusters tested                                         |
| `metrics.n_genes_tested` | int       | Total genes tested                                                |

**Recommendations**: Wilcoxon rank-sum is the default and most robust. Use `n_genes=50` to limit output size for visualization. Results are sorted by adjusted p-value (most significant first).

**References**: [Scanpy rank_genes_groups](https://scanpy.readthedocs.io/en/stable/api/scanpy.tl.rank_genes_groups.html)

---

### Pathway Scoring

**Module**: `methods/annotation/pathway_scoring.py`
**Class**: `PathwayScoringMethod`
**Compute**: CPU only
**Version**: 1.0.0

Per-cell pathway activity scoring using decoupler. Supports multiple pathway databases (MSigDB, GO, KEGG) supplied via KnowledgePacks.

**Input Schema** (`PathwayScoringInput`):

| Parameter                | Type        | Default          | Description                                                                |
| ------------------------ | ----------- | ---------------- | -------------------------------------------------------------------------- |
| `adata`                  | AnnData     | _required_       | Annotated dataset                                                          |
| `net`                    | DataFrame   | _required_       | Gene set network (source, target, weight columns)                          |
| `pathway_database`       | str         | "custom"         | Database name for provenance                                               |
| `knowledge_pack_version` | str \| None | None             | KnowledgePack version                                                      |
| `methods`                | list[str]   | ["ulm"]          | decoupler methods: `ulm`, `mlm`, `aucell`, `wsum`, `gsva`, `zscore`, `ora` |
| `min_n`                  | int         | 5                | Min targets per pathway (≥ 1)                                              |
| `obsm_key`               | str         | "pathway_scores" | Key for storing scores in obsm                                             |

**Output Schema** (`PathwayScoringOutput`):

| Field                       | Type      | Description                                               |
| --------------------------- | --------- | --------------------------------------------------------- |
| `adata`                     | AnnData   | Dataset with pathway scores in obsm and provenance in uns |
| `metrics.n_pathways_scored` | int       | Number of pathways scored                                 |
| `metrics.n_cells`           | int       | Number of cells                                           |
| `metrics.methods_used`      | list[str] | Successfully run methods                                  |

Scores are stored in:

- `obsm["pathway_scores"]` — primary score matrix (n_cells × n_pathways)
- `uns["pathway_scoring_meta"]` — provenance metadata

**Recommendations**: `ulm` (univariate linear model) is fast and effective for most use cases. Run multiple methods (`["ulm", "mlm"]`) for consensus scoring.

**References**: [Badia-i-Mompel et al., 2022 (decoupler)](https://doi.org/10.1093/bioinformatics/btac651)

---

### Ligand-Receptor Analysis

**Module**: `methods/annotation/ligand_receptor.py`
**Class**: `LigandReceptorMethod`
**Compute**: CPU only
**Version**: 1.0.0

Cell-cell communication analysis using LIANA. Computes ligand-receptor interaction scores between all cluster pairs.

**Input Schema** (`LigandReceptorInput`):

| Parameter       | Type    | Default     | Description                                                                   |
| --------------- | ------- | ----------- | ----------------------------------------------------------------------------- |
| `adata`         | AnnData | _required_  | Clustered and annotated dataset                                               |
| `cluster_key`   | str     | "leiden"    | obs column with cluster/cell-type assignments                                 |
| `resource_name` | str     | "consensus" | LIANA resource: `consensus`, `cellphonedb`, `cellchat`, `connectome`, `natmi` |
| `expr_prop`     | float   | 0.1         | Min proportion of cells expressing ligand/receptor                            |
| `min_cells`     | int     | 5           | Min cells per cluster to include                                              |
| `n_perms`       | int     | 100         | Permutations for significance testing (0 = skip)                              |

**Output Schema** (`LigandReceptorOutput`):

| Field                     | Type      | Description                                                                |
| ------------------------- | --------- | -------------------------------------------------------------------------- |
| `adata`                   | AnnData   | Dataset with `liana_res` in uns                                            |
| `results_df`              | DataFrame | Tidy results: source, target, ligand_complex, receptor_complex, liana_rank |
| `metrics.n_interactions`  | int       | Total interactions found                                                   |
| `metrics.n_cluster_pairs` | int       | Number of directed cluster pairs                                           |
| `metrics.n_clusters`      | int       | Number of clusters analyzed                                                |

**Recommendations**: Use `resource_name="consensus"` for a curated set of interactions. Increase `n_perms` to 1000 for publication-quality p-values. Requires at least 2 clusters with `min_cells` each.

**References**: [Dimitrov et al., 2022 (LIANA)](https://doi.org/10.1038/s41467-022-34346-1)
