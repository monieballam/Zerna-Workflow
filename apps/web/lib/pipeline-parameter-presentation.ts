export type TemplateMethodEntry =
  | string
  | {
      name?: string;
      params?: Record<string, unknown>;
      enabled_if?: string | string[];
    };

export type ParameterSectionConfig = {
  id: string;
  title: string;
  description: string;
  methods?: string[];
  fields: string[];
  fullWidth?: boolean;
  /**
   * When false, the main run-form section renders as a collapsed `<details>` block.
   * Omitted or true keeps the section expanded (open) by default.
   */
  defaultExpanded?: boolean;
};

/** UI labels for `de_mode` enum values (backend / schema values unchanged). */
export const DE_MODE_SELECT_OPTIONS: { value: string; label: string }[] = [
  { value: 'marker_ranking', label: 'Marker ranking' },
  { value: 'condition_de_within_celltype', label: 'Condition DE within cell type' },
  { value: 'pseudobulk_sample_level_contrast', label: 'Pseudobulk sample-level contrast' },
];

/** Richer copy for the run form (shown under the DE mode control). */
export const DE_MODE_DETAIL_GUIDANCE: Record<
  string,
  { headline: string; body: string; keys?: string }
> = {
  marker_ranking: {
    headline: 'Exploratory (cell-level)',
    body: 'Ranks marker genes per cluster or group using a Scanpy-style test on log-normalized expression. Fast and simple; not a replicate-aware sample-level model. No extra sample/condition columns required for basic use.',
  },
  condition_de_within_celltype: {
    headline: 'Replicate-aware within a subset',
    body: 'Pseudobulk contrasts within a cell-type or stratum using explicit sample and condition columns. Use when you have biological replicates and want inference at sample level inside a focused population.',
    keys: 'Requires de_sample_key, de_condition_key, and de_groupby_key / focus settings as configured in Advanced.',
  },
  pseudobulk_sample_level_contrast: {
    headline: 'Replicate-aware sample-level',
    body: 'Aggregates counts per sample and runs a count-model contrast between conditions. Appropriate for experiment-wide treatment effects with replicates.',
    keys: 'Requires de_sample_key and de_condition_key (and contrast levels or de_contrast as applicable).',
  },
};

/** Main-form sections that are primarily biological context (emphasized in the UI). */
export const RUN_FORM_BIOLOGY_FIRST_SECTION_IDS = new Set([
  'batch_main',
  'annotation_context_main',
  'de_main',
  'optional_main',
]);

/** Subsections inside the single collapsed “Advanced settings” block on the run form */
export type RunFormAdvancedGroupConfig = {
  id: string;
  title: string;
  /** Optional subsection blurb under the title (e.g. optional advanced preprocessing). */
  description?: string;
  methods?: string[];
  fields: string[];
};

export function getMethodName(entry: TemplateMethodEntry): string {
  return typeof entry === 'string' ? entry : String(entry.name ?? '');
}

/** Steps shown in the pre-launch pipeline summary: respects ``enabled_if`` flags like the worker. */
export function filterMethodsForLaunchPreview(
  methods: TemplateMethodEntry[],
  paramValues: Record<string, unknown>
): TemplateMethodEntry[] {
  return methods.filter((entry) => {
    if (typeof entry === 'string') return true;
    const gate = entry.enabled_if;
    if (gate == null) return true;
    if (typeof gate === 'string') return Boolean(paramValues[gate]);
    if (Array.isArray(gate)) return gate.every((key) => Boolean(paramValues[key]));
    return Boolean(gate);
  });
}

export type LrCommunicationGroupingSelectOption = { value: string; label: string };

const LR_GROUPING_SELECT_ORDER = [
  'auto',
  'cci_major',
  'cci_minor',
  'cci_fine',
  'cluster',
  'lineage_subcluster',
] as const;

const LR_GROUPING_SELECT_LABELS: Record<string, string> = {
  auto: 'auto — canonical CCI tiers, then cluster (default)',
  cci_major: 'cci_major — cci_celltype_major (strict)',
  cci_minor: 'cci_minor — cci_celltype_minor (strict)',
  cci_fine: 'cci_fine — cci_celltype_fine (strict)',
  cluster: 'cluster — clustering column only',
  lineage_subcluster:
    'lineage_subcluster — advanced / exploratory (P2 lineage_subcluster partitions)',
};

/** Builds LR grouping `<select>` options from the template enum, optionally exposing P2 lineage mode. */
export function buildLrCommunicationGroupingSelectOptions(args: {
  schemaEnum: unknown[] | undefined;
  showLineageSubcluster: boolean;
}): LrCommunicationGroupingSelectOption[] {
  const allowed = new Set(
    (args.schemaEnum ?? [])
      .map((v) => {
        if (v == null) return '';
        if (typeof v === 'string') return v;
        if (typeof v === 'number' || typeof v === 'boolean' || typeof v === 'bigint') {
          return String(v);
        }
        return '';
      })
      .filter(Boolean)
  );
  if (allowed.size === 0) return [];
  return LR_GROUPING_SELECT_ORDER.filter(
    (v) => allowed.has(v) && (v !== 'lineage_subcluster' || args.showLineageSubcluster)
  ).map((v) => ({ value: v, label: LR_GROUPING_SELECT_LABELS[v] ?? v }));
}

