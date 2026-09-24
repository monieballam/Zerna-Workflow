"""Canonical pipeline method catalog and seeded template definitions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

TemplateMethodEntry = str | dict[str, Any]


METHOD_CATALOG: list[dict[str, Any]] = [
    {
        "name": "qc_filter",
        "label": "QC & Filtering",
        "description": (
            "Remove low-quality cells and genes before downstream analysis. "
            "Stricter QC usually speeds later steps by shrinking the matrix, but it can discard "
            "rare or stressed populations if pushed too far."
        ),
        "order": 10,
        "default_selected": True,
    },
    {
        "name": "doublet_detection",
        "label": "Doublet Detection",
        "description": (
            "Score and optionally remove likely doublets before normalization. "
            "This adds some early runtime, but it often improves cluster purity and reduces "
            "wasted computation on mixed-cell artifacts."
        ),
        "order": 20,
        "default_selected": True,
    },
    {
        "name": "ambient_correction",
        "label": "Ambient RNA correction",
        "description": (
            "Optional advanced preprocessing for suspected background RNA contamination—usually not "
            "needed for every dataset. SoupX is available through an R helper; because this worker "
            "does not have the raw empty-droplet matrix at this stage, it uses a filtered-counts-only "
            "approximation. Identity only copies counts to corrected_counts for provenance and does "
            "not remove ambient RNA. Disabled by default."
        ),
        "order": 25,
        "default_selected": False,
        "enabled_if": "ambient_correction",
    },
    {
        "name": "normalize",
        "label": "Normalization",
        "description": (
            "Library-size normalize counts and compute log1p expression values. "
            "This step is usually fast and low-risk, and it stabilizes downstream HVG, PCA, "
            "and marker detection."
        ),
        "order": 30,
        "default_selected": True,
    },
    {
        "name": "select_hvg",
        "label": "HVG Selection",
        "description": (
            "Select highly variable genes for downstream PCA and clustering. "
            "This step marks HVGs in adata.var but does not subset genes immediately. "
            "Using fewer genes is faster and lighter on memory, while using more genes may keep "
            "subtle biology at the cost of noisier and slower downstream steps."
        ),
        "order": 40,
        "default_selected": True,
    },
    {
        "name": "run_pca",
        "label": "PCA",
        "description": (
            "Compute principal components from the selected HVGs. "
            "More components can preserve more structure, but they increase downstream neighbor, "
            "clustering, and embedding cost."
        ),
        "order": 50,
        "default_selected": True,
    },
    {
        "name": "batch_correct",
        "label": "Batch Correction",
        "description": (
            "Optionally integrate batches before clustering. "
            "This can greatly improve comparability across samples, but it is often one of the "
            "slowest parts of the pipeline, especially with scVI."
        ),
        "order": 60,
        "default_selected": True,
        "enabled_if": "batch_correction",
    },
    {
        "name": "cluster",
        "label": "Clustering",
        "description": (
            "Build a neighbor graph and cluster cells with Leiden or Louvain. "
            "This is usually moderate in cost; finer settings can reveal substructure but may "
            "split biologically similar cells into too many groups."
        ),
        "order": 70,
        "default_selected": True,
    },
    {
        "name": "embed",
        "label": "Embedding",
        "description": (
            "Compute a UMAP or t-SNE embedding for visualization. "
            "UMAP is usually faster and more scalable; t-SNE can separate local structure well "
            "but often costs more time."
        ),
        "order": 80,
        "default_selected": True,
    },
    {
        "name": "annotate",
        "label": "Cell-Type Annotation",
        "description": (
            "Assign cell types using CellTypist and Zerna-specific outputs. "
            "This adds moderate runtime, but it turns clusters into interpretable biology and "
            "improves downstream reporting."
        ),
        "order": 90,
        "default_selected": True,
    },
    {
        "name": "differential_expression",
        "label": "Differential Expression",
        "description": (
            "Rank marker genes for clusters or cell populations. "
            "This can be expensive on large datasets, but it is one of the most useful steps for "
            "cluster interpretation and validation."
        ),
        "order": 100,
        "default_selected": True,
    },
    {
        "name": "pathway_scoring",
        "label": "Pathway Scoring",
        "description": (
            "Optionally score pathway activity with decoupler and PROGENy-style inputs. "
            "This adds noticeable runtime and memory use, but it provides pathway-level signals "
            "that are often easier to interpret than single genes."
        ),
        "order": 110,
        "default_selected": True,
        "enabled_if": "pathway_scoring",
    },
    {
        "name": "ligand_receptor_analysis",
        "label": "Ligand-Receptor Analysis",
        "description": (
            "Optionally infer cell-cell communication with LIANA. "
            "This is one of the heavier downstream analyses, but it can reveal cross-cluster "
            "signaling programs that simple marker analysis misses."
        ),
        "order": 120,
        "default_selected": True,
        "enabled_if": "ligand_receptor",
    },
]

METHOD_CATALOG_BY_NAME = {entry["name"]: deepcopy(entry) for entry in METHOD_CATALOG}

FULL_PARAMETER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "min_genes": {
            "type": "integer",
            "default": 200,
            "minimum": 1,
            "description": (
                "Drop cells with fewer detected genes than this threshold. "
                "Raising it removes emptier droplets and usually speeds later steps slightly, "
                "but it can discard small or transcriptionally quiet cell types."
            ),
        },
        "max_genes": {
            "type": "integer",
            "default": 6000,
            "minimum": 1,
            "description": (
                "Drop cells with unusually high gene counts, which often helps catch doublets or "
                "multiplets. Lower values clean the dataset more aggressively and reduce runtime, "
                "but they can also remove genuinely complex cells."
            ),
        },
        "min_cells": {
            "type": "integer",
            "default": 3,
            "minimum": 1,
            "description": (
                "Keep only genes expressed in at least this many cells. "
                "Higher values reduce matrix size and speed the pipeline, but they also remove "
                "rare-feature signals."
            ),
        },
        "max_mito_pct": {
            "type": "number",
            "default": 20.0,
            "minimum": 0.0,
            "maximum": 100.0,
            "description": (
                "Filter out cells with mitochondrial transcript fractions above this value. "
                "Lower thresholds usually improve quality and slightly reduce runtime, but they "
                "can also remove stressed yet biologically relevant cells."
            ),
        },
        "qc_species": {
            "type": "string",
            "default": "auto",
            "enum": ["auto", "human", "mouse"],
            "description": (
                "Species used for mitochondrial, ribosomal, hemoglobin, and housekeeping gene matching. "
                "auto inspects feature names (e.g. MT- vs mt-) and picks human or mouse when confident; "
                "ambiguous cases default conservatively and are recorded in the QC report."
            ),
        },
        "filter_by_housekeeping": {
            "type": "boolean",
            "default": False,
            "description": (
                "When enabled, applies a max housekeeping-associated fraction filter using species-appropriate "
                "defaults (MALAT1/NEAT1 for human; Malat1/Neat1 for mouse) unless overridden programmatically."
            ),
        },
        "min_counts": {
            "type": "number",
            "minimum": 0.0,
            "description": (
                "Optional minimum total UMI counts per cell. "
                "Helps remove empty droplets; leave unset to skip this filter."
            ),
        },
        "max_counts": {
            "type": "number",
            "minimum": 0.0,
            "description": (
                "Optional maximum total UMI counts per cell. "
                "Helps remove multiplets; leave unset to skip this filter."
            ),
        },
        "max_ribo_pct": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 100.0,
            "description": (
                "Optional maximum ribosomal transcript fraction (RPS/RPL prefix matching by default). "
                "Useful for blood or highly metabolic samples; leave unset to skip."
            ),
        },
        "compute_hb_pct": {
            "type": "boolean",
            "default": False,
            "description": (
                "Enable hemoglobin fraction QC using species-appropriate hemoglobin gene symbols "
                "(human HBA/HBB family; mouse Hba/Hbb-style). A default max hemoglobin fraction applies when enabled."
            ),
        },
        "max_hb_pct": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 100.0,
            "description": "Max hemoglobin fraction when hemoglobin QC is enabled (or when max_hb_pct is set alone).",
        },
        "max_hk_pct": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 100.0,
            "description": (
                "Max housekeeping-associated fraction when housekeeping filtering is enabled "
                "(toggle) or when this threshold is set programmatically."
            ),
        },
        "ambient_correction": {
            "type": "boolean",
            "default": False,
            "description": (
                "Optional advanced step before normalization for datasets with suspected ambient RNA. "
                "Usually not needed for every run. SoupX is available through an R helper in a "
                "filtered-counts-only mode because raw empty-droplet matrices are not available at "
                "this step. Identity does not perform real ambient removal."
            ),
        },
        "ambient_method": {
            "type": "string",
            "default": "off",
            "enum": ["off", "identity", "soupx"],
            "description": (
                "off: no ambient processing. identity: copy counts to corrected_counts only (scaffold; "
                "not biological correction). soupx: run SoupX via the R helper using filtered counts "
                "as both toc and tod because raw empty-droplet counts are unavailable here."
            ),
        },
        "mito_prefix": {
            "type": "string",
            "description": (
                "Legacy override: single mitochondrial gene prefix (case-insensitive). "
                "When set, it replaces species-aware MT-/mt- matching. Omit for automatic matching from qc_species."
            ),
        },
        "ribo_prefixes": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Programmatic override for ribosomal gene prefixes (uppercased during matching). "
                "Defaults to RPS and RPL when omitted."
            ),
        },
        "hb_gene_names": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Programmatic override for hemoglobin gene symbols (case-insensitive matching on var names).",
        },
        "hk_gene_names": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Programmatic override for housekeeping gene symbols (case-insensitive matching on var names).",
        },
        "expected_doublet_rate": {
            "type": "number",
            "default": 0.05,
            "minimum": 0.0,
            "maximum": 1.0,
            "description": (
                "Expected doublet fraction for Scrublet (ignored by SOLO). "
                "Higher values make Scrublet more willing to flag suspect cells, improving "
                "sensitivity at the cost of specificity."
            ),
        },
        "doublet_method": {
            "type": "string",
            "default": "scrublet",
            "enum": [
                "scrublet",
                "solo",
            ],
            "description": (
                "Doublet detection method. scrublet: fast simulation-based detection for most datasets. "
                "solo: scVI + SOLO model-based detection with higher compute cost. "
                "Legacy templates or API payloads may still supply other backends; the worker accepts them."
            ),
        },
        "doublet_threshold": {
            "type": "number",
            "default": 0.25,
            "minimum": 0.0,
            "maximum": 1.0,
            "description": (
                "Score cutoff used to label cells as doublets. "
                "Lower thresholds remove more cells and can improve cluster purity, but they may "
                "also over-filter true singlets."
            ),
        },
        "doublet_mode": {
            "type": "string",
            "default": "remove_doublets",
            "enum": ["flag_only", "remove_doublets"],
            "description": (
                "flag_only stores doublet_score and predicted_doublet without removing cells; "
                "remove_doublets drops predicted doublets before normalization. "
                "When unset, legacy filter_doublets still applies for older templates."
            ),
        },
        "doublet_sample_key": {
            "type": "string",
            "description": (
                "obs column for per-sample doublet detection (defaults to batch_key when unset)."
            ),
        },
        "solo_batch_size": {
            "type": "integer",
            "default": 512,
            "minimum": 16,
            "description": (
                "Mini-batch size used by SOLO/scVI training. Higher values can speed GPU-backed "
                "runs and improve hardware utilization, but they increase memory pressure and may "
                "destabilize constrained machines."
            ),
        },
        "solo_gene_likelihood": {
            "type": "string",
            "default": "zinb",
            "enum": ["zinb", "nb", "poisson"],
            "description": (
                "Observation model used by SOLO's underlying scVI fit. ZINB is the most flexible "
                "and closest to the literature default; NB or Poisson can train faster or behave "
                "better on hardware backends that struggle with the heavier likelihood."
            ),
        },
        "solo_max_epochs": {
            "type": "integer",
            "default": 100,
            "minimum": 1,
            "description": (
                "Maximum epochs for SOLO/scVI doublet training. More epochs can improve "
                "convergence on noisy datasets, but they materially increase runtime."
            ),
        },
        "doubletdetection_voter_thresh": {
            "type": "number",
            "default": 0.5,
            "minimum": 0.0,
            "maximum": 1.0,
            "description": (
                "Consensus threshold for DoubletDetection's ensemble voters. Raising it makes "
                "calls more conservative with little runtime change, trading sensitivity for "
                "specificity."
            ),
        },
        "doubletdetection_p_thresh": {
            "type": "number",
            "default": 1e-16,
            "minimum": 0.0,
            "description": (
                "P-value threshold used by DoubletDetection. More permissive values flag more "
                "doublets but risk over-filtering; runtime impact is negligible."
            ),
        },
        "filter_doublets": {
            "type": "boolean",
            "default": True,
            "description": (
                "If enabled, predicted doublets are removed before downstream analysis. "
                "Keeping this on usually improves downstream quality and reduces compute by "
                "shrinking the dataset, but it depends on doublet calls being well calibrated."
            ),
        },
        "target_sum": {
            "type": "number",
            "default": 10000,
            "minimum": 1,
            "description": (
                "Target library size used during normalization. "
                "This has little effect on runtime; it mainly changes expression scaling, so the "
                "gain is comparability rather than speed."
            ),
        },
        "n_top_genes": {
            "type": "integer",
            "default": 2000,
            "minimum": 100,
            "description": (
                "HVG Selection: number of highly variable genes to mark for PCA and downstream "
                "analysis (genes are not subset from the object in this step). "
                "Lower values are faster and lighter, while higher values can preserve subtler "
                "biology but increase noise and compute cost."
            ),
        },
        "hvg_flavor": {
            "type": "string",
            "default": "seurat_v3",
            "enum": ["seurat", "seurat_v3", "cell_ranger"],
            "description": (
                "HVG Selection: Scanpy ``highly_variable_genes`` flavor. "
                "seurat_v3 uses ``layers['counts']`` when present; otherwise it falls back to "
                "the active matrix with an explicit provenance warning. seurat and cell_ranger use "
                "the active expression matrix (``adata.X``)."
            ),
        },
        "hvg_batch_key": {
            "type": "string",
            "description": (
                "Optional obs column for batch-aware HVG Selection (Scanpy ``batch_key``). "
                "Intended when multiple samples or batches are present; the run UI shows this "
                "when batch correction is enabled, per-sample doublet detection needs a column, "
                "or a batch key is already configured."
            ),
        },
        "n_pcs": {
            "type": "integer",
            "default": 50,
            "minimum": 2,
            "maximum": 100,
            "description": (
                "Number of principal components to compute and carry forward. "
                "More PCs can capture more structure, but they increase neighbor graph, embedding, "
                "and integration cost."
            ),
        },
        "batch_correction": {
            "type": "boolean",
            "default": False,
            "description": (
                "Enable batch correction before clustering and embedding. "
                "This can substantially improve multi-sample integration, but it adds one of the "
                "largest runtime and memory costs in the pipeline."
            ),
        },
        "integration_mode": {
            "type": "string",
            "default": "harmony",
            "enum": ["harmony", "scvi"],
            "description": (
                "Integration method when batch correction is enabled: Harmony (PCA space) or "
                "scVI (counts-based latent space). This is the canonical dashboard selector; "
                "legacy runs may still supply batch_method instead."
            ),
        },
        "batch_method": {
            "type": "string",
            "default": "harmony",
            "enum": ["harmony", "scvi"],
            "description": (
                "Legacy/API-only alias for integration_mode when integration_mode is unset. "
                "Harmony adjusts PCA embeddings; scVI trains on integer counts and writes X_scVI. "
                "Prefer integration_mode in new templates."
            ),
        },
        "batch_key": {
            "type": "string",
            "description": (
                "Metadata (obs) column that identifies which cells came from different samples, "
                "patients, libraries, or sequencing batches. The same column is reused for batch-aware "
                "doublet detection and HVG selection when applicable. The wrong column can cause "
                "overcorrection, weak doublet calls, or misleading HVG results."
            ),
        },
        "n_latent": {
            "type": "integer",
            "default": 30,
            "minimum": 2,
            "description": (
                "Latent dimensionality used by scVI. "
                "Higher values can preserve finer structure, but they increase training time, "
                "memory use, and the risk of modeling noise."
            ),
        },
        "max_epochs": {
            "type": "integer",
            "default": 0,
            "minimum": 0,
            "description": (
                "Maximum training epochs for scVI when enabled. "
                "Higher values usually improve convergence but can dominate total runtime; set to "
                "0 to use scVI's automatic epoch heuristic as a safer quality-versus-speed default."
            ),
        },
        "clustering_method": {
            "type": "string",
            "default": "leiden",
            "enum": ["leiden", "louvain"],
            "description": (
                "Graph clustering algorithm. "
                "Runtime differences are usually small; the main tradeoff is cluster behavior, "
                "with Leiden generally being the safer modern default."
            ),
        },
        "resolution": {
            "type": "number",
            "default": 1.0,
            "minimum": 0.01,
            "maximum": 10.0,
            "description": (
                "Controls how fine or coarse the clustering is. "
                "Higher values often produce more clusters with little runtime penalty, but they "
                "can over-split biologically similar populations."
            ),
        },
        "n_neighbors": {
            "type": "integer",
            "default": 15,
            "minimum": 2,
            "maximum": 200,
            "description": (
                "Neighbor count used for graph construction. "
                "Higher values make the graph smoother and slightly more expensive to build, while "
                "lower values emphasize local structure but can make clustering noisier."
            ),
        },
        "embedding_method": {
            "type": "string",
            "default": "umap",
            "enum": ["umap", "tsne"],
            "description": (
                "Embedding algorithm to compute for visualization. "
                "UMAP is usually faster and scales better, while t-SNE may separate local groups "
                "well but often costs more time."
            ),
        },
        "umap_min_dist": {
            "type": "number",
            "default": 0.5,
            "minimum": 0.0,
            "maximum": 1.0,
            "description": (
                "Controls how tightly UMAP packs points together. "
                "This has little effect on runtime; lower values give tighter visual clusters, "
                "while higher values preserve broader continuity."
            ),
        },
        "tsne_perplexity": {
            "type": "number",
            "default": 30.0,
            "minimum": 1.0,
            "description": (
                "Neighborhood size parameter for t-SNE. "
                "Changing it has modest runtime impact compared with the overall cost of t-SNE, "
                "and the gain is mostly in embedding readability rather than speed."
            ),
        },
        "cluster_key": {
            "type": "string",
            "default": "leiden",
            "description": (
                "obs column containing the active cluster labels used by downstream steps. "
                "This does not affect performance, but pointing to the wrong labels changes "
                "annotation, DE, pathway summaries, and LIANA outputs."
            ),
        },
        "annotation_method": {
            "type": "string",
            "default": "celltypist",
            "enum": [
                "celltypist",
                "conservative",
                "marker_pack",
                "hybrid",
            ],
            "description": (
                "Annotation engine. celltypist (default) uses a CellTypist reference model. "
                "conservative is an audit-first fallback that can abstain. "
                "marker_pack scores clusters with bundled marker YAML. "
                "hybrid combines CellTypist with marker-pack refinement."
            ),
        },
        "annotation_model": {
            "type": "string",
            "default": "auto",
            "enum": [
                "auto",
                "Immune_All_Low.pkl",
                "Immune_All_High.pkl",
                "Human_Lung_Atlas.pkl",
                "Healthy_Human_Liver.pkl",
                "Adult_Mouse_Gut.pkl",
                "Healthy_Mouse_Liver.pkl",
                "custom",
            ],
            "description": (
                "CellTypist model name used for automated annotation. "
                "`auto` picks a species-appropriate default; broader models can take slightly "
                "longer but usually improve coverage; choose `custom` to point at a local or "
                "mounted model file when the curated dropdown does not match your biology."
            ),
        },
        "annotation_model_path": {
            "type": "string",
            "description": (
                "Path to a custom CellTypist model when annotation_model is `custom`. This does "
                "not materially change runtime beyond the model itself; the gain is the ability to "
                "use a domain-specific reference outside the curated dropdown."
            ),
        },
        "annotation_majority_voting": {
            "type": "boolean",
            "default": True,
            "description": (
                "Enable cluster-level majority voting during annotation. "
                "This adds little runtime and often stabilizes noisy single-cell labels, but it can "
                "wash out real within-cluster heterogeneity."
            ),
        },
        "annotation_cluster_key": {
            "type": "string",
            "description": (
                "Cluster key passed to the annotation engine for group-aware heuristics. "
                "This has negligible performance impact; the gain is more coherent labels when the "
                "chosen clustering matches the biology."
            ),
        },
        "annotation_min_prob": {
            "type": "number",
            "default": 0.0,
            "minimum": 0.0,
            "maximum": 1.0,
            "description": (
                "Minimum probability threshold for accepted labels. "
                "This does not change runtime much, but higher thresholds trade coverage for "
                "confidence by leaving more cells unlabeled."
            ),
        },
        "annotation_tissue_context": {
            "type": "string",
            "default": "",
            "description": (
                "Optional tissue context for annotation heuristics. "
                "This has negligible runtime cost and can improve label specificity if the context "
                "is correct."
            ),
        },
        "annotation_cancer_type": {
            "type": "string",
            "description": (
                "Optional cancer-type context for annotation heuristics. "
                "This does not affect performance, but it can improve biological relevance when "
                "the annotation logic uses disease-specific priors."
            ),
        },
        "annotation_species": {
            "type": "string",
            "default": "auto",
            "enum": ["auto", "human", "mouse"],
            "description": (
                "Species expected by the annotation model and related downstream resources. "
                "`auto` infers the species from gene symbols; the wrong explicit species does not "
                "affect runtime much, but it can severely degrade annotation and pathway or "
                "ligand-receptor accuracy."
            ),
        },
        "annotation_marker_pack_path": {
            "type": "string",
            "description": (
                "Optional marker-pack file used for lineage-aware annotation. "
                "Large packs can add some overhead, but they can improve domain-specific accuracy "
                "when the reference model is too generic."
            ),
        },
        "annotation_marker_database": {
            "type": "string",
            "default": "zerna_default",
            "enum": [
                "zerna_default",
                "legacy_zerna_taxonomy",
                "legacy_universal_immune",
                "legacy_universal_stromal",
                "legacy_universal_epithelial",
                "legacy_universal_endothelial",
                "legacy_universal_states",
                "legacy_myeloid_hgm_subtypes",
                "legacy_stromal_hgm_subtypes",
                "custom",
            ],
            "description": (
                "Marker database used by the marker-pack and hybrid annotation modes. The bundled "
                "Zerna pack is the recommended default; the legacy_* entries mirror the older "
                "pan-prostate marker packs for immune, stromal, epithelial, endothelial, "
                "state, hierarchical ZeRNA-style annotation, HGM subtype packs, or the old "
                "pan-prostate merged tissue stack; the `legacy_zerna_*` entries expose the legacy "
                "Zerna JSON corpora used by the v3 annotation agent, including broad markers, "
                "immune and fibroblast subtype panels, tissue-specific markers, cancer-specific "
                "markers, and merged pan-prostate human or mouse stacks; `custom` lets you swap "
                "in a domain-specific marker file at the cost of more manual curation."
            ),
        },
        "annotation_cluster_prior_path": {
            "type": "string",
            "description": (
                "Optional prior-information file for annotation. "
                "This has little runtime cost and can improve results when you have trustworthy "
                "external lineage priors."
            ),
        },
        "annotation_cluster_marker_top_n": {
            "type": "integer",
            "default": 50,
            "minimum": 1,
            "description": (
                "Number of top marker genes used for cluster-level evidence. "
                "Higher values add some annotation-time overhead and may capture more evidence, "
                "but they also introduce more weak or noisy markers."
            ),
        },
        "annotation_min_marker_overlap": {
            "type": "integer",
            "default": 2,
            "minimum": 1,
            "description": (
                "Minimum marker overlap needed to support a lineage call. "
                "This does not materially change performance, but higher values trade sensitivity "
                "for more conservative lineage assignments."
            ),
        },
        "annotation_benchmark_reference_key": {
            "type": "string",
            "description": (
                "Optional obs column containing reference labels for benchmarking. "
                "This adds little runtime but enables coverage, abstention, accuracy, and "
                "confusion reporting for the final annotation calls."
            ),
        },
        "knowledge_pack_version": {
            "type": "string",
            "description": (
                "Optional knowledge-pack version recorded for annotation or pathway provenance. "
                "This has no runtime cost by itself; the gain is reproducibility and clearer audit "
                "trails."
            ),
        },
        "de_mode": {
            "type": "string",
            "default": "marker_ranking",
            "enum": [
                "marker_ranking",
                "condition_de_within_celltype",
                "pseudobulk_sample_level_contrast",
            ],
            "description": (
                "Differential-expression mode. `marker_ranking` runs exploratory Scanpy "
                "`rank_genes_groups` on log-normalized expression. `condition_de_within_celltype` "
                "aggregates raw counts to sample-level pseudobulk within a chosen cluster/cell type "
                "and runs replicate-aware testing. `pseudobulk_sample_level_contrast` aggregates "
                "by sample (optionally stratified by cluster/cell type) for sample-level contrasts."
            ),
        },
        "de_groupby_key": {
            "type": "string",
            "description": (
                "Obs column for grouping: cluster or cell-type labels. Defaults to `cluster_key` "
                "when omitted. Required semantics depend on `de_mode` (subset focus vs stratification)."
            ),
        },
        "de_sample_key": {
            "type": "string",
            "description": (
                "Obs column identifying biological replicate / sample ID. Required for pseudobulk "
                "modes (`condition_de_within_celltype`, `pseudobulk_sample_level_contrast`)."
            ),
        },
        "de_condition_key": {
            "type": "string",
            "description": (
                "Obs column for experimental condition or treatment. Required for pseudobulk "
                "modes. Exactly two condition levels are compared unless `de_reference_level` / "
                "`de_compare_level` or `de_contrast` disambiguates."
            ),
        },
        "de_focus_level": {
            "type": "string",
            "description": (
                "When `de_mode` is `condition_de_within_celltype`, restrict cells to this level "
                "within `de_groupby_key` (single cluster or cell-type label)."
            ),
        },
        "de_reference_level": {
            "type": "string",
            "description": (
                "Reference / control level for the condition contrast (pseudobulk modes)."
            ),
        },
        "de_compare_level": {
            "type": "string",
            "description": (
                "Treatment / comparison level for the condition contrast (pseudobulk modes)."
            ),
        },
        "de_contrast": {
            "type": "string",
            "description": (
                "Optional explicit contrast label of the form `levelA-vs-levelB` for pseudobulk "
                "modes (compare levelA vs reference levelB)."
            ),
        },
        "de_min_cells_per_sample": {
            "type": "integer",
            "default": 10,
            "minimum": 1,
            "description": (
                "Minimum cells per sample-stratum pseudobulk profile to include (pseudobulk modes)."
            ),
        },
        "de_min_samples_per_group": {
            "type": "integer",
            "default": 2,
            "minimum": 2,
            "description": (
                "Minimum distinct samples per condition arm after filtering (pseudobulk modes). "
                "Inferential DE requires at least 2 replicates per arm; the run fails if this cannot be met."
            ),
        },
        "de_padj_method": {
            "type": "string",
            "default": "benjamini-hochberg",
            "description": (
                "Multiple-testing adjustment for marker ranking maps to Scanpy `corr_method`; "
                "for pseudobulk modes, BH FDR is applied to gene-wise p-values."
            ),
        },
        "de_logfc_threshold": {
            "type": "number",
            "default": 0.0,
            "description": (
                "Minimum absolute log fold change for reporting filtered hits (pseudobulk modes; "
                "0 keeps all genes in the table)."
            ),
        },
        "de_method": {
            "type": "string",
            "default": "wilcoxon",
            "enum": ["wilcoxon", "t-test", "t-test_overestim_var", "logreg"],
            "description": (
                "Differential-expression ranking method. "
                "Runtime and statistical behavior vary by method; Wilcoxon is a strong default, "
                "while more complex methods can cost more for potentially better fit in some cases."
            ),
        },
        "de_n_genes": {
            "type": "integer",
            "default": 0,
            "minimum": 0,
            "description": (
                "Top genes to keep per comparison, where 0 keeps all ranked genes. "
                "Keeping fewer genes reduces output size and some downstream inspection overhead, "
                "while keeping all genes preserves full detail."
            ),
        },
        "pathway_scoring": {
            "type": "boolean",
            "default": False,
            "description": (
                "Enable per-cell pathway *activity scoring* (decoupler / PROGENy-style). "
                "Each cell gets pathway activity scores from the expression matrix; this is not "
                "DE-contrast pathway enrichment or inferential testing. Adds noticeable runtime "
                "and memory for large gene sets."
            ),
        },
        "pathway_database": {
            "type": "string",
            "default": "PROGENy",
            "enum": [
                "PROGENy",
                "DoRothEA",
                "Hallmark",
                "KEGG",
                "Reactome",
                "GO_Biological_Process",
                "Custom",
            ],
            "description": (
                "Pathway resource for *cell-level activity scoring*. PROGENy is a fast default; "
                "Hallmark, KEGG, Reactome, and GO broaden coverage; DoRothEA targets TF activity; "
                "Zerna packs match legacy Zerna resources; Custom uses your CSV network."
            ),
        },
        "pathway_method": {
            "type": "string",
            "default": "ulm",
            "enum": ["ulm", "mlm", "aucell", "wsum", "zscore", "ora", "gsva"],
            "description": (
                "decoupler method for per-cell pathway activity scores. ULM is a general default; "
                "MLM can be more stable on weighted nets; AUCell / ORA emphasize ranks or overlap."
            ),
        },
        "pathway_progeny_top": {
            "type": "integer",
            "default": 500,
            "minimum": 50,
            "description": (
                "PROGENy only: number of top target genes per pathway used when building the "
                "scoring network. Higher values retain more targets but increase cost and noise."
            ),
        },
        "pathway_net_path": {
            "type": "string",
            "description": (
                "Custom pathway network CSV (source, target, weight) for activity scoring when "
                "pathway_database is Custom. Required for Custom; local paths suit dev until "
                "uploaded packs are wired."
            ),
        },
        "ligand_receptor": {
            "type": "boolean",
            "default": False,
            "description": (
                "Enable LIANA ligand-receptor analysis after DE or pathway scoring. "
                "This is one of the heavier downstream steps, but it adds cross-cluster signaling "
                "insight that marker-based analysis alone cannot provide."
            ),
        },
        "lr_resource_name": {
            "type": "string",
            "default": "consensus",
            "description": (
                "LIANA resource or consensus database to use. "
                "Different resources change biological coverage more than runtime, so the tradeoff "
                "is mostly accuracy and interpretability for your organism or context."
            ),
        },
        "lr_expr_prop": {
            "type": "number",
            "default": 0.1,
            "minimum": 0.0,
            "maximum": 1.0,
            "description": (
                "Minimum expression proportion required before testing a ligand or receptor. "
                "Higher values reduce the search space and speed LIANA, but they may miss weaker "
                "yet real signaling programs."
            ),
        },
        "lr_min_cells": {
            "type": "integer",
            "default": 5,
            "minimum": 1,
            "description": (
                "Minimum cells required in a cluster before including it in LR analysis. "
                "Higher values reduce runtime and unstable calls, but they can exclude rare "
                "clusters from communication analysis."
            ),
        },
        "lr_n_perms": {
            "type": "integer",
            "default": 100,
            "minimum": 0,
            "description": (
                "Number of permutations used by LIANA where applicable. "
                "More permutations improve stability and significance estimation, but runtime "
                "scales up accordingly."
            ),
        },
        "lr_communication_grouping": {
            "type": "string",
            "default": "auto",
            "enum": [
                "auto",
                "cci_major",
                "cci_minor",
                "cci_fine",
                "cluster",
                "lineage_subcluster",
            ],
            "description": (
                "LIANA groupby: `auto` tries cci_celltype_minor, then fine, then major, then falls "
                "back to the resolved cluster column with recorded provenance (never "
                "`lineage_subcluster`). "
                "`cci_*` modes require the matching cci_celltype_* column from annotation "
                "(no silent cluster fallback). `cluster` uses only the clustering key. "
                "`lineage_subcluster` is optional advanced/exploratory grouping by P2 "
                "`obs['lineage_subcluster']` when that column exists after annotation; not a default."
            ),
        },
        "random_seed": {
            "type": "integer",
            "default": 42,
            "minimum": 0,
            "description": (
                "Global random seed for reproducibility across stochastic steps. "
                "This does not materially affect performance; the gain is easier reruns and more "
                "consistent comparisons."
            ),
        },
    },
    "required": [],
    "allOf": [
        {
            "if": {"properties": {"ambient_correction": {"const": True}}},
            "then": {"required": ["ambient_method"]},
        },
        {
            "if": {"properties": {"batch_correction": {"const": True}}},
            "then": {"required": ["batch_key"]},
        },
        {
            "if": {
                "properties": {"annotation_model": {"const": "custom"}},
                "required": ["annotation_model"],
            },
            "then": {"required": ["annotation_model_path"]},
        },
        {
            "if": {
                "properties": {"annotation_marker_database": {"const": "custom"}},
                "required": ["annotation_marker_database"],
            },
            "then": {"required": ["annotation_marker_pack_path"]},
        },
        {
            "if": {
                "properties": {
                    "pathway_scoring": {"const": True},
                    "pathway_database": {"const": "Custom"},
                },
                "required": ["pathway_scoring", "pathway_database"],
            },
            "then": {"required": ["pathway_net_path"]},
        },
    ],
}

STANDARD_METHODS: list[TemplateMethodEntry] = [
    "qc_filter",
    "doublet_detection",
    {"name": "ambient_correction", "enabled_if": "ambient_correction"},
    "normalize",
    "select_hvg",
    "run_pca",
    {"name": "batch_correct", "enabled_if": "batch_correction"},
    "cluster",
    "embed",
    "annotate",
    "differential_expression",
    {"name": "pathway_scoring", "enabled_if": "pathway_scoring"},
    {"name": "ligand_receptor_analysis", "enabled_if": "ligand_receptor"},
]

LEGACY_PARITY_METHODS: list[TemplateMethodEntry] = [
    "qc_filter",
    "doublet_detection",
    {"name": "ambient_correction", "enabled_if": "ambient_correction"},
    "normalize",
    "select_hvg",
    "run_pca",
    {"name": "batch_correct", "enabled_if": "batch_correction"},
    "cluster",
    "embed",
    "annotate",
    "differential_expression",
    {"name": "pathway_scoring", "enabled_if": "pathway_scoring"},
    {"name": "ligand_receptor_analysis", "enabled_if": "ligand_receptor"},
]


def _method_name(entry: TemplateMethodEntry) -> str:
    if isinstance(entry, str):
        return entry
    return str(entry.get("name", "")).strip()


def get_method_catalog() -> list[dict[str, Any]]:
    """Return a deep copy of the canonical method catalog."""
    return deepcopy(METHOD_CATALOG)


def build_pipeline_dependencies(methods: list[TemplateMethodEntry]) -> dict[str, list[str]]:
    """Build direct dependencies for a selected set of pipeline methods."""
    method_names = [_method_name(entry) for entry in methods if _method_name(entry)]
    selected = set(method_names)
    dependencies: dict[str, list[str]] = {}

    def add(step: str, dependency: str) -> None:
        if step not in selected or dependency not in selected:
            return
        dependencies.setdefault(step, [])
        if dependency not in dependencies[step]:
            dependencies[step].append(dependency)

    if "doublet_detection" in selected:
        add("doublet_detection", "qc_filter")

    if "ambient_correction" in selected:
        if "doublet_detection" in selected:
            add("ambient_correction", "doublet_detection")
        else:
            add("ambient_correction", "qc_filter")

    if "normalize" in selected:
        if "ambient_correction" in selected:
            add("normalize", "ambient_correction")
        elif "doublet_detection" in selected:
            add("normalize", "doublet_detection")
        else:
            add("normalize", "qc_filter")

    add("select_hvg", "normalize")
    add("run_pca", "select_hvg")

    has_batch_step = any(
        step in selected
        for step in (
            "batch_correct",
            "batch_correction",
            "batch_correction_harmony",
            "batch_correction_scvi",
        )
    )
    batch_step = next(
        (
            step
            for step in (
                "batch_correct",
                "batch_correction",
                "batch_correction_harmony",
                "batch_correction_scvi",
            )
            if step in selected
        ),
        None,
    )
    if batch_step:
        add(batch_step, "run_pca")

    cluster_parent = batch_step or "run_pca"
    embed_parent = batch_step or "run_pca"

    add("cluster", cluster_parent)
    if "embed" in selected:
        add("embed", embed_parent)
    if "umap" in selected:
        add("umap", embed_parent)
    if "tsne" in selected:
        add("tsne", embed_parent)

    annotation_parent = "cluster" if "cluster" in selected else cluster_parent
    add("annotate", annotation_parent)

    de_parent = "annotate" if "annotate" in selected else annotation_parent
    add("differential_expression", de_parent)

    pathway_parent = (
        "differential_expression" if "differential_expression" in selected else de_parent
    )
    add("pathway_scoring", pathway_parent)

    lr_parent = (
        "pathway_scoring"
        if "pathway_scoring" in selected
        else ("differential_expression" if "differential_expression" in selected else de_parent)
    )
    add("ligand_receptor_analysis", lr_parent)

    return {step: deps for step, deps in dependencies.items() if deps}


def normalize_pipeline_template_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Merge any missing dependency edges from the current catalog rules (non-destructive to DB).

    Older templates may omit edges introduced after they were created (for example
    ``normalize`` → ``ambient_correction``). This adds only **missing** edges required by
    ``build_pipeline_dependencies``; it does not remove user-defined edges.
    """
    if not isinstance(definition, dict):
        return definition
    methods = definition.get("methods")
    if not isinstance(methods, list) or not methods:
        return definition
    stored = definition.get("dependencies")
    if not isinstance(stored, dict):
        stored = {}
    canonical = build_pipeline_dependencies(methods)
    merged: dict[str, list[str]] = {k: list(v) for k, v in stored.items()}
    merged_any = False
    for step, deps in canonical.items():
        existing = set(merged.get(step, []))
        for dep in deps:
            if dep not in existing:
                merged.setdefault(step, []).append(dep)
                existing.add(dep)
                merged_any = True
    out = dict(definition)
    out["dependencies"] = {k: v for k, v in merged.items() if v}
    if merged_any:
        meta = dict(out.get("metadata") or {})
        meta["dependency_edges_merged_from_catalog"] = True
        out["metadata"] = meta
    return out


