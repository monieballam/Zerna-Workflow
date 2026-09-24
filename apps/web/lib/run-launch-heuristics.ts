import type { Dataset, DatasetVersionSummary } from '@zerna/sdk';

/** Advisory only — not validation. */
export type RunComplexityEstimate = 'standard' | 'heavy' | 'very_heavy';

export type DatasetScaleSnapshot = {
  datasetName: string;
  versionLabel: string;
  cellCount: number | null;
  geneCount: number | null;
  /** Human-readable hints from metadata when present */
  mergeOrSourceHint: string | null;
  batchLikeColumnCount: number | null;
};

export type LargeRunAdvisory = {
  complexity: RunComplexityEstimate;
  complexityLabel: string;
  /** Short bullet reasons (memory / scale risk signals) */
  riskSignals: string[];
  /** Actionable suggestions */
  suggestions: string[];
};

const CELLS_HEAVY = 80_000;
const CELLS_VERY_HEAVY = 250_000;
const GENES_HEAVY = 35_000;

/** Safe string for eslint no-base-to-string when metadata / params are loosely typed. */
function paramString(v: unknown): string {
  if (v == null) return '';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean' || typeof v === 'bigint') return String(v);
  return '';
}

/** Fields launch presets may adjust (must exist in template schema to apply). */
export const LAUNCH_PRESET_FIELD_KEYS = [
  'pathway_scoring',
  'ligand_receptor',
  'batch_correction',
  'integration_mode',
  'ambient_correction',
  'ambient_method',
  'de_mode',
  'n_top_genes',
] as const;

export type LaunchPresetId = 'standard' | 'lightweight' | 'deep';

export const LAUNCH_PRESETS: {
  id: LaunchPresetId;
  label: string;
  shortDescription: string;
  detail: string;
}[] = [
  {
    id: 'standard',
    label: 'Standard',
    shortDescription: 'Recommended defaults for this template',
    detail:
      'Resets preset-related fields to the template’s recommended defaults. Use this as a clean baseline before tweaking individual options.',
  },
  {
    id: 'lightweight',
    label: 'Lightweight',
    shortDescription: 'Lower memory pressure for large or merged objects',
    detail:
      'Turns off optional heavy downstream analyses (pathway, ligand–receptor), disables batch correction and ambient correction when those toggles exist, prefers Harmony over scVI when both exist, sets DE to marker ranking, and caps HVG count when n_top_genes is present. You can re-enable anything afterward.',
  },
  {
    id: 'deep',
    label: 'Deep analysis',
    shortDescription: 'Enable richer exploratory downstream outputs',
    detail:
      'Turns on pathway activity scoring and ligand–receptor analysis when those toggles exist. Does not change DE mode or batch correction — configure those explicitly if you need pseudobulk or integration.',
  },
];

export function findDatasetVersion(
  datasets: Dataset[],
  versionId: string
): { dataset: Dataset; version: DatasetVersionSummary } | null {
  if (!versionId.trim()) return null;
  for (const dataset of datasets) {
    const version = dataset.versions.find((v) => v.id === versionId);
    if (version) return { dataset, version };
  }
  return null;
}

function readPositiveInt(meta: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const v = meta[key];
    if (typeof v === 'number' && Number.isFinite(v) && v > 0) return Math.floor(v);
    if (typeof v === 'string' && /^\d+$/.test(v.trim())) {
      const n = parseInt(v.trim(), 10);
      if (n > 0) return n;
    }
  }
  return null;
}

function mergeHintFromMetadata(
  datasetMeta: Record<string, unknown>,
  versionMeta: Record<string, unknown>
): string | null {
  const nSources =
    readPositiveInt(versionMeta, [
      'n_sources',
      'n_input_files',
      'input_file_count',
      'num_sources',
      'library_count',
    ]) ??
    readPositiveInt(datasetMeta, [
      'n_sources',
      'n_input_files',
      'input_file_count',
      'num_sources',
      'library_count',
    ]);
  if (nSources != null && nSources > 1) {
    return `${nSources} input sources recorded in metadata`;
  }
  const merged =
    datasetMeta.merged === true ||
    versionMeta.merged === true ||
    paramString(datasetMeta.merge_strategy).toLowerCase() === 'concat' ||
    paramString(versionMeta.merge_strategy).toLowerCase() === 'concat';
  if (merged) {
    return 'Metadata indicates merged or concatenated inputs';
  }
  return null;
}

