import type { PipelineMethodCatalogEntry } from '@zerna/sdk';

const FALLBACK_PIPELINE_CATALOG: PipelineMethodCatalogEntry[] = [
  {
    name: 'qc_filter',
    label: 'QC & Filtering',
    description:
      'Remove low-quality cells and genes before downstream analysis. Stricter QC usually speeds later steps by shrinking the matrix, but it can discard rare or stressed populations if pushed too far.',
    order: 10,
    default_selected: true,
    enabled_if: null,
  },
  {
    name: 'doublet_detection',
    label: 'Doublet Detection',
    description:
      'Score and optionally remove likely doublets before normalization. This adds some early runtime, but it often improves cluster purity and reduces wasted computation on mixed-cell artifacts.',
    order: 20,
    default_selected: true,
    enabled_if: null,
  },
  {
    name: 'ambient_correction',
    label: 'Ambient RNA correction',
    description:
      'Optional advanced preprocessing for suspected background RNA. Off by default; SoupX runs through an R helper using a filtered-counts-only approximation, while Identity only copies counts for provenance.',
    order: 25,
    default_selected: false,
    enabled_if: 'ambient_correction',
  },
  {
    name: 'normalize',
    label: 'Normalization',
    description:
      'Library-size normalize counts and compute log1p expression values. This step is usually fast and low-risk, and it stabilizes downstream HVG, PCA, and marker detection.',
    order: 30,
    default_selected: true,
    enabled_if: null,
  },
  {
    name: 'select_hvg',
    label: 'HVG Selection',
    description:
      'Select highly variable genes for downstream PCA and clustering. This step marks HVGs but does not subset genes immediately. Using fewer genes is faster and lighter on memory, while using more genes may keep subtle biology at the cost of noisier and slower downstream steps.',
    order: 40,
    default_selected: true,
    enabled_if: null,
  },
  {
    name: 'run_pca',
    label: 'PCA',
    description:
      'Compute principal components from the selected HVGs. More components can preserve more structure, but they increase downstream neighbor, clustering, and embedding cost.',
    order: 50,
    default_selected: true,
    enabled_if: null,
  },
  {
    name: 'batch_correct',
    label: 'Batch Correction',
    description:
      'Optionally integrate batches before clustering. This can greatly improve comparability across samples, but it is often one of the slowest parts of the pipeline, especially with scVI.',
    order: 60,
    default_selected: true,
    enabled_if: 'batch_correction',
  },
  {
    name: 'cluster',
    label: 'Clustering',
    description:
      'Build a neighbor graph and cluster cells with Leiden or Louvain. This is usually moderate in cost; finer settings can reveal substructure but may split biologically similar cells into too many groups.',
    order: 70,
    default_selected: true,
    enabled_if: null,
  },
  {
    name: 'embed',
    label: 'Embedding',
    description:
      'Compute a UMAP or t-SNE embedding for visualization. UMAP is usually faster and more scalable; t-SNE can separate local structure well but often costs more time.',
    order: 80,
    default_selected: true,
    enabled_if: null,
  },
  {
    name: 'annotate',
    label: 'Cell-Type Annotation',
    description:
      'Assign cell types using CellTypist and Zerna-specific outputs. This adds moderate runtime, but it turns clusters into interpretable biology and improves downstream reporting.',
    order: 90,
    default_selected: true,
    enabled_if: null,
  },
  {
    name: 'differential_expression',
    label: 'Differential Expression',
    description:
      'Rank marker genes for clusters or cell populations. This can be expensive on large datasets, but it is one of the most useful steps for cluster interpretation and validation.',
    order: 100,
    default_selected: true,
    enabled_if: null,
  },
  {
    name: 'pathway_scoring',
    label: 'Pathway Activity Scoring',
    description:
      'Optional per-cell pathway activity scoring (decoupler / PROGENy-style resources). Exploratory scores from expression—not DE-contrast enrichment. Heavier on runtime and memory for large gene sets.',
    order: 110,
    default_selected: true,
    enabled_if: 'pathway_scoring',
  },
  {
    name: 'ligand_receptor_analysis',
    label: 'Ligand-Receptor Analysis',
    description:
      'Optional LIANA ligand–receptor inference. Default grouping stays on canonical cci_celltype_* tiers (auto) with cluster fallback; optional advanced lineage_subcluster mode is available when P2 partitions exist. Heavier runtime than marker steps alone.',
    order: 120,
    default_selected: true,
    enabled_if: 'ligand_receptor',
  },
];

export function getFallbackPipelineCatalog(): PipelineMethodCatalogEntry[] {
  return FALLBACK_PIPELINE_CATALOG.map((entry) => ({ ...entry }));
}