/**
 * Offer lineage_subcluster LR grouping only when the input matrix already has the column,
 * or when the launch preview includes annotation (P2 can populate lineage_subcluster before LR).
 */
export function shouldOfferLineageSubclusterLrGrouping(args: {
  datasetObsColumns: string[] | undefined;
  launchPreviewMethodNames: string[];
}): boolean {
  if (args.datasetObsColumns?.includes('lineage_subcluster')) return true;
  return args.launchPreviewMethodNames.includes('annotate');
}

export function formatFieldValue(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return JSON.stringify(value);
}

export function formatParameterValue(value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'boolean') return value ? 'Enabled' : 'Disabled';
  if (Array.isArray(value)) return value.map((item) => formatFieldValue(item)).join(', ');
  return formatFieldValue(value);
}

export const METHOD_INFO: Record<string, { label: string; description: string }> = {
  qc: {
    label: 'QC & Filtering',
    description:
      'Remove low-quality cells and genes based on mitochondrial %, gene counts, and UMI counts.',
  },
  qc_filter: {
    label: 'QC & Filtering',
    description:
      'Remove low-quality cells and genes using species-aware mitochondrial detection, gene counts, and optional blood / housekeeping filters.',
  },
  doublet_detection: {
    label: 'Doublet Detection',
    description:
      'Score likely doublets on raw counts (after QC, before normalization) using Scrublet or SOLO. Legacy backends remain available via API for older templates.',
  },
  normalize: {
    label: 'Normalization',
    description: 'Library-size normalization and log1p transformation.',
  },
  select_hvg: {
    label: 'HVG Selection',
    description:
      'Select highly variable genes for downstream PCA and clustering. This step marks HVGs in the object but does not subset genes immediately.',
  },
  pca: { label: 'PCA', description: 'Principal component analysis for dimensionality reduction.' },
  run_pca: {
    label: 'PCA',
    description: 'Principal component analysis for dimensionality reduction.',
  },
  batch_correction: {
    label: 'Batch Correction',
    description: 'Correct for batch effects across samples (Harmony / scVI).',
  },
  batch_correct: {
    label: 'Batch Correction',
    description: 'Correct for batch effects across samples (Harmony / scVI).',
  },
  batch_correction_harmony: {
    label: 'Batch Correction (Harmony)',
    description: 'Correct for batch effects across samples using Harmony.',
  },
  batch_correction_scvi: {
    label: 'Batch Correction (scVI)',
    description: 'Correct for batch effects across samples using scVI.',
  },
  cluster: {
    label: 'Clustering',
    description: 'Leiden / Louvain community detection on the neighbor graph.',
  },
  umap: { label: 'Embedding (UMAP)', description: '2-D UMAP embedding for visualization.' },
  tsne: { label: 'Embedding (t-SNE)', description: '2-D t-SNE embedding for visualization.' },
  embed: { label: 'Embedding (UMAP/t-SNE)', description: '2-D embedding for visualization.' },
  annotate: {
    label: 'Cell-Type Annotation',
    description:
      'Default product path uses CellTypist on the main pipeline object, aligned with upstream Leiden/Louvain clusters and log-normalized expression. Cancer type and species are the main run-form controls; engine and tuning options stay under Advanced settings.',
  },
  differential_expression: {
    label: 'Differential Expression',
    description:
      'Unified DE: exploratory marker ranking (Scanpy) or replicate-aware pseudobulk contrasts with explicit sample and condition keys.',
  },
  pathway_scoring: {
    label: 'Pathway Activity Scoring',
    description:
      'Per-cell pathway activity scores (decoupler / PROGENy-style resources). This is exploratory scoring from single-cell expression—not DE-contrast enrichment or sample-level inference. Resource and method live under Advanced.',
  },
  ligand_receptor: {
    label: 'Ligand–Receptor Analysis',
    description:
      'LIANA rank_aggregate on ligand–receptor resources. Grouping: auto prefers annotation cci_celltype_* columns then cluster (fallback is provenance-recorded); explicit cci_* requires those columns.',
  },
  ligand_receptor_analysis: {
    label: 'Ligand–Receptor Analysis',
    description:
      'LIANA rank_aggregate on ligand–receptor resources. Grouping: auto prefers annotation cci_celltype_* columns then cluster (fallback is provenance-recorded); explicit cci_* requires those columns.',
  },
  ambient_correction: {
    label: 'Ambient RNA correction',
    description:
      'Optional advanced preprocessing when you suspect strong background RNA. Usually not needed for every dataset. SoupX is available through an R helper using a filtered-counts-only approximation; Identity only copies counts for provenance.',
  },
};