export function getDatasetScaleSnapshot(
  datasets: Dataset[],
  versionId: string,
  batchLikeColumnCount: number | null
): DatasetScaleSnapshot | null {
  const found = findDatasetVersion(datasets, versionId);
  if (!found) return null;
  const { dataset, version } = found;
  const dm = dataset.metadata ?? {};
  const vm = version.metadata ?? {};
  return {
    datasetName: dataset.name,
    versionLabel: version.version,
    cellCount: version.cell_count,
    geneCount: version.gene_count,
    mergeOrSourceHint: mergeHintFromMetadata(dm, vm),
    batchLikeColumnCount: batchLikeColumnCount,
  };
}

function truthyParam(v: unknown): boolean {
  return v === true || v === 'true';
}

export function estimateRunComplexity(
  cells: number | null,
  genes: number | null,
  paramValues: Record<string, unknown>,
  options: { batchCorrectionEnabled: boolean; scvi: boolean; heavyOptionalCount: number }
): RunComplexityEstimate {
  const c = cells ?? 0;
  const g = genes ?? 0;
  if (c >= CELLS_VERY_HEAVY) return 'very_heavy';

  let score = 0;
  if (c >= CELLS_HEAVY) score += 2;
  else if (c >= 40_000) score += 1;

  if (g >= GENES_HEAVY) score += 1;

  if (options.batchCorrectionEnabled && c >= 50_000) score += 2;
  if (options.scvi && c >= 40_000) score += 1;
  score += options.heavyOptionalCount;

  if (truthyParam(paramValues.ambient_correction)) score += 1;

  if (score >= 5) return 'very_heavy';
  if (score >= 2) return 'heavy';
  return 'standard';
}