def build_pipeline_definition(
    methods: list[TemplateMethodEntry],
    *,
    description: str,
    recommended: bool = False,
    template_family: str | None = None,
    deprecated: bool = False,
    visible_in_picker: bool = True,
) -> dict[str, Any]:
    """Build a canonical pipeline definition from methods and schema defaults."""
    return {
        "methods": deepcopy(methods),
        "dependencies": build_pipeline_dependencies(methods),
        "parameter_schema": deepcopy(FULL_PARAMETER_SCHEMA),
        "metadata": {
            "description": description,
            "recommended": recommended,
            "template_family": template_family,
            "deprecated": deprecated,
            "visible_in_picker": visible_in_picker,
            "seeded": True,
        },
    }


def merge_template_presentation_metadata(
    definition: dict[str, Any],
    *,
    name: str,
    version: str,
) -> dict[str, Any]:
    """Ensure ``deprecated`` / ``visible_in_picker`` / ``recommended`` exist for API + UI.

    Seeded templates carry explicit flags. Older database rows may omit them; this fills
    defaults using ``template_family`` or canonical name+version without overriding stored values.
    """
    if not isinstance(definition, dict):
        return definition
    meta = dict(definition.get("metadata") or {})
    family = meta.get("template_family")

    def legacy_defaults() -> None:
        meta.setdefault("deprecated", True)
        meta.setdefault("visible_in_picker", False)
        meta.setdefault("recommended", False)

    def standard_defaults() -> None:
        meta.setdefault("deprecated", False)
        meta.setdefault("visible_in_picker", True)
        meta.setdefault("recommended", True)

    if family == "legacy_parity":
        legacy_defaults()
    elif family == "standard":
        standard_defaults()
    elif name == "scRNA-seq Legacy Parity" and version == "1.6.0":
        legacy_defaults()
    elif name == "scRNA-seq Standard" and version == "1.7.0":
        standard_defaults()
    else:
        meta.setdefault("deprecated", bool(meta.get("deprecated", False)))
        meta.setdefault("visible_in_picker", not meta.get("deprecated", False))
        meta.setdefault("recommended", bool(meta.get("recommended", False)))

    out = dict(definition)
    out["metadata"] = meta
    return out