/** Passed only via API / templates; never shown on the default run form. */
export const QC_PROGRAMMATIC_ONLY_FIELDS = [
  'mito_prefix',
  'ribo_prefixes',
  'hb_gene_names',
  'hk_gene_names',
] as const;

/** Legacy / expert doublet inputs — not shown on the main run form (advanced or API only). */
export const DOUBLET_PROGRAMMATIC_ONLY_FIELDS = [
  'filter_doublets',
  'doublet_threshold',
  'solo_batch_size',
  'solo_gene_likelihood',
  'solo_max_epochs',
  'doubletdetection_voter_thresh',
  'doubletdetection_p_thresh',
] as const;

/** Legacy batch engine alias — use integration_mode in the UI; API/templates may still send this. */
export const BATCH_INTEGRATION_PROGRAMMATIC_ONLY_FIELDS = ['batch_method'] as const;

/** Template/API may still send this; it is not shown on the run form (annotation path does not use tissue-specific context in the product UI). */
export const ANNOTATION_FORM_HIDDEN_FIELDS = ['annotation_tissue_context'] as const;

function batchIntegrationIsScvi(values: Record<string, unknown>): boolean {
  const im = values.integration_mode;
  if (im === 'scvi') return true;
  if (im === 'harmony') return false;
  return values.batch_method === 'scvi';
}

function hasNonEmptyString(values: Record<string, unknown>, key: string): boolean {
  const v = values[key];
  return typeof v === 'string' && v.trim().length > 0;
}

export const PARAM_LABELS: Record<string, string> = {
  qc_species: 'QC species',
  filter_by_housekeeping: 'Filter by housekeeping fraction',
  max_genes: 'Max genes per cell',
  max_mito_pct: 'Max mitochondrial %',
  mito_prefix: 'Mitochondrial gene prefix (legacy override)',
  expected_doublet_rate: 'Expected doublet rate',
  doublet_method: 'Doublet detection method',
  doublet_mode: 'Doublet handling',
  doublet_threshold: 'Doublet score threshold',
  solo_batch_size: 'SOLO batch size',
  solo_gene_likelihood: 'SOLO gene likelihood',
  solo_max_epochs: 'SOLO max epochs',
  doubletdetection_voter_thresh: 'DoubletDetection voter threshold',
  doubletdetection_p_thresh: 'DoubletDetection p-value threshold',
  filter_doublets: 'Remove predicted doublets',
  doublet_sample_key: 'Per-sample column for doublets',
  min_counts: 'Min UMI counts per cell',
  max_counts: 'Max UMI counts per cell',
  max_ribo_pct: 'Max ribosomal %',
  max_hk_pct: 'Max housekeeping-associated %',
  compute_hb_pct: 'Hemoglobin QC (blood-rich samples)',
  max_hb_pct: 'Max hemoglobin %',
  ribo_prefixes: 'Ribosomal gene prefixes (override)',
  hb_gene_names: 'Hemoglobin genes (override)',
  hk_gene_names: 'Housekeeping genes (override)',
  ambient_correction: 'Ambient RNA correction (optional advanced)',
  ambient_method: 'Ambient correction mode (Off / Identity / SoupX)',
  integration_mode: 'Integration method (Harmony vs scVI)',
  target_sum: 'Target normalization sum',
  min_genes: 'Min genes per cell',
  min_cells: 'Min cells per gene',
  n_top_genes: 'Number of HVGs (highly variable genes)',
  hvg_flavor: 'HVG selection flavor',
  hvg_batch_key: 'HVG batch column (batch-aware selection)',
  n_pcs: 'Number of principal components',
  batch_correction: 'Enable batch correction',
  batch_method: 'Batch correction backend (legacy API only)',
  batch_key: 'Sample or batch ID column',
  n_latent: 'scVI latent dimensions',
  max_epochs: 'scVI max epochs',
  clustering_method: 'Clustering method',
  resolution: 'Clustering resolution',
  n_neighbors: 'Number of neighbors (k)',
  embedding_method: 'Embedding method',
  umap_min_dist: 'UMAP min distance',
  tsne_perplexity: 't-SNE perplexity',
  cluster_key: 'Cluster key',
  annotation_method: 'Annotation engine',
  annotation_model: 'Annotation model',
  annotation_model_path: 'Custom annotation model path',
  annotation_majority_voting: 'Enable majority voting',
  annotation_cluster_key: 'Annotation cluster key',
  annotation_min_prob: 'Minimum annotation probability',
  annotation_tissue_context: 'Tissue context',
  annotation_cancer_type: 'Cancer type context',
  annotation_species: 'Species',
  annotation_marker_database: 'Marker database',
  annotation_marker_pack_path: 'Marker pack path',
  annotation_cluster_prior_path: 'Cluster prior path',
  annotation_cluster_marker_top_n: 'Top markers per cluster',
  annotation_min_marker_overlap: 'Minimum marker overlap',
  knowledge_pack_version: 'Knowledge pack version',
  annotation_benchmark_reference_key: 'Benchmark reference labels column',
  de_mode: 'Differential expression mode',
  de_groupby_key: 'DE group-by column (cluster or cell type)',
  de_sample_key: 'Sample / replicate ID column (pseudobulk)',
  de_condition_key: 'Condition column (pseudobulk contrast)',
  de_focus_level: 'Subset label within group-by (within-cell-type DE)',
  de_reference_level: 'Reference condition level',
  de_compare_level: 'Comparison condition level',
  de_contrast: 'Explicit contrast (e.g. A_vs_B)',
  de_min_cells_per_sample: 'Min cells per pseudobulk profile',
  de_min_samples_per_group: 'Min samples per condition arm',
  de_padj_method: 'Multiple testing adjustment',
  de_logfc_threshold: 'Min |log fold change| for filtered hits',
  de_method: 'Marker ranking test (Scanpy)',
  de_n_genes: 'Top marker genes per group',
  pathway_scoring: 'Enable pathway activity scoring',
  pathway_database: 'Pathway resource (activity scoring)',
  pathway_method: 'Activity scoring method (decoupler)',
  pathway_progeny_top: 'PROGENy top targets',
  pathway_net_path: 'Pathway network file',
  ligand_receptor: 'Enable ligand-receptor analysis',
  lr_resource_name: 'LIANA resource',
  lr_expr_prop: 'Min expression proportion',
  lr_min_cells: 'Min cells per cluster',
  lr_n_perms: 'Permutation count',
  lr_communication_grouping: 'LR communication grouping',
  random_seed: 'Random seed',
};

