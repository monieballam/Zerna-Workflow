'use client';

import { useEffect, useMemo, useState } from 'react';
import type { Artifact } from '@zerna/sdk';
import {
  DifferentialExpressionSection,
  DownstreamAnalysisNotRunPanel,
  LigandReceptorSection,
  PathwayActivitySection,
} from '@/components/runs/DownstreamAnalysisPanels';
import { buildBiologicalSummaryItems } from '@/lib/run-results-biological-summary';

type GenericStepMetrics = {
  skipped?: boolean;
  reason?: string;
  [key: string]: unknown;
};

interface StepMetrics {
  [key: string]: GenericStepMetrics | undefined;
  cluster?: GenericStepMetrics & {
    n_clusters: number;
    cluster_sizes: number[];
    cluster_key?: string;
    clusters?: Array<{
      cluster_id: string;
      label: string;
      n_cells: number;
    }>;
  };
  qc_filter?: GenericStepMetrics & {
    n_cells_before: number;
    n_cells_after: number;
    n_genes_before: number;
    n_genes_after: number;
    median_genes_per_cell: number;
    median_counts_per_cell: number;
  };
  doublet_detection?: GenericStepMetrics & {
    n_cells_before: number;
    n_cells_after: number;
    n_predicted_doublets: number;
    doublet_rate: number;
    mean_doublet_score: number;
  };
  normalize?: GenericStepMetrics & {
    target_sum?: number;
    log1p_applied?: boolean;
    scale_applied?: boolean;
    scale_max_value?: number | null;
  };
  select_hvg?: GenericStepMetrics & {
    n_genes_total: number;
    n_hvgs_selected: number;
  };
  run_pca?: GenericStepMetrics & {
    n_components_computed: number;
    variance_ratio_top10: number[];
  };
  batch_correction_harmony?: GenericStepMetrics & {
    batch_key: string;
    n_batches: number;
    kbet_score: number;
    lisi_score: number;
  };
  batch_correction_scvi?: GenericStepMetrics & {
    batch_key: string;
    n_batches: number;
    kbet_score: number;
    lisi_score: number;
  };
  embed?: GenericStepMetrics & {
    embedding_key?: string;
    method_executed?: string;
    method_requested?: string;
    n_components?: number;
    representation_used?: string;
  };
  annotate?: GenericStepMetrics & {
    gene_overlap?: number;
    model_genes?: number;
    dataset_genes?: number;
    n_cells_annotated?: number;
    n_cell_types_predicted?: number;
    mean_confidence?: number;
    model_used?: string;
  };
  differential_expression?: GenericStepMetrics & {
    de_mode?: string;
    n_clusters?: number | null;
    n_comparisons?: number | null;
    n_genes_tested?: number | null;
    cluster_key?: string | null;
    method?: string;
    method_requested?: string;
    method_executed?: string;
    n_pseudobulk_profiles?: number | null;
    groupby_key_used?: string | null;
    condition_key_used?: string | null;
    sample_key_used?: string | null;
    statistical_warning?: string | null;
  };
  pathway_scoring?: GenericStepMetrics & {
    n_pathways_scored: number;
    n_cells: number;
    pathway_database: string;
    methods_used: string[];
    obsm_key: string;
  };
  ligand_receptor_analysis?: GenericStepMetrics & {
    n_interactions: number;
    n_cluster_pairs: number;
    n_clusters: number;
    cluster_key: string;
    resource_name: string;
  };
}

interface RunResultsData {
  run_id: string;
  status: string;
  step_metrics: StepMetrics;
  software_versions: Record<string, string>;
  artifact_id: string | null;
  artifact_size_bytes: number | null;
  download_url: string | null;
}

interface StepGroup {
  label: string;
  keys: string[];
}

const STEP_GROUPS: StepGroup[] = [
  { label: 'QC Filter', keys: ['qc_filter'] },
  { label: 'Doublet Detection', keys: ['doublet_detection'] },
  { label: 'Normalize', keys: ['normalize'] },
  { label: 'HVG Selection', keys: ['select_hvg'] },
  { label: 'PCA', keys: ['run_pca'] },
  { label: 'Batch Correction', keys: ['batch_correction_harmony', 'batch_correction_scvi'] },
  { label: 'Clustering', keys: ['cluster'] },
  { label: 'Embedding', keys: ['embed'] },
  { label: 'Annotation', keys: ['annotate'] },
  { label: 'Differential Expression', keys: ['differential_expression'] },
  { label: 'Pathway Activity Scoring', keys: ['pathway_scoring'] },
  { label: 'Ligand-Receptor', keys: ['ligand_receptor_analysis'] },
];