export function buildLargeRunAdvisory(
  snapshot: DatasetScaleSnapshot | null,
  paramValues: Record<string, unknown>,
  batchCandidateCount: number | null
): LargeRunAdvisory | null {
  if (!snapshot) return null;

  const cells = snapshot.cellCount;
  const genes = snapshot.geneCount;
  const batchOn = truthyParam(paramValues.batch_correction);
  const integrationMode = (paramString(paramValues.integration_mode) || 'harmony').toLowerCase();
  const scvi = integrationMode === 'scvi' || paramValues.batch_method === 'scvi';
  const pathway = truthyParam(paramValues.pathway_scoring);
  const lr = truthyParam(paramValues.ligand_receptor);
  const ambient = truthyParam(paramValues.ambient_correction);
  const deMode = paramString(paramValues.de_mode).toLowerCase();
  const pseudobulkish =
    deMode === 'pseudobulk_sample_level_contrast' || deMode === 'condition_de_within_celltype';

  let heavyOptionalCount = 0;
  if (pathway) heavyOptionalCount += 1;
  if (lr) heavyOptionalCount += 1;
  if (pseudobulkish) heavyOptionalCount += 1;

  const complexity = estimateRunComplexity(cells, genes, paramValues, {
    batchCorrectionEnabled: batchOn,
    scvi,
    heavyOptionalCount,
  });

  const riskSignals: string[] = [];
  if (cells != null && cells >= CELLS_VERY_HEAVY) {
    riskSignals.push(
      `Very large cell count (~${cells.toLocaleString()}). Normalization, PCA, and neighbors can require substantial RAM.`
    );
  } else if (cells != null && cells >= CELLS_HEAVY) {
    riskSignals.push(
      `Large cell count (~${cells.toLocaleString()}). This run may require substantial memory.`
    );
  }
  if (genes != null && genes >= GENES_HEAVY) {
    riskSignals.push(
      `High gene dimension (~${genes.toLocaleString()} genes). Dense intermediate matrices are more likely to exhaust memory.`
    );
  }
  if (snapshot.mergeOrSourceHint) {
    riskSignals.push(
      `${snapshot.mergeOrSourceHint}. Large merged runs are more likely to fail during normalization, PCA, or integration.`
    );
  }
  if (batchCandidateCount != null && batchCandidateCount >= 6 && cells != null && cells >= 40_000) {
    riskSignals.push(
      'Many batch- or sample-like columns were detected in metadata — often seen with multi-library or merged datasets.'
    );
  }
  if (batchOn && cells != null && cells >= 50_000) {
    riskSignals.push(
      'Batch correction is enabled on a large object. Integration steps (especially scVI) increase peak memory.'
    );
  }
  if (scvi && cells != null && cells >= 40_000) {
    riskSignals.push(
      'scVI integration is enabled; it is typically more memory-intensive than Harmony on PCA.'
    );
  }
  if (pathway && lr && cells != null && cells >= 40_000) {
    riskSignals.push(
      'Pathway scoring and ligand–receptor are both enabled — together they add significant downstream work and memory use.'
    );
  }
  if (ambient && cells != null && cells >= 40_000) {
    riskSignals.push(
      'Ambient correction is enabled; extra matrices can increase memory pressure on large runs.'
    );
  }
  if (pseudobulkish && cells != null && cells >= 60_000) {
    riskSignals.push(
      'Replicate-aware pseudobulk DE modes aggregate per-sample profiles and can be heavier than marker ranking at scale.'
    );
  }

  if (riskSignals.length === 0 && complexity === 'standard') return null;

  const suggestions: string[] = [
    'Start with the Standard preset, then enable heavy options only when needed.',
    'For very large or merged objects, try the Lightweight preset to turn off optional downstream analyses and integration until the core object is stable.',
    'Tighten QC (higher min genes per cell, stricter max mitochondrial %) to reduce cell count before normalization.',
    'Run a Standard workflow first without pathway, ligand–receptor, or pseudobulk DE; add those on a follow-up run if resources allow.',
    'If batch correction is not essential, disable it for an initial pass; prefer Harmony over scVI when memory is tight.',
  ];

  const complexityLabel =
    complexity === 'very_heavy' ? 'Very heavy' : complexity === 'heavy' ? 'Heavy' : 'Standard';

  return {
    complexity,
    complexityLabel,
    riskSignals,
    suggestions,
  };
}

/** Keys to reset to template defaults when applying the Standard preset. */
const STANDARD_RESET_KEYS = new Set<string>(LAUNCH_PRESET_FIELD_KEYS);

const LIGHTWEIGHT_PATCH: Record<string, unknown> = {
  pathway_scoring: false,
  ligand_receptor: false,
  batch_correction: false,
  integration_mode: 'harmony',
  ambient_correction: false,
  ambient_method: 'off',
  de_mode: 'marker_ranking',
  n_top_genes: 1500,
};

const DEEP_PATCH: Record<string, unknown> = {
  pathway_scoring: true,
  ligand_receptor: true,
};

export function applyLaunchPresetToParams(
  presetId: LaunchPresetId,
  current: Record<string, unknown>,
  templateDefaults: Record<string, unknown>,
  schemaProperties: Record<string, Record<string, unknown>> | undefined
): Record<string, unknown> {
  const keys = new Set(Object.keys(schemaProperties ?? {}));
  const next = { ...current };

  if (presetId === 'standard') {
    for (const key of STANDARD_RESET_KEYS) {
      if (!keys.has(key)) continue;
      if (Object.prototype.hasOwnProperty.call(templateDefaults, key)) {
        next[key] = templateDefaults[key];
      }
    }
    return next;
  }

  const patch = presetId === 'lightweight' ? LIGHTWEIGHT_PATCH : DEEP_PATCH;
  for (const [key, value] of Object.entries(patch)) {
    if (keys.has(key)) next[key] = value;
  }
  return next;
}