/**
 * Concise run-form helper copy (shown with each control). Keeps schema `description`
 * as optional extra detail from the API when no entry exists here.
 */
export const PARAM_FIELD_HELP: Record<string, string> = {
  batch_key:
    'Select the metadata column that identifies which cells came from different samples, patients, libraries, or sequencing batches.',
  ambient_correction:
    'Optional advanced step for datasets with suspected background RNA contamination. Usually not needed for every dataset. Off: no ambient step runs. On: SoupX uses an R helper with the filtered counts matrix only, while Identity just copies counts for provenance.',
  ambient_method:
    'Off — no ambient processing. Identity — copies raw counts to corrected_counts for pipeline provenance only; no biological ambient removal. SoupX — runs through an R helper using the filtered counts matrix as both toc and tod because raw empty-droplet counts are not available at this stage.',
  expected_doublet_rate:
    'Doublets are technical multiplets where two (or more) cells are captured in one droplet. They are usually filtered or flagged before normalization and downstream analysis.',
  filter_doublets:
    'When enabled, predicted doublets are removed before later steps. Doublets are technical artifacts, not biological cell states.',
  doublet_method:
    'Doublets are technical multiplets (two cells in one droplet). Choose a detection backend; predicted doublets are typically removed before downstream analysis.',
  batch_correction:
    'Biological / study design choice: enable when technical differences between samples, patients, or library batches should be softened before clustering and annotation. Pick a batch column that identifies those technical splits — avoid using the primary treatment variable as batch unless it is truly confounded with batch. Integration increases memory use on large objects.',
  integration_mode:
    'Harmony adjusts PCA coordinates (usually lighter on memory). scVI learns a latent space from counts (often heavier). Downstream steps follow zerna_active_representation. Fixed workflow defaults apply for iteration counts unless overridden via API.',
  annotation_method:
    'Default for new runs: CellTypist. Choose conservative for the audit-first, abstaining engine if you need maximum caution with explicit evidence trails.',
  qc_species:
    'Human and mouse use curated mitochondrial and hemoglobin matching. Auto-detect reads your feature names; if the signal is mixed or weak, pick the species explicitly.',
  filter_by_housekeeping:
    'Uses species-appropriate housekeeping genes (e.g. MALAT1/NEAT1 vs Malat1/Neat1) to cap ambient-like signal when enabled.',
  compute_hb_pct:
    'Computes hemoglobin fraction with species-appropriate gene symbols. Enable for blood-rich samples; a sensible default max fraction applies when turned on.',
  n_top_genes:
    'How many top highly variable genes to mark for PCA and downstream steps. Genes stay in the matrix; this only sets the highly_variable flag.',
  hvg_flavor:
    'Scanpy HVG algorithm: seurat_v3 prefers raw counts in the counts layer when present; seurat and cell_ranger use the active expression matrix (adata.X).',
  hvg_batch_key:
    'Optional obs column for batch-aware HVG selection. Shown when batch correction is enabled or a batch/sample column is already selected.',
  de_mode:
    'Choose how differential expression is performed. Marker ranking is exploratory at cell level; pseudobulk modes are replicate-aware and need explicit sample/condition columns (see guidance under the menu).',
  annotation_cancer_type:
    'Disease context passed to the annotation engine (e.g. tumor type). Improves priors and marker context; does not replace careful review in the explorer.',
  annotation_species:
    'Species for gene naming and QC (human vs mouse vs auto-detect). Should match your feature names and annotation model.',
  pathway_scoring:
    'Exploratory per-cell pathway activity scores (not sample-level enrichment). Adds compute and memory on large objects; useful for hypothesis generation after core clustering looks stable.',
  ligand_receptor:
    'Heavier cell–cell communication inference (LIANA). Best when clusters or annotation groups are stable. Expect longer runtime and higher memory than pathway scoring alone.',
  lr_communication_grouping:
    'LIANA groupby: auto tries cci_celltype_minor → fine → major (annotation outputs), then cluster with provenance—never lineage_subcluster by default. cci_* modes require those cci_celltype_* columns—no silent cluster fallback. cluster uses only the clustering key. lineage_subcluster is an optional advanced / exploratory mode (P2 partitions) shown only when the dataset already has that column or the launch includes annotation so P2 can populate it before LR; small groups are still dropped by min cells per group.',
};