function firstMetrics(stepMetrics: StepMetrics, keys: string[]): GenericStepMetrics | undefined {
  for (const key of keys) {
    const value = stepMetrics[key];
    if (value) {
      return value;
    }
  }
  return undefined;
}

function pct(a: number, b: number): string {
  if (b === 0) return '0%';
  return `${((a / b) * 100).toFixed(1)}%`;
}

type ClusterRow = {
  cluster_id: string;
  label?: string;
  n_cells: number;
};

type ClusterSortOption =
  | 'cluster_id_asc'
  | 'cluster_id_desc'
  | 'label_asc'
  | 'cells_desc'
  | 'cells_asc';

function compareClusterId(a: string, b: string): number {
  const aText = String(a);
  const bText = String(b);
  if (/^\d+$/.test(aText) && /^\d+$/.test(bText)) {
    return Number(aText) - Number(bText);
  }
  return aText.localeCompare(bText, undefined, { numeric: true, sensitivity: 'base' });
}

function sortClusterRows(rows: ClusterRow[], sortBy: ClusterSortOption): ClusterRow[] {
  const next = [...rows];
  next.sort((a, b) => {
    switch (sortBy) {
      case 'cluster_id_desc':
        return compareClusterId(b.cluster_id, a.cluster_id);
      case 'label_asc': {
        const aLabel = (a.label?.trim() || `Cluster ${a.cluster_id}`).toLowerCase();
        const bLabel = (b.label?.trim() || `Cluster ${b.cluster_id}`).toLowerCase();
        const labelOrder = aLabel.localeCompare(bLabel, undefined, { sensitivity: 'base' });
        return labelOrder !== 0 ? labelOrder : compareClusterId(a.cluster_id, b.cluster_id);
      }
      case 'cells_asc':
        return a.n_cells - b.n_cells || compareClusterId(a.cluster_id, b.cluster_id);
      case 'cells_desc':
        return b.n_cells - a.n_cells || compareClusterId(a.cluster_id, b.cluster_id);
      case 'cluster_id_asc':
      default:
        return compareClusterId(a.cluster_id, b.cluster_id);
    }
  });
  return next;
}