def get_seed_template_specs() -> list[dict[str, Any]]:
    """Return seeded template specs for synchronization/bootstrap."""
    return [
        {
            "name": "scRNA-seq Standard",
            "version": "1.7.0",
            "definition": build_pipeline_definition(
                STANDARD_METHODS,
                description=(
                    "Zerna’s recommended scRNA-seq path: QC, doublets, normalization and HVGs, PCA, "
                    "optional Harmony or scVI integration, clustering and UMAP with provenance, "
                    "annotation, and optional DE, pathway scoring, and ligand–receptor analysis. "
                    "Use Advanced for tuning and optional ambient correction. Multi-file and 10x "
                    "uploads are supported with concat diagnostics."
                ),
                recommended=True,
                template_family="standard",
                deprecated=False,
                visible_in_picker=True,
            ),
        },
        {
            "name": "scRNA-seq Legacy Parity",
            "version": "1.6.0",
            "definition": build_pipeline_definition(
                LEGACY_PARITY_METHODS,
                description=(
                    "Deprecated — kept only for backward compatibility with older runs. "
                    "Step layout mirrors a legacy Zerna-style path on the current executor; "
                    "new analyses should use scRNA-seq Standard v1.7.0."
                ),
                recommended=False,
                template_family="legacy_parity",
                deprecated=True,
                visible_in_picker=False,
            ),
        },
    ]