export function getParameterFieldHelp(name: string): string | undefined {
  return PARAM_FIELD_HELP[name];
}

/** Default run form: biology-first controls always visible */
export const RUN_FORM_MAIN_SECTIONS: ParameterSectionConfig[] = [
  {
    id: 'qc_main',
    title: 'Quality Control',
    description:
      'Filter low-quality cells and rare genes before analysis. Stricter settings remove more cells but can drop rare biology.',
    methods: ['qc', 'qc_filter'],
    fields: ['min_genes', 'max_genes', 'min_cells', 'max_mito_pct'],
    defaultExpanded: true,
    fullWidth: true,
  },
  {
    id: 'doublets_main',
    title: 'Doublets',
    description:
      'Doublets are droplets containing two or more cells. Detection runs on raw counts after QC, before normalization.',
    methods: ['doublet_detection'],
    fields: ['doublet_method'],
    defaultExpanded: false,
    fullWidth: true,
  },
  {
    id: 'batch_main',
    title: 'Batch correction',
    description:
      'Biological / study design: harmonize technical differences across samples or batches. When enabled, pick the batch column under Advanced — it should reflect technical structure, not your main scientific contrast unless those coincide.',
    methods: [
      'batch_correct',
      'batch_correction',
      'batch_correction_harmony',
      'batch_correction_scvi',
    ],
    fields: ['batch_correction'],
    defaultExpanded: false,
    fullWidth: true,
  },
  {
    id: 'annotation_context_main',
    title: 'Annotation context',
    description:
      'Biological context for annotation: cancer/tissue type and species. These tune the default annotation engine; results should still be reviewed in the explorer.',
    methods: ['annotate'],
    fields: ['annotation_cancer_type', 'annotation_species'],
    defaultExpanded: true,
    fullWidth: true,
  },
  {
    id: 'cluster_main',
    title: 'Clustering',
    description:
      'Resolution controls cluster granularity; neighbor count and algorithm choice live under Advanced.',
    methods: ['cluster'],
    fields: ['resolution'],
    defaultExpanded: false,
    fullWidth: true,
  },
  {
    id: 'de_main',
    title: 'Differential expression',
    description:
      'Biological analysis choice: marker ranking is exploratory; pseudobulk modes are replicate-aware and require sample/condition keys (Advanced). Pick the mode that matches your experimental design.',
    methods: ['differential_expression'],
    fields: ['de_mode'],
    defaultExpanded: false,
    fullWidth: true,
  },
  {
    id: 'optional_main',
    title: 'Optional analyses',
    description:
      'Downstream add-ons after core QC–cluster–annotate. Pathway scoring is exploratory per-cell signal; ligand–receptor is heavier and needs stable groups. Disable both on very large or merged runs if memory is tight.',
    methods: ['pathway_scoring', 'ligand_receptor', 'ligand_receptor_analysis'],
    fields: ['pathway_scoring', 'ligand_receptor'],
    defaultExpanded: true,
    fullWidth: true,
  },
];