function ClusterBar({ sizes, clusters }: { sizes?: number[]; clusters?: ClusterRow[] }) {
  const [sortBy, setSortBy] = useState<ClusterSortOption>('cluster_id_asc');
  const baseRows = useMemo(
    () =>
      clusters && clusters.length > 0
        ? clusters
        : (sizes ?? []).map((size, index) => ({
            cluster_id: String(index),
            label: '',
            n_cells: size,
          })),
    [clusters, sizes]
  );
  const rows = useMemo(() => sortClusterRows(baseRows, sortBy), [baseRows, sortBy]);
  const max = Math.max(...rows.map((row) => row.n_cells), 0);
  const total = rows.reduce((sum, row) => sum + row.n_cells, 0);
  const colors = [
    'bg-blue-500',
    'bg-green-500',
    'bg-yellow-500',
    'bg-red-500',
    'bg-purple-500',
    'bg-pink-500',
    'bg-indigo-500',
    'bg-teal-500',
    'bg-orange-500',
    'bg-cyan-500',
    'bg-blue-400',
    'bg-green-400',
    'bg-yellow-400',
    'bg-red-400',
    'bg-purple-400',
    'bg-pink-400',
    'bg-indigo-400',
    'bg-teal-400',
    'bg-orange-400',
    'bg-cyan-400',
    'bg-blue-300',
    'bg-green-300',
    'bg-yellow-300',
    'bg-red-300',
    'bg-purple-300',
  ];

  return (
    <div className="space-y-1">
      {rows.length > 1 && (
        <div className="mb-3 flex items-center justify-end gap-2">
          <label htmlFor="cluster-sort" className="text-xs font-medium text-gray-500">
            Sort clusters
          </label>
          <select
            id="cluster-sort"
            value={sortBy}
            onChange={(event) => setSortBy(event.target.value as ClusterSortOption)}
            className="rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-700"
          >
            <option value="cluster_id_asc">Cluster ID (low to high)</option>
            <option value="cluster_id_desc">Cluster ID (high to low)</option>
            <option value="label_asc">Label (A to Z)</option>
            <option value="cells_desc">Cell count (high to low)</option>
            <option value="cells_asc">Cell count (low to high)</option>
          </select>
        </div>
      )}
      <div role="list" className="space-y-1">
        {rows.map((row, i) => {
          const displayLabel =
            row.label && row.label !== row.cluster_id && row.label !== `Cluster ${row.cluster_id}`
              ? row.label
              : null;

          return (
            <div key={row.cluster_id} role="listitem" className="flex items-center gap-2 text-xs">
              <div className="w-44 min-w-0">
                <p className="truncate text-xs font-medium text-gray-700">
                  Cluster <span className="font-mono">{row.cluster_id}</span>
                </p>
                {displayLabel && <p className="truncate text-xs text-gray-400">{displayLabel}</p>}
              </div>
              <div className="flex-1 h-4 bg-gray-100 rounded overflow-hidden">
                <div
                  className={`h-full ${colors[i % colors.length]} rounded`}
                  style={{ width: max > 0 ? `${(row.n_cells / max) * 100}%` : '0%' }}
                />
              </div>
              <span className="w-16 text-right text-gray-600 font-mono">
                {row.n_cells.toLocaleString()}
              </span>
              <span className="w-12 text-right text-gray-400">{pct(row.n_cells, total)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function formatQcCollapsedSummary(qc: NonNullable<StepMetrics['qc_filter']>): string {
  const after = qc.n_cells_after.toLocaleString();
  const before = qc.n_cells_before.toLocaleString();
  const genes = qc.n_genes_after.toLocaleString();
  return `${after} / ${before} cells retained • ${genes} genes after filtering`;
}

function formatDoubletCollapsedSummary(dd: NonNullable<StepMetrics['doublet_detection']>): string {
  const n = dd.n_predicted_doublets.toLocaleString();
  const pctFlag = (dd.doublet_rate * 100).toFixed(1);
  return `${n} predicted doublets • ${pctFlag}% flagged`;
}

function formatPcaCollapsedSummary(runPca: NonNullable<StepMetrics['run_pca']>): string {
  const n = runPca.n_components_computed;
  const ratios = runPca.variance_ratio_top10 ?? [];
  const k = Math.min(10, ratios.length);
  if (k === 0) {
    return `${n} components`;
  }
  const topSum = ratios.slice(0, k).reduce((acc, r) => acc + r, 0);
  const pctExplained = (topSum * 100).toFixed(0);
  return `${n} components • top ${k} PCs explain ${pctExplained}% variance`;
}

function formatBatchCollapsedSummary(
  batchMethod: string,
  batch: NonNullable<StepMetrics['batch_correction_harmony'] | StepMetrics['batch_correction_scvi']>
): string {
  const n = Number(batch.n_batches ?? 0);
  return `${batchMethod} on ${n.toLocaleString()} batches`;
}

function formatClusteringCollapsedSummary(cluster: NonNullable<StepMetrics['cluster']>): string {
  const ck = cluster.cluster_key?.trim();
  const keyPart = ck ? ` • cluster key: ${ck}` : '';
  return `${cluster.n_clusters} clusters identified${keyPart}`;
}

function formatNormalizeCollapsedSummary(n: NonNullable<StepMetrics['normalize']>): string {
  const ts = typeof n.target_sum === 'number' ? n.target_sum : null;
  const log1p = n.log1p_applied !== false;
  const scale = Boolean(n.scale_applied);
  const parts: string[] = [];
  if (ts != null) parts.push(`target sum ${ts.toLocaleString()}`);
  parts.push(log1p ? 'log1p on' : 'log1p off');
  if (scale) parts.push('scaled');
  return parts.join(' • ');
}

function formatHvgCollapsedSummary(h: NonNullable<StepMetrics['select_hvg']>): string {
  return `${h.n_hvgs_selected.toLocaleString()} HVGs from ${h.n_genes_total.toLocaleString()} genes`;
}

function formatEmbedCollapsedSummary(e: NonNullable<StepMetrics['embed']>): string {
  const method = String(e.method_executed ?? e.method_requested ?? 'umap').toLowerCase();
  const label = method === 'tsne' ? 't-SNE' : 'UMAP';
  const key = e.embedding_key ? String(e.embedding_key) : 'embedding';
  const nc = typeof e.n_components === 'number' ? `${e.n_components}D` : '';
  return nc ? `${label} ${nc} • ${key}` : `${label} • ${key}`;
}

function CollapseChevron() {
  return (
    <svg
      className="h-5 w-5 shrink-0 text-gray-400 transition-transform duration-200 group-open:rotate-180"
      viewBox="0 0 20 20"
      fill="currentColor"
      aria-hidden
    >
      <path
        fillRule="evenodd"
        d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function VarianceBars({ ratios }: { ratios: number[] }) {
  const max = Math.max(...ratios, 0);
  return (
    <div className="space-y-1">
      {ratios.map((r, i) => (
        <div key={i} className="flex items-center gap-2 text-xs">
          <span className="w-8 text-right text-gray-500 font-mono">PC{i + 1}</span>
          <div className="flex-1 h-3 bg-gray-100 rounded overflow-hidden">
            <div
              className="h-full bg-indigo-400 rounded"
              style={{ width: max > 0 ? `${(r / max) * 100}%` : '0%' }}
            />
          </div>
          <span className="w-14 text-right text-gray-600 font-mono">{(r * 100).toFixed(1)}%</span>
        </div>
      ))}
    </div>
  );
}

function StepBadge({ name, status }: { name: string; status: 'done' | 'skipped' | 'pending' }) {
  const styles = {
    done: 'bg-green-100 text-green-700 border-green-200',
    skipped: 'bg-yellow-100 text-yellow-700 border-yellow-200',
    pending: 'bg-gray-100 text-gray-500 border-gray-200',
  };
  const icons = { done: '✓', skipped: '⊘', pending: '○' };
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${styles[status]}`}
    >
      {icons[status]} {name}
    </span>
  );
}

export default function RunResults({
  runId,
  mode = 'all',
  artifacts = [],
}: {
  runId: string;
  mode?: 'all' | 'steps' | 'details';
  /** Run artifacts (for downstream preview links and previews). */
  artifacts?: Artifact[];
}) {
  const [data, setData] = useState<RunResultsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchResults() {
      try {
        const res = await fetch(`/api/proxy/v1/runs/${runId}/results`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const payload = (await res.json()) as RunResultsData;
        setData(payload);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load results');
      } finally {
        setLoading(false);
      }
    }
    void fetchResults();
  }, [runId]);

  const biologicalSummary = useMemo(() => {
    if (!data)
      return { items: [] as { id: string; text: string }[], dominantLine: null as string | null };
    return buildBiologicalSummaryItems(data.step_metrics);
  }, [data]);

  if (loading) {
    return (
      <div className="card p-6 animate-pulse">
        <div className="h-4 bg-gray-200 rounded w-1/3 mb-4" />
        <div className="space-y-2">
          <div className="h-3 bg-gray-200 rounded w-full" />
          <div className="h-3 bg-gray-200 rounded w-2/3" />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return <div className="card p-6 text-sm text-gray-500">{error ?? 'No results available.'}</div>;
  }

  const { step_metrics: m } = data;
  const batchCorrection = m.batch_correction_harmony ?? m.batch_correction_scvi;
  const batchMethod = m.batch_correction_scvi ? 'scVI' : 'Harmony';

  const showSteps = mode !== 'details';
  const showDetails = mode !== 'steps';

  return (
    <div className="space-y-6">
      {showSteps && (
        <div className="card p-6">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Pipeline steps</h2>
          <div className="flex flex-wrap gap-2">
            {STEP_GROUPS.map((step) => {
              const metrics = firstMetrics(m, step.keys);
              let status: 'done' | 'skipped' | 'pending' = 'pending';
              if (metrics) {
                status = metrics.skipped ? 'skipped' : 'done';
              }
              return <StepBadge key={step.label} name={step.label} status={status} />;
            })}
          </div>
        </div>
      )}

      {showDetails && biologicalSummary.items.length > 0 && (
        <section
          className="card border-l-4 border-l-emerald-500/90 p-5 shadow-sm"
          aria-labelledby="results-biological-summary-heading"
          data-testid="results-biological-summary"
        >
          <h2
            id="results-biological-summary-heading"
            className="text-base font-semibold tracking-tight text-gray-900"
          >
            Biological summary
          </h2>
          <p className="mt-1 text-xs text-gray-500">
            High-level readout from recorded metrics only — open sections below for full detail.
          </p>
          {biologicalSummary.dominantLine && (
            <p className="mt-3 text-sm font-medium text-gray-800">
              {biologicalSummary.dominantLine}
            </p>
          )}
          <div className="mt-3 space-y-1.5 text-sm text-gray-700">
            {biologicalSummary.items
              .filter((row) => row.text !== biologicalSummary.dominantLine)
              .map((row) => (
                <div key={row.id} className="flex gap-2">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500/80" />
                  <span>{row.text}</span>
                </div>
              ))}
          </div>
        </section>
      )}

      {showDetails &&
        (m.qc_filter ||
          m.doublet_detection ||
          m.normalize ||
          m.select_hvg ||
          m.run_pca ||
          batchCorrection) && (
          <section className="space-y-4" aria-labelledby="results-run-summary-heading">
            <h2
              id="results-run-summary-heading"
              className="text-base font-semibold tracking-tight text-gray-900"
            >
              Run summary & preprocessing
            </h2>
            <p className="text-sm text-gray-600">
              Technical normalization and dimensionality steps are collapsed by default; expand a
              card for full parameters and QC-style metrics.
            </p>
            <div className="space-y-4">
              {m.qc_filter && (
                <details
                  data-testid="results-qc-details"
                  className="group card overflow-hidden [&_summary::-webkit-details-marker]:hidden"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-6 text-left hover:bg-gray-50/80">
                    <div className="min-w-0 flex-1">
                      <h2 className="text-sm font-semibold text-gray-900">Quality Control</h2>
                      <p
                        data-testid="results-qc-collapsed-summary"
                        className="mt-0.5 text-xs text-gray-500"
                      >
                        {formatQcCollapsedSummary(m.qc_filter)}
                      </p>
                    </div>
                    <CollapseChevron />
                  </summary>
                  <div className="border-t border-gray-100 px-6 pb-6 pt-4">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <div>
                        <p className="text-xs text-gray-500">Cells before</p>
                        <p className="text-lg font-semibold text-gray-900">
                          {m.qc_filter.n_cells_before.toLocaleString()}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Cells after</p>
                        <p className="text-lg font-semibold text-green-700">
                          {m.qc_filter.n_cells_after.toLocaleString()}
                        </p>
                        <p className="text-xs text-gray-400">
                          {pct(m.qc_filter.n_cells_after, m.qc_filter.n_cells_before)} retained
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Genes before → after</p>
                        <p className="text-lg font-semibold text-gray-900">
                          {m.qc_filter.n_genes_before.toLocaleString()} →{' '}
                          {m.qc_filter.n_genes_after.toLocaleString()}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Median genes/cell</p>
                        <p className="text-lg font-semibold text-gray-900">
                          {m.qc_filter.median_genes_per_cell.toLocaleString()}
                        </p>
                        <p className="text-xs text-gray-400">
                          {m.qc_filter.median_counts_per_cell.toLocaleString()} counts/cell
                        </p>
                      </div>
                    </div>
                  </div>
                </details>
              )}

              {m.doublet_detection && (
                <details
                  data-testid="results-doublet-details"
                  className="group card overflow-hidden [&_summary::-webkit-details-marker]:hidden"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-6 text-left hover:bg-gray-50/80">
                    <div className="min-w-0 flex-1">
                      <h2 className="text-sm font-semibold text-gray-900">Doublet Detection</h2>
                      <p
                        data-testid="results-doublet-collapsed-summary"
                        className="mt-0.5 text-xs text-gray-500"
                      >
                        {formatDoubletCollapsedSummary(m.doublet_detection)}
                      </p>
                    </div>
                    <CollapseChevron />
                  </summary>
                  <div className="border-t border-gray-100 px-6 pb-6 pt-4">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <div>
                        <p className="text-xs text-gray-500">Cells before</p>
                        <p className="text-lg font-semibold text-gray-900">
                          {m.doublet_detection.n_cells_before.toLocaleString()}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Cells after</p>
                        <p className="text-lg font-semibold text-green-700">
                          {m.doublet_detection.n_cells_after.toLocaleString()}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Predicted doublets</p>
                        <p className="text-lg font-semibold text-gray-900">
                          {m.doublet_detection.n_predicted_doublets.toLocaleString()}
                        </p>
                        <p className="text-xs text-gray-400">
                          {(m.doublet_detection.doublet_rate * 100).toFixed(1)}% flagged
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Mean score</p>
                        <p className="text-lg font-semibold text-gray-900">
                          {m.doublet_detection.mean_doublet_score.toFixed(3)}
                        </p>
                      </div>
                    </div>
                  </div>
                </details>
              )}

              {m.normalize && (
                <details
                  data-testid="results-normalize-details"
                  className="group card overflow-hidden [&_summary::-webkit-details-marker]:hidden"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-6 text-left hover:bg-gray-50/80">
                    <div className="min-w-0 flex-1">
                      <h2 className="text-sm font-semibold text-gray-900">Normalization</h2>
                      <p
                        data-testid="results-normalize-collapsed-summary"
                        className="mt-0.5 text-xs text-gray-500"
                      >
                        {formatNormalizeCollapsedSummary(m.normalize)}
                      </p>
                    </div>
                    <CollapseChevron />
                  </summary>
                  <div className="border-t border-gray-100 px-6 pb-6 pt-4">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <div>
                        <p className="text-xs text-gray-500">Target sum</p>
                        <p className="text-lg font-semibold text-gray-900">
                          {typeof m.normalize.target_sum === 'number'
                            ? m.normalize.target_sum.toLocaleString()
                            : '—'}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">log1p</p>
                        <p className="text-lg font-semibold text-gray-900">
                          {m.normalize.log1p_applied !== false ? 'Yes' : 'No'}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Scale</p>
                        <p className="text-lg font-semibold text-gray-900">
                          {m.normalize.scale_applied ? 'Yes' : 'No'}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Scale cap</p>
                        <p className="text-lg font-semibold text-gray-900">
                          {m.normalize.scale_max_value != null
                            ? String(m.normalize.scale_max_value)
                            : '—'}
                        </p>
                      </div>
                    </div>
                  </div>
                </details>
              )}

              {m.select_hvg && (
                <details
                  data-testid="results-hvg-details"
                  className="group card overflow-hidden [&_summary::-webkit-details-marker]:hidden"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-6 text-left hover:bg-gray-50/80">
                    <div className="min-w-0 flex-1">
                      <h2 className="text-sm font-semibold text-gray-900">Highly variable genes</h2>
                      <p
                        data-testid="results-hvg-collapsed-summary"
                        className="mt-0.5 text-xs text-gray-500"
                      >
                        {formatHvgCollapsedSummary(m.select_hvg)}
                      </p>
                    </div>
                    <CollapseChevron />
                  </summary>
                  <div className="border-t border-gray-100 px-6 pb-6 pt-4">
                    <p className="text-sm text-gray-600">
                      Selected{' '}
                      <span className="font-semibold text-gray-900">
                        {m.select_hvg.n_hvgs_selected.toLocaleString()}
                      </span>{' '}
                      HVGs from {m.select_hvg.n_genes_total.toLocaleString()} total genes (
                      {pct(m.select_hvg.n_hvgs_selected, m.select_hvg.n_genes_total)}).
                    </p>
                  </div>
                </details>
              )}

              {m.run_pca && (
                <details
                  data-testid="results-pca-details"
                  className="group card overflow-hidden [&_summary::-webkit-details-marker]:hidden"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-6 text-left hover:bg-gray-50/80">
                    <div className="min-w-0 flex-1">
                      <h2 className="text-sm font-semibold text-gray-900">PCA</h2>
                      <p
                        data-testid="results-pca-collapsed-summary"
                        className="mt-0.5 text-xs text-gray-500"
                      >
                        {formatPcaCollapsedSummary(m.run_pca)}
                      </p>
                    </div>
                    <CollapseChevron />
                  </summary>
                  <div className="border-t border-gray-100 px-6 pb-6 pt-4">
                    <p className="text-xs text-gray-500 mb-2">Variance explained (top 10 PCs)</p>
                    <VarianceBars ratios={m.run_pca.variance_ratio_top10} />
                  </div>
                </details>
              )}

              {batchCorrection && (
                <details
                  data-testid="results-batch-details"
                  className="group card overflow-hidden [&_summary::-webkit-details-marker]:hidden"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-6 text-left hover:bg-gray-50/80">
                    <div className="min-w-0 flex-1">
                      <h2 className="text-sm font-semibold text-gray-900">
                        Batch Correction ({batchMethod})
                      </h2>
                      <p
                        data-testid="results-batch-collapsed-summary"
                        className="mt-0.5 text-xs text-gray-500"
                      >
                        {formatBatchCollapsedSummary(batchMethod, batchCorrection)}
                      </p>
                    </div>
                    <CollapseChevron />
                  </summary>
                  <div className="border-t border-gray-100 px-6 pb-6 pt-4">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <div>
                        <p className="text-xs text-gray-500">Batch key</p>
                        <p className="text-lg font-semibold text-gray-900">
                          {String(batchCorrection.batch_key ?? 'none')}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Batches</p>
                        <p className="text-lg font-semibold text-gray-900">
                          {Number(batchCorrection.n_batches ?? 0).toLocaleString()}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">kBET proxy</p>
                        <p className="text-lg font-semibold text-gray-900">
                          {Number(batchCorrection.kbet_score ?? 0).toFixed(3)}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">LISI proxy</p>
                        <p className="text-lg font-semibold text-gray-900">
                          {Number(batchCorrection.lisi_score ?? 0).toFixed(3)}
                        </p>
                      </div>
                    </div>
                  </div>
                </details>
              )}
            </div>
          </section>
        )}

      {showDetails && (m.cluster || m.embed || m.annotate) && (
        <section className="space-y-4" aria-labelledby="results-cell-landscape-heading">
          <h2
            id="results-cell-landscape-heading"
            className="text-base font-semibold tracking-tight text-gray-900"
          >
            Cell landscape & annotation
          </h2>
          <p className="text-sm text-gray-600">
            Clustering and embedding are technical views of cell organization; annotation summarizes
            biological labels when available.
          </p>
          <div className="space-y-4">
            {m.cluster && (
              <details
                data-testid="results-clustering-details"
                className="group card overflow-hidden [&_summary::-webkit-details-marker]:hidden"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-6 text-left hover:bg-gray-50/80">
                  <div className="min-w-0 flex-1">
                    <h2 className="text-sm font-semibold text-gray-900">Clustering</h2>
                    <p
                      data-testid="results-clustering-collapsed-summary"
                      className="mt-0.5 text-xs text-gray-500"
                    >
                      {formatClusteringCollapsedSummary(m.cluster)}
                    </p>
                  </div>
                  <CollapseChevron />
                </summary>
                <div className="border-t border-gray-100 px-6 pb-6 pt-4">
                  <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500">
                    <span>
                      {(
                        m.cluster.clusters?.reduce((sum, cluster) => sum + cluster.n_cells, 0) ??
                        m.cluster.cluster_sizes.reduce((a, b) => a + b, 0)
                      ).toLocaleString()}{' '}
                      cells across {m.cluster.n_clusters} clusters
                    </span>
                    {m.cluster.cluster_key && <span>Cluster key: {m.cluster.cluster_key}</span>}
                  </div>
                  <ClusterBar sizes={m.cluster.cluster_sizes} clusters={m.cluster.clusters} />
                </div>
              </details>
            )}

            {m.embed && (
              <details
                data-testid="results-embed-details"
                className="group card overflow-hidden [&_summary::-webkit-details-marker]:hidden"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-6 text-left hover:bg-gray-50/80">
                  <div className="min-w-0 flex-1">
                    <h2 className="text-sm font-semibold text-gray-900">Embedding</h2>
                    <p
                      data-testid="results-embed-collapsed-summary"
                      className="mt-0.5 text-xs text-gray-500"
                    >
                      {formatEmbedCollapsedSummary(m.embed)}
                    </p>
                  </div>
                  <CollapseChevron />
                </summary>
                <div className="border-t border-gray-100 px-6 pb-6 pt-4">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <p className="text-xs text-gray-500">Embedding key</p>
                      <p className="font-semibold text-gray-900">
                        {m.embed.embedding_key ? String(m.embed.embedding_key) : '—'}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-gray-500">Method</p>
                      <p className="font-semibold text-gray-900">
                        {String(m.embed.method_executed ?? m.embed.method_requested ?? '—')}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-gray-500">Representation</p>
                      <p className="font-semibold text-gray-900">
                        {m.embed.representation_used ? String(m.embed.representation_used) : '—'}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-gray-500">Components</p>
                      <p className="font-semibold text-gray-900">
                        {typeof m.embed.n_components === 'number'
                          ? m.embed.n_components.toLocaleString()
                          : '—'}
                      </p>
                    </div>
                  </div>
                </div>
              </details>
            )}

            {m.annotate && (
              <details
                open
                data-testid="results-annotation-details"
                className="group card overflow-hidden [&_summary::-webkit-details-marker]:hidden"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-6 text-left hover:bg-gray-50/80">
                  <div className="min-w-0 flex-1">
                    <h2 className="text-sm font-semibold text-gray-900">Cell type annotation</h2>
                    <p className="mt-0.5 text-xs text-gray-500">
                      Biological labels and confidence for this run.
                    </p>
                  </div>
                  <CollapseChevron />
                </summary>
                <div className="border-t border-gray-100 px-6 pb-6 pt-4">
                  {m.annotate.skipped ? (
                    <div className="space-y-1">
                      <p className="text-sm text-amber-900/90">
                        <span className="font-medium">Analysis skipped.</span>{' '}
                        {m.annotate.reason ?? 'Annotation was not applied for this run.'}
                      </p>
                      {m.annotate.gene_overlap != null && (
                        <p className="text-xs text-gray-400">
                          Gene overlap: {m.annotate.gene_overlap} / {m.annotate.model_genes ?? '?'}{' '}
                          model genes ({m.annotate.dataset_genes?.toLocaleString()} dataset genes)
                        </p>
                      )}
                    </div>
                  ) : (
                    <div className="grid grid-cols-3 gap-4">
                      <div>
                        <p className="text-xs text-gray-500">Cells annotated</p>
                        <p className="text-lg font-semibold">
                          {m.annotate.n_cells_annotated?.toLocaleString()}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Cell types</p>
                        <p className="text-lg font-semibold">{m.annotate.n_cell_types_predicted}</p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Mean confidence</p>
                        <p className="text-lg font-semibold">
                          {((m.annotate.mean_confidence ?? 0) * 100).toFixed(1)}%
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              </details>
            )}
          </div>
        </section>
      )}

      {showDetails && (
        <section className="space-y-4" aria-labelledby="results-downstream-heading">
          <h2
            id="results-downstream-heading"
            className="text-base font-semibold tracking-tight text-gray-900"
          >
            Downstream analyses
          </h2>
          <p className="text-sm text-gray-600">
            Interpreted outputs for differential expression, pathway activity, and ligand–receptor
            inference. Each block follows the same layout: summary metrics, compact preview, and a
            link to the full artifact.
          </p>
          <div className="space-y-4">
            {m.differential_expression ? (
              <DifferentialExpressionSection
                runId={runId}
                artifacts={artifacts}
                metrics={m.differential_expression}
              />
            ) : (
              <DownstreamAnalysisNotRunPanel title="Differential expression" testId="de-section" />
            )}
            {m.pathway_scoring ? (
              <PathwayActivitySection
                runId={runId}
                artifacts={artifacts}
                metrics={m.pathway_scoring}
              />
            ) : (
              <DownstreamAnalysisNotRunPanel
                title="Pathway activity scoring"
                testId="pathway-section"
              />
            )}
            {m.ligand_receptor_analysis ? (
              <LigandReceptorSection
                runId={runId}
                artifacts={artifacts}
                metrics={m.ligand_receptor_analysis}
              />
            ) : (
              <DownstreamAnalysisNotRunPanel
                title="Ligand–receptor analysis"
                testId="liana-section"
              />
            )}
          </div>
        </section>
      )}
    </div>
  );
}