/** Expert tuning inside one collapsed “Advanced settings” region */
export const RUN_FORM_ADVANCED_GROUPS: RunFormAdvancedGroupConfig[] = [
  {
    id: 'doublet_advanced',
    title: 'Doublet detection advanced',
    methods: ['doublet_detection'],
    fields: [
      'expected_doublet_rate',
      'doublet_mode',
      'doublet_sample_key',
      'doublet_threshold',
      'solo_batch_size',
      'solo_gene_likelihood',
      'solo_max_epochs',
      'doubletdetection_voter_thresh',
      'doubletdetection_p_thresh',
    ],
  },
  {
    id: 'ambient_preprocessing_advanced',
    title: 'Ambient RNA correction',
    description:
      'Optional advanced preprocessing for datasets with suspected ambient or background RNA contamination. Usually not needed for every dataset.',
    methods: ['ambient_correction'],
    fields: ['ambient_correction', 'ambient_method'],
  },
  {
    id: 'feature_advanced',
    title: 'HVG Selection, normalization & PCA (advanced)',
    description:
      'Default HVG settings are recommended for most datasets. Tune counts target and PCA dimensionality here when needed.',
    methods: ['normalize', 'select_hvg', 'pca', 'run_pca'],
    fields: ['n_top_genes', 'hvg_flavor', 'hvg_batch_key', 'target_sum', 'n_pcs'],
  },
  {
    id: 'batch_advanced',
    title: 'Batch correction advanced',
    description:
      'Choose Harmony (PCA) vs scVI (counts latent). scVI latent size and training epochs appear only when scVI is selected; Harmony iteration count and scVI hidden layers stay at workflow defaults unless set via API.',
    methods: [
      'batch_correct',
      'batch_correction',
      'batch_correction_harmony',
      'batch_correction_scvi',
    ],
    fields: ['batch_key', 'integration_mode', 'n_latent', 'max_epochs'],
  },
  {
    id: 'cluster_embed_advanced',
    title: 'Clustering and embedding advanced',
    methods: ['cluster', 'embed', 'umap', 'tsne'],
    fields: [
      'clustering_method',
      'n_neighbors',
      'embedding_method',
      'umap_min_dist',
      'tsne_perplexity',
      'cluster_key',
    ],
  },
  {
    id: 'annotation_advanced',
    title: 'Annotation advanced',
    methods: ['annotate'],
    fields: [
      'annotation_method',
      'annotation_model',
      'annotation_model_path',
      'annotation_majority_voting',
      'annotation_cluster_key',
      'annotation_min_prob',
      'annotation_marker_database',
      'annotation_marker_pack_path',
      'annotation_cluster_prior_path',
      'annotation_cluster_marker_top_n',
      'annotation_min_marker_overlap',
      'knowledge_pack_version',
      'annotation_benchmark_reference_key',
    ],
  },
  {
    id: 'de_advanced',
    title: 'Differential expression advanced',
    description:
      'Mode-specific columns and statistics appear here after you choose a DE mode on the main form.',
    methods: ['differential_expression'],
    fields: [
      'de_groupby_key',
      'de_sample_key',
      'de_condition_key',
      'de_focus_level',
      'de_method',
      'de_n_genes',
      'de_reference_level',
      'de_compare_level',
      'de_contrast',
      'de_min_cells_per_sample',
      'de_min_samples_per_group',
      'de_padj_method',
      'de_logfc_threshold',
    ],
  },
  {
    id: 'pathway_lr_advanced',
    title: 'Pathway and ligand–receptor advanced',
    methods: ['pathway_scoring', 'ligand_receptor', 'ligand_receptor_analysis'],
    fields: [
      'pathway_database',
      'pathway_method',
      'pathway_progeny_top',
      'pathway_net_path',
      'lr_resource_name',
      'lr_communication_grouping',
      'lr_expr_prop',
      'lr_min_cells',
      'lr_n_perms',
    ],
  },
  {
    id: 'qc_advanced',
    title: 'QC advanced',
    methods: ['qc', 'qc_filter'],
    fields: [
      'qc_species',
      'min_counts',
      'max_counts',
      'max_ribo_pct',
      'compute_hb_pct',
      'max_hb_pct',
      'filter_by_housekeeping',
      'max_hk_pct',
    ],
  },
  {
    id: 'repro_advanced',
    title: 'Reproducibility',
    fields: ['random_seed'],
  },
];

/** Every field assigned to main or advanced run form layout (for “additional parameters” detection). */
export function getRunFormManagedFieldNames(): string[] {
  const main = RUN_FORM_MAIN_SECTIONS.flatMap((s) => s.fields);
  const adv = RUN_FORM_ADVANCED_GROUPS.flatMap((g) => g.fields);
  return [
    ...new Set([
      ...main,
      ...adv,
      ...QC_PROGRAMMATIC_ONLY_FIELDS,
      ...DOUBLET_PROGRAMMATIC_ONLY_FIELDS,
      ...BATCH_INTEGRATION_PROGRAMMATIC_ONLY_FIELDS,
      ...ANNOTATION_FORM_HIDDEN_FIELDS,
    ]),
  ];
}

/**
 * Full section list for run detail, template editor dependencies, and any code that expects
 * phase-grouped parameters (legacy layout).
 */
export const PARAMETER_SECTIONS: ParameterSectionConfig[] = [
  {
    id: 'qc',
    title: 'Quality Control',
    description: 'Filtering thresholds used before downstream analysis starts.',
    methods: ['qc', 'qc_filter'],
    fields: [
      'qc_species',
      'min_genes',
      'max_genes',
      'min_cells',
      'max_mito_pct',
      'min_counts',
      'max_counts',
      'max_ribo_pct',
      'filter_by_housekeeping',
      'max_hk_pct',
      'compute_hb_pct',
      'max_hb_pct',
      'mito_prefix',
      'ribo_prefixes',
      'hb_gene_names',
      'hk_gene_names',
    ],
  },
  {
    id: 'doublets',
    title: 'Doublet Detection',
    description: 'Controls for scoring and removing likely multiplets.',
    methods: ['doublet_detection'],
    fields: [
      'doublet_method',
      'expected_doublet_rate',
      'doublet_mode',
      'doublet_sample_key',
      'doublet_threshold',
      'solo_batch_size',
      'solo_gene_likelihood',
      'solo_max_epochs',
      'doubletdetection_voter_thresh',
      'doubletdetection_p_thresh',
      'filter_doublets',
    ],
  },
  {
    id: 'ambient',
    title: 'Ambient RNA correction (advanced optional)',
    description:
      'Optional advanced preprocessing for suspected background contamination. SoupX uses an R helper with a filtered-counts-only approximation; Identity copies counts for provenance and does not remove ambient RNA.',
    methods: ['ambient_correction'],
    fields: ['ambient_correction', 'ambient_method'],
  },
  {
    id: 'features',
    title: 'Normalization, HVG selection, and PCA',
    description:
      'Normalization target, HVG Selection (number and flavor), optional batch-aware HVG column, and PCA dimensionality.',
    methods: ['normalize', 'select_hvg', 'pca', 'run_pca'],
    fields: ['target_sum', 'n_top_genes', 'hvg_flavor', 'hvg_batch_key', 'n_pcs'],
  },
  {
    id: 'batch',
    title: 'Batch-Aware Settings',
    description:
      'Shared batch/sample controls for doublet detection, HVG selection, and optional Harmony or scVI. The batch column should identify technical or sample batches — avoid using the primary biological variable of interest unless it is also your batch structure.',
    methods: [
      'batch_correct',
      'batch_correction',
      'batch_correction_harmony',
      'batch_correction_scvi',
    ],
    fields: ['batch_correction', 'integration_mode', 'batch_key', 'n_latent', 'max_epochs'],
  },
  {
    id: 'embedding',
    title: 'Clustering & Embedding',
    description:
      'Clustering resolution is the primary tuning knob; neighbor count and Leiden vs Louvain are advanced. Embedding follows the same neighbor graph defaults unless you change k here (API use_rep stays programmatic).',
    methods: ['cluster', 'embed', 'umap', 'tsne'],
    fields: [
      'resolution',
      'clustering_method',
      'n_neighbors',
      'embedding_method',
      'umap_min_dist',
      'tsne_perplexity',
      'cluster_key',
    ],
  },
  {
    id: 'annotation',
    title: 'Annotation',
    description:
      'Primary run controls are cancer type and species. AnnotationAgentV3_0 is the default engine and uses the clustering step’s output column automatically unless you override the cluster key in Advanced settings. Legacy tissue context may still appear on older runs if it was stored.',
    methods: ['annotate'],
    fields: ['annotation_cancer_type', 'annotation_species', 'annotation_tissue_context'],
    fullWidth: true,
  },
  {
    id: 'de',
    title: 'Differential Expression',
    description:
      'Mode selector plus marker-ranking or pseudobulk inputs. Main form shows mode, grouping, sample/condition keys, and marker test settings; contrast tuning and pseudobulk thresholds are under Advanced.',
    methods: ['differential_expression'],
    fields: [
      'de_mode',
      'de_groupby_key',
      'de_sample_key',
      'de_condition_key',
      'de_method',
      'de_n_genes',
      'de_focus_level',
      'de_reference_level',
      'de_compare_level',
      'de_contrast',
      'de_min_cells_per_sample',
      'de_min_samples_per_group',
      'de_padj_method',
      'de_logfc_threshold',
    ],
  },
  {
    id: 'optional',
    title: 'Optional Analyses',
    description:
      'Pathway: per-cell activity scoring (resource + decoupler method below). Ligand–receptor when enabled.',
    methods: ['pathway_scoring', 'ligand_receptor', 'ligand_receptor_analysis'],
    fields: [
      'pathway_scoring',
      'pathway_database',
      'pathway_method',
      'pathway_progeny_top',
      'pathway_net_path',
      'ligand_receptor',
      'lr_resource_name',
      'lr_communication_grouping',
      'lr_expr_prop',
      'lr_min_cells',
      'lr_n_perms',
    ],
    fullWidth: true,
  },
  {
    id: 'reproducibility',
    title: 'Reproducibility',
    description: 'Seed and provenance-related inputs.',
    fields: ['random_seed'],
  },
];

const CONDITIONAL_FIELD_VISIBILITY: Record<string, (values: Record<string, unknown>) => boolean> = {
  expected_doublet_rate: (values) =>
    !values.doublet_method ||
    values.doublet_method === 'scrublet' ||
    values.doublet_method === 'solo',
  batch_method: () => false,
  integration_mode: (values) => Boolean(values.batch_correction),
  batch_key: (values) => Boolean(values.batch_correction),
  doublet_sample_key: (values) => values.doublet_method === 'scrublet',
  hvg_batch_key: (values) =>
    Boolean(values.batch_correction) ||
    hasNonEmptyString(values, 'batch_key') ||
    hasNonEmptyString(values, 'hvg_batch_key'),
  ambient_method: (values) => Boolean(values.ambient_correction),
  n_latent: (values) => Boolean(values.batch_correction) && batchIntegrationIsScvi(values),
  max_epochs: (values) => Boolean(values.batch_correction) && batchIntegrationIsScvi(values),
  solo_batch_size: (values) => values.doublet_method === 'solo',
  solo_gene_likelihood: (values) => values.doublet_method === 'solo',
  solo_max_epochs: (values) => values.doublet_method === 'solo',
  doubletdetection_voter_thresh: (values) => values.doublet_method === 'doubletdetection',
  doubletdetection_p_thresh: (values) => values.doublet_method === 'doubletdetection',
  annotation_model: (values) => values.annotation_method !== 'marker_pack',
  annotation_model_path: (values) =>
    values.annotation_method !== 'marker_pack' && values.annotation_model === 'custom',
  pathway_database: (values) => Boolean(values.pathway_scoring),
  pathway_method: (values) => Boolean(values.pathway_scoring),
  pathway_progeny_top: (values) =>
    Boolean(values.pathway_scoring) && values.pathway_database === 'PROGENy',
  pathway_net_path: (values) =>
    Boolean(values.pathway_scoring) && values.pathway_database === 'Custom',
  annotation_marker_database: (values) =>
    values.annotation_method === 'marker_pack' || values.annotation_method === 'hybrid',
  annotation_marker_pack_path: (values) =>
    (values.annotation_method === 'marker_pack' || values.annotation_method === 'hybrid') &&
    values.annotation_marker_database === 'custom',
  lr_resource_name: (values) => Boolean(values.ligand_receptor),
  lr_expr_prop: (values) => Boolean(values.ligand_receptor),
  lr_min_cells: (values) => Boolean(values.ligand_receptor),
  lr_n_perms: (values) => Boolean(values.ligand_receptor),
  lr_communication_grouping: (values) => Boolean(values.ligand_receptor),
  max_hb_pct: (values) => Boolean(values.compute_hb_pct) || values.max_hb_pct != null,
  max_hk_pct: (values) => Boolean(values.filter_by_housekeeping) || values.max_hk_pct != null,
  umap_min_dist: (values) => values.embedding_method !== 'tsne',
  tsne_perplexity: (values) => values.embedding_method === 'tsne',
  de_sample_key: (values) =>
    values.de_mode === 'condition_de_within_celltype' ||
    values.de_mode === 'pseudobulk_sample_level_contrast',
  de_condition_key: (values) =>
    values.de_mode === 'condition_de_within_celltype' ||
    values.de_mode === 'pseudobulk_sample_level_contrast',
  de_focus_level: (values) => values.de_mode === 'condition_de_within_celltype',
  de_reference_level: (values) =>
    values.de_mode === 'condition_de_within_celltype' ||
    values.de_mode === 'pseudobulk_sample_level_contrast',
  de_compare_level: (values) =>
    values.de_mode === 'condition_de_within_celltype' ||
    values.de_mode === 'pseudobulk_sample_level_contrast',
  de_contrast: (values) =>
    values.de_mode === 'condition_de_within_celltype' ||
    values.de_mode === 'pseudobulk_sample_level_contrast',
  de_min_cells_per_sample: (values) =>
    values.de_mode === 'condition_de_within_celltype' ||
    values.de_mode === 'pseudobulk_sample_level_contrast',
  de_min_samples_per_group: (values) =>
    values.de_mode === 'condition_de_within_celltype' ||
    values.de_mode === 'pseudobulk_sample_level_contrast',
  de_padj_method: (values) =>
    values.de_mode === 'condition_de_within_celltype' ||
    values.de_mode === 'pseudobulk_sample_level_contrast',
  de_logfc_threshold: (values) =>
    values.de_mode === 'condition_de_within_celltype' ||
    values.de_mode === 'pseudobulk_sample_level_contrast',
  de_groupby_key: (values) =>
    values.de_mode === 'condition_de_within_celltype' ||
    values.de_mode === 'pseudobulk_sample_level_contrast',
  de_method: (values) => !values.de_mode || values.de_mode === 'marker_ranking',
  de_n_genes: (values) => !values.de_mode || values.de_mode === 'marker_ranking',
};

export function getParameterLabel(name: string): string {
  return PARAM_LABELS[name] ?? name.replace(/_/g, ' ');
}

export function isFieldVisible(name: string, values: Record<string, unknown>): boolean {
  const condition = CONDITIONAL_FIELD_VISIBILITY[name];
  return condition ? condition(values) : true;
}

export function getSectionFields(
  section: Pick<ParameterSectionConfig, 'methods' | 'fields'>,
  properties: Record<string, Record<string, unknown>>,
  selectedMethodNames: Set<string>,
  values: Record<string, unknown>
): string[] {
  if (
    section.methods &&
    section.methods.length > 0 &&
    !section.methods.some((methodName) => selectedMethodNames.has(methodName))
  ) {
    return [];
  }

  return section.fields.filter(
    (fieldName) => properties[fieldName] && isFieldVisible(fieldName, values)
  );
}
