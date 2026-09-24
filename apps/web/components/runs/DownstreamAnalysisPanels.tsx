'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import type { Artifact } from '@zerna/sdk';

/** Shared copy for downstream analysis preview panes (DE, pathway, LR). */
export const PREVIEW_COPY = {
  loading: 'Loading preview…',
  analysisSkipped: 'This analysis was skipped for this run.',
  noPreviewRows: 'This analysis ran successfully, but no previewable rows were returned.',
  openFullHint: 'You can still open the full results artifact.',
  previewFetchFailed:
    'Preview could not be loaded right now. You can still open the full results artifact.',
  noArtifactAttached:
    'No results file is linked to this run yet. The metrics above still summarize what was computed.',
  metricsNoArtifact:
    'Results metrics are recorded, but no artifact file is linked for preview yet. You can still revisit this run later.',
} as const;

/** API `detail.code` from artifact preview failures → user-facing copy (no raw JSON). */
const ARTIFACT_PREVIEW_SOFT_BY_CODE: Record<string, string> = {
  storage_unreachable: PREVIEW_COPY.previewFetchFailed,
  storage_error: PREVIEW_COPY.previewFetchFailed,
  artifact_missing:
    'Preview could not be loaded because the results file was missing from storage. You can still open the full results page.',
  preview_parse_failed:
    'Preview could not be read as a table. You can still open the full results artifact.',
};

export async function softArtifactPreviewErrorMessage(res: Response): Promise<string> {
  try {
    const data: unknown = await res.json();
    const detail = (data as { detail?: unknown })?.detail;
    if (detail && typeof detail === 'object' && detail !== null && 'code' in detail) {
      const code = String((detail as { code: unknown }).code);
      return ARTIFACT_PREVIEW_SOFT_BY_CODE[code] ?? PREVIEW_COPY.previewFetchFailed;
    }
  } catch {
    // ignore — fall back to generic copy
  }
  return PREVIEW_COPY.previewFetchFailed;
}

export function DownstreamAnalysisNotRunPanel({
  title,
  testId,
}: {
  title: string;
  testId: string;
}) {
  return (
    <div
      className="rounded-xl border border-dashed border-gray-200 bg-gray-50/60 p-5 shadow-sm"
      data-testid={testId}
    >
      <h3 className="text-base font-semibold text-gray-900">{title}</h3>
      <p className="mt-1 text-sm text-gray-600">
        This analysis was not run for this pipeline, or no result metrics were recorded yet.
      </p>
    </div>
  );
}

export interface PathwayStepMetrics {
  n_pathways_scored: number;
  n_cells: number;
  pathway_database: string;
  methods_used: string[];
  obsm_key?: string;
  skipped?: boolean;
  reason?: string;
}

export interface LigandReceptorStepMetrics {
  n_interactions: number;
  n_cluster_pairs: number;
  n_clusters: number;
  cluster_key: string;
  resource_name: string;
  skipped?: boolean;
  reason?: string;
}

export interface DifferentialExpressionStepMetrics {
  de_mode?: string;
  n_clusters?: number | null;
  n_comparisons?: number | null;
  n_genes_tested?: number | null;
  cluster_key?: string | null;
  /** Legacy / alternate API field */
  method?: string;
  method_requested?: string;
  method_executed?: string;
  n_pseudobulk_profiles?: number | null;
  groupby_key_used?: string | null;
  condition_key_used?: string | null;
  sample_key_used?: string | null;
  statistical_warning?: string | null;
  skipped?: boolean;
  reason?: string;
}

interface PreviewPayload {
  columns: string[];
  rows: Record<string, unknown>[];
  total_rows: number | null;
  truncated: boolean;
}

function pathwayColumnsFromPreview(columns: string[]): string[] {
  return columns.filter((c) => c !== 'cell_id' && c !== 'Cell_ID');
}

function topPathwaysByMean(
  rows: Record<string, unknown>[],
  pathwayCols: string[],
  limit: number
): Array<{ pathway: string; mean: number }> {
  const stats = pathwayCols.map((col) => {
    let s = 0;
    let n = 0;
    for (const r of rows) {
      const v = Number(r[col]);
      if (Number.isFinite(v)) {
        s += v;
        n += 1;
      }
    }
    return { pathway: col, mean: n > 0 ? s / n : 0 };
  });
  return [...stats].sort((a, b) => Math.abs(b.mean) - Math.abs(a.mean)).slice(0, limit);
}

function MiniPathwayBars({ items }: { items: Array<{ pathway: string; mean: number }> }) {
  const max = Math.max(...items.map((i) => Math.abs(i.mean)), 1e-12);
  return (
    <div className="space-y-1.5" data-testid="pathway-preview-bars">
      {items.map((i) => (
        <div key={i.pathway} className="flex items-center gap-2 text-xs">
          <span
            className="w-[min(100%,14rem)] shrink-0 truncate font-medium text-gray-800"
            title={i.pathway}
          >
            {i.pathway}
          </span>
          <div className="h-2 min-w-0 flex-1 rounded-full bg-gray-100">
            <div
              className="h-2 rounded-full bg-teal-500"
              style={{ width: `${Math.min(100, (Math.abs(i.mean) / max) * 100)}%` }}
            />
          </div>
          <span className="w-14 shrink-0 tabular-nums text-right text-gray-600">
            {i.mean.toFixed(3)}
          </span>
        </div>
      ))}
    </div>
  );
}

function lrDisplayScore(row: Record<string, unknown>): number {
  const rank = row.liana_rank;
  if (rank != null && Number.isFinite(Number(rank))) return Number(rank);
  return Number(row.interaction_score ?? row.lrscore ?? row.lr_means ?? row.aggregate_rank ?? 0);
}

function topLrRows(rows: Record<string, unknown>[], limit: number): Record<string, unknown>[] {
  const sorted = [...rows].sort((a, b) => {
    const ar = a.liana_rank;
    const br = b.liana_rank;
    if (ar != null && br != null && Number.isFinite(Number(ar)) && Number.isFinite(Number(br))) {
      return Number(ar) - Number(br);
    }
    return lrDisplayScore(b) - lrDisplayScore(a);
  });
  return sorted.slice(0, limit);
}

function isPseudobulkDeArtifact(a: Artifact): boolean {
  const meta = a.metadata ?? {};
  if (meta.kind === 'pseudobulk') return true;
  const path = `${a.s3_path ?? ''}`;
  return path.includes('pseudobulk');
}

/** When multiple `de_results` artifacts exist, pick the one that matches the DE mode. */
export function pickDeResultsArtifact(
  artifacts: Artifact[],
  deMode: string | undefined
): Artifact | undefined {
  const list = artifacts.filter((a) => a.artifact_type === 'de_results');
  if (list.length === 0) return undefined;
  if (list.length === 1) return list[0];
  const mode = (deMode ?? 'marker_ranking').toLowerCase();
  if (mode === 'marker_ranking') {
    const markerFirst = list.find((a) => !isPseudobulkDeArtifact(a));
    return markerFirst ?? list[0];
  }
  const pbFirst = list.find((a) => isPseudobulkDeArtifact(a));
  return pbFirst ?? list[0];
}

function deAdjustedP(row: Record<string, unknown>): number {
  const v =
    row.adjusted_p_value ?? row.pval_adj ?? row.p_adj ?? row.padj ?? row.p_value ?? row.pval;
  const n = Number(v);
  return Number.isFinite(n) ? n : 1;
}

function topDePreviewRows(
  rows: Record<string, unknown>[],
  limit: number
): Record<string, unknown>[] {
  return [...rows].sort((a, b) => deAdjustedP(a) - deAdjustedP(b)).slice(0, limit);
}

function deGroupLabel(row: Record<string, unknown>): string {
  const v =
    row.cluster ?? row.stratum ?? row.group ?? row.contrast ?? row.comparison ?? row.cell_subset;
  if (v == null || v === '') return '—';
  return String(v);
}

function deLogFc(row: Record<string, unknown>): number {
  const v = row.log_fold_change ?? row.logfoldchange ?? row.log2FoldChange ?? row.lfc;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function deGene(row: Record<string, unknown>): string {
  const g = row.gene ?? row.gene_symbol ?? row.names;
  return g != null ? String(g) : '—';
}

export function deModeLabel(deMode: string | undefined): string {
  switch ((deMode ?? '').toLowerCase()) {
    case 'marker_ranking':
      return 'Marker ranking';
    case 'condition_de_within_celltype':
      return 'Condition DE within cell type';
    case 'pseudobulk_sample_level_contrast':
      return 'Pseudobulk sample-level contrast';
    default:
      return deMode && deMode.trim() ? deMode : 'Differential expression';
  }
}

/** Table header: pseudobulk/count-model outputs use log2-style effects, not Welch on log1p(CPM). */
export function deEffectSizeColumnLabel(deMode: string | undefined): string {
  const m = (deMode ?? '').toLowerCase();
  if (m === 'pseudobulk_sample_level_contrast' || m === 'condition_de_within_celltype') {
    return 'Effect (log2-scale)';
  }
  return 'log2 FC';
}

function dePreviewInterpretation(deMode: string | undefined): string {
  switch ((deMode ?? '').toLowerCase()) {
    case 'marker_ranking':
      return 'Preview shows top genes by the cell-level ranking test below (not a pseudobulk count model).';
    case 'condition_de_within_celltype':
      return 'Preview shows top genes from replicate-aware pseudobulk contrasts within the selected cell subset (count-model backend).';
    case 'pseudobulk_sample_level_contrast':
      return 'Preview shows top genes from replicate-aware, sample-level pseudobulk inference (count-model backend).';
    default:
      return 'Preview shows top-ranked genes from the saved differential expression table.';
  }
}

function deSummaryLine(deMode: string | undefined): string {
  switch ((deMode ?? '').toLowerCase()) {
    case 'marker_ranking':
      return 'Exploratory marker genes are ranked per group using the method below (Scanpy rank_genes_groups–style; not sample-level inference).';
    case 'condition_de_within_celltype':
      return 'Replicate-aware pseudobulk contrasts are run within a cell-type or subset stratum using sample metadata and a count-based model.';
    case 'pseudobulk_sample_level_contrast':
      return 'Replicate-aware pseudobulk differential expression is run at the sample level using the contrast and keys below.';
    default:
      return 'Differential expression results summarize gene-level changes for this run.';
  }
}

function isPseudobulkStyleDeMode(deMode: string | undefined): boolean {
  const m = (deMode ?? '').toLowerCase();
  return m === 'pseudobulk_sample_level_contrast' || m === 'condition_de_within_celltype';
}

function methodDisplay(m: DifferentialExpressionStepMetrics): string {
  const raw = m.method_executed ?? m.method ?? m.method_requested ?? '';
  return typeof raw === 'string' && raw.trim() ? raw.trim() : '—';
}

function DownstreamPreviewPane({
  loading,
  error,
  hasArtifactId,
  hasRenderablePreview,
  children,
  truncatedNote,
  noArtifactMessage,
}: {
  loading: boolean;
  error: string | null;
  hasArtifactId: boolean;
  hasRenderablePreview: boolean;
  children: React.ReactNode;
  truncatedNote?: React.ReactNode;
  /** When the analysis has metrics but no linked artifact (e.g. file not registered yet). */
  noArtifactMessage?: string;
}) {
  if (loading) {
    return <p className="mt-2 text-sm text-gray-500">{PREVIEW_COPY.loading}</p>;
  }
  if (error) {
    return (
      <p className="mt-2 text-sm text-amber-900/90" data-testid="downstream-preview-failure">
        {error}
      </p>
    );
  }
  if (hasRenderablePreview) {
    return (
      <div className="mt-2">
        {children}
        {truncatedNote}
      </div>
    );
  }
  if (hasArtifactId) {
    return (
      <div className="mt-2 space-y-1 text-sm text-gray-600">
        <p>{PREVIEW_COPY.noPreviewRows}</p>
        <p className="text-xs text-gray-500">{PREVIEW_COPY.openFullHint}</p>
      </div>
    );
  }
  return (
    <p className="mt-2 text-sm text-gray-600" data-testid="downstream-no-artifact">
      {noArtifactMessage ?? PREVIEW_COPY.noArtifactAttached}
    </p>
  );
}

export function PathwayActivitySection({
  runId,
  artifacts,
  metrics,
}: {
  runId: string;
  artifacts: Artifact[];
  metrics: PathwayStepMetrics;
}) {
  const artifact = artifacts.find((a) => a.artifact_type === 'pathway_scores');
  const [preview, setPreview] = useState<PreviewPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!artifact?.id || metrics.skipped) {
      setPreview(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const res = await fetch(
          `/api/proxy/v1/runs/${runId}/artifacts/${artifact.id}/preview?limit=80`
        );
        if (!res.ok) {
          if (!cancelled) setError(await softArtifactPreviewErrorMessage(res));
          return;
        }
        const data = (await res.json()) as PreviewPayload;
        if (!cancelled) setPreview(data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : PREVIEW_COPY.previewFetchFailed);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId, artifact?.id, metrics.skipped]);

  const topPathways = useMemo(() => {
    if (!preview) return [];
    const colNames =
      (preview.columns?.length ?? 0) > 0
        ? preview.columns!
        : preview.rows[0]
          ? Object.keys(preview.rows[0])
          : [];
    const cols = pathwayColumnsFromPreview(colNames);
    if (cols.length === 0) return [];
    return topPathwaysByMean(preview.rows, cols, 8);
  }, [preview]);

  if (metrics.skipped) {
    return (
      <div
        className="rounded-xl border border-amber-200 bg-amber-50/50 p-5 shadow-sm"
        data-testid="pathway-section"
      >
        <h3 className="text-base font-semibold text-gray-900">Pathway activity scoring</h3>
        <p className="mt-1 text-sm text-amber-900/90">
          <span className="font-medium">Analysis skipped.</span>{' '}
          {metrics.reason ?? 'This step was not executed for this pipeline run.'}
        </p>
      </div>
    );
  }

  const methods = Array.isArray(metrics.methods_used) ? metrics.methods_used.join(', ') : '—';

  return (
    <div
      className="rounded-xl border border-teal-200/80 bg-gradient-to-br from-white to-teal-50/40 p-4 shadow-sm"
      data-testid="pathway-section"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-gray-900">Pathway activity scoring</h3>
          <p className="mt-1 max-w-3xl text-sm text-gray-600">
            Per-cell pathway activity scores quantify pathway signal strength in each cell using the
            selected gene-set resource.
          </p>
        </div>
        {artifact?.id ? (
          <Link
            href={`/runs/${runId}/artifacts/${artifact.id}`}
            className="shrink-0 rounded-lg border border-teal-600 bg-teal-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-teal-700"
            data-testid="pathway-view-full-link"
          >
            View full pathway results
          </Link>
        ) : null}
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <dt className="text-xs font-medium text-gray-500">Database</dt>
          <dd className="text-sm font-semibold text-gray-900">{metrics.pathway_database}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">Methods</dt>
          <dd className="text-sm font-semibold text-gray-900">{methods}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">Pathways scored</dt>
          <dd className="text-sm font-semibold text-gray-900">
            {metrics.n_pathways_scored.toLocaleString()}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">Cells</dt>
          <dd className="text-sm font-semibold text-gray-900">
            {metrics.n_cells.toLocaleString()}
          </dd>
        </div>
      </dl>

      <div className="mt-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Preview</p>
        <p className="mt-1 text-xs text-gray-500" data-testid="pathway-preview-interpretation">
          Preview shows the strongest pathway activity signals in the scored cells. This is not a
          formal enrichment ranking against a background set.
        </p>
        <DownstreamPreviewPane
          loading={loading}
          error={error}
          hasArtifactId={Boolean(artifact?.id)}
          hasRenderablePreview={topPathways.length > 0}
          noArtifactMessage={PREVIEW_COPY.metricsNoArtifact}
          truncatedNote={
            preview?.truncated ? (
              <p className="mt-2 text-xs text-gray-400">
                Based on a sample of rows from the saved file.
              </p>
            ) : null
          }
        >
          <MiniPathwayBars items={topPathways} />
        </DownstreamPreviewPane>
      </div>
    </div>
  );
}

export function LigandReceptorSection({
  runId,
  artifacts,
  metrics,
}: {
  runId: string;
  artifacts: Artifact[];
  metrics: LigandReceptorStepMetrics;
}) {
  const artifact = artifacts.find((a) => a.artifact_type === 'liana_results');
  const [preview, setPreview] = useState<PreviewPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!artifact?.id || metrics.skipped) {
      setPreview(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const res = await fetch(
          `/api/proxy/v1/runs/${runId}/artifacts/${artifact.id}/preview?limit=50`
        );
        if (!res.ok) {
          if (!cancelled) setError(await softArtifactPreviewErrorMessage(res));
          return;
        }
        const data = (await res.json()) as PreviewPayload;
        if (!cancelled) setPreview(data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : PREVIEW_COPY.previewFetchFailed);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId, artifact?.id, metrics.skipped]);

  const topRows = useMemo(() => {
    if (!preview?.rows.length) return [];
    return topLrRows(preview.rows, 6);
  }, [preview]);

  if (metrics.skipped) {
    return (
      <div
        className="rounded-xl border border-amber-200 bg-amber-50/50 p-5 shadow-sm"
        data-testid="liana-section"
      >
        <h3 className="text-base font-semibold text-gray-900">Ligand–receptor analysis</h3>
        <p className="mt-1 text-sm text-amber-900/90">
          <span className="font-medium">Analysis skipped.</span>{' '}
          {metrics.reason ?? 'This step was not executed for this pipeline run.'}
        </p>
      </div>
    );
  }

  return (
    <div
      className="rounded-xl border border-violet-200/80 bg-gradient-to-br from-white to-violet-50/40 p-4 shadow-sm"
      data-testid="liana-section"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-gray-900">Ligand–receptor analysis</h3>
          <p className="mt-1 max-w-3xl text-sm text-gray-600">
            LIANA-based inference of cell–cell communication using the selected ligand–receptor
            resource.
          </p>
        </div>
        {artifact?.id ? (
          <Link
            href={`/runs/${runId}/artifacts/${artifact.id}`}
            className="shrink-0 rounded-lg border border-violet-600 bg-violet-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-violet-700"
            data-testid="liana-view-full-link"
          >
            View full ligand–receptor results
          </Link>
        ) : null}
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <dt className="text-xs font-medium text-gray-500">Resource</dt>
          <dd className="text-sm font-semibold text-gray-900">{metrics.resource_name}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">Interactions</dt>
          <dd className="text-sm font-semibold text-gray-900">
            {metrics.n_interactions.toLocaleString()}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">Cluster pairs</dt>
          <dd className="text-sm font-semibold text-gray-900">
            {metrics.n_cluster_pairs.toLocaleString()}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">Clusters</dt>
          <dd className="text-sm font-semibold text-gray-900">
            {metrics.n_clusters.toLocaleString()}
          </dd>
        </div>
      </dl>
      <p className="mt-2 text-xs text-gray-500">Cluster key: {metrics.cluster_key}</p>

      <div className="mt-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Preview</p>
        <p className="mt-1 text-xs text-gray-500" data-testid="liana-preview-interpretation">
          Preview shows top inferred interactions by LIANA aggregate rank.
        </p>
        <DownstreamPreviewPane
          loading={loading}
          error={error}
          hasArtifactId={Boolean(artifact?.id)}
          hasRenderablePreview={topRows.length > 0}
          noArtifactMessage={PREVIEW_COPY.metricsNoArtifact}
        >
          <div
            className="overflow-x-auto rounded-lg border border-gray-100 bg-white/80"
            data-testid="liana-preview-table"
          >
            <table className="w-full min-w-[32rem] text-left text-xs">
              <thead>
                <tr className="border-b border-gray-100 text-gray-500">
                  <th className="px-2 py-1.5 font-medium">Source</th>
                  <th className="px-2 py-1.5 font-medium">Target</th>
                  <th className="px-2 py-1.5 font-medium">Ligand</th>
                  <th className="px-2 py-1.5 font-medium">Receptor</th>
                  <th className="px-2 py-1.5 font-medium text-right">Score</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {topRows.map((row, idx) => (
                  <tr key={idx} className="text-gray-800">
                    <td className="px-2 py-1 font-mono">
                      {String(row.source ?? row.source_cluster ?? '—')}
                    </td>
                    <td className="px-2 py-1 font-mono">
                      {String(row.target ?? row.target_cluster ?? '—')}
                    </td>
                    <td className="px-2 py-1">{String(row.ligand ?? row.ligand_complex ?? '—')}</td>
                    <td className="px-2 py-1">
                      {String(row.receptor ?? row.receptor_complex ?? '—')}
                    </td>
                    <td className="px-2 py-1 text-right tabular-nums">
                      {lrDisplayScore(row).toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DownstreamPreviewPane>
      </div>
    </div>
  );
}

export function DifferentialExpressionSection({
  runId,
  artifacts,
  metrics,
}: {
  runId: string;
  artifacts: Artifact[];
  metrics: DifferentialExpressionStepMetrics;
}) {
  const deMode = metrics.de_mode;
  const artifact = useMemo(() => pickDeResultsArtifact(artifacts, deMode), [artifacts, deMode]);
  const [preview, setPreview] = useState<PreviewPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!artifact?.id || metrics.skipped) {
      setPreview(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const res = await fetch(
          `/api/proxy/v1/runs/${runId}/artifacts/${artifact.id}/preview?limit=40`
        );
        if (!res.ok) {
          if (!cancelled) setError(await softArtifactPreviewErrorMessage(res));
          return;
        }
        const data = (await res.json()) as PreviewPayload;
        if (!cancelled) setPreview(data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : PREVIEW_COPY.previewFetchFailed);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId, artifact?.id, metrics.skipped]);

  const topRows = useMemo(() => {
    if (!preview?.rows?.length) return [];
    return topDePreviewRows(preview.rows, 8);
  }, [preview]);

  if (metrics.skipped) {
    return (
      <div
        className="rounded-xl border border-amber-200 bg-amber-50/50 p-5 shadow-sm"
        data-testid="de-section"
      >
        <h3 className="text-base font-semibold text-gray-900">Differential expression</h3>
        <p className="mt-1 text-sm text-amber-900/90">
          <span className="font-medium">Analysis skipped.</span>{' '}
          {metrics.reason ?? 'This step was not executed for this pipeline run.'}
        </p>
      </div>
    );
  }

  const groupby = metrics.groupby_key_used ?? metrics.cluster_key ?? null;
  const nComp = metrics.n_comparisons;
  const nGenes = metrics.n_genes_tested;

  return (
    <div
      className="rounded-xl border border-sky-200/80 bg-gradient-to-br from-white to-sky-50/40 p-4 shadow-sm"
      data-testid="de-section"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-gray-900">Differential expression</h3>
          <p className="mt-1 max-w-3xl text-sm text-gray-600">{deSummaryLine(deMode)}</p>
          <p className="mt-2 flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-sky-100 px-2.5 py-0.5 text-xs font-semibold text-sky-900">
              Mode: {deModeLabel(deMode)}
            </span>
            {isPseudobulkStyleDeMode(deMode) ? (
              <>
                <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-800">
                  Replicate-aware
                </span>
                <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-800">
                  Pseudobulk
                </span>
                <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-800">
                  Count-model backend
                </span>
              </>
            ) : null}
          </p>
        </div>
        {artifact?.id ? (
          <Link
            href={`/runs/${runId}/artifacts/${artifact.id}`}
            className="shrink-0 rounded-lg border border-sky-600 bg-sky-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-sky-700"
            data-testid="de-view-full-link"
          >
            View full differential expression results
          </Link>
        ) : null}
      </div>

      {metrics.statistical_warning ? (
        <div
          className="mt-3 rounded-md border border-amber-200/90 bg-amber-50/90 px-3 py-2 text-xs text-amber-950"
          data-testid="de-statistical-warning"
        >
          {metrics.statistical_warning}
        </div>
      ) : null}

      <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <dt className="text-xs font-medium text-gray-500">
            {isPseudobulkStyleDeMode(deMode) ? 'Inferential backend' : 'Method / backend'}
          </dt>
          <dd className="text-sm font-semibold text-gray-900">{methodDisplay(metrics)}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">Groupby key</dt>
          <dd className="text-sm font-semibold text-gray-900">
            {groupby != null && String(groupby).trim() !== '' ? String(groupby) : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">Condition key</dt>
          <dd className="text-sm font-semibold text-gray-900">
            {metrics.condition_key_used != null && String(metrics.condition_key_used).trim() !== ''
              ? String(metrics.condition_key_used)
              : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">Sample key</dt>
          <dd className="text-sm font-semibold text-gray-900">
            {metrics.sample_key_used != null && String(metrics.sample_key_used).trim() !== ''
              ? String(metrics.sample_key_used)
              : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">Comparisons</dt>
          <dd className="text-sm font-semibold text-gray-900">
            {typeof nComp === 'number' && Number.isFinite(nComp) ? nComp.toLocaleString() : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">Genes tested / reported</dt>
          <dd className="text-sm font-semibold text-gray-900">
            {typeof nGenes === 'number' && Number.isFinite(nGenes) ? nGenes.toLocaleString() : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">Clusters (marker mode)</dt>
          <dd className="text-sm font-semibold text-gray-900">
            {typeof metrics.n_clusters === 'number' && Number.isFinite(metrics.n_clusters)
              ? metrics.n_clusters.toLocaleString()
              : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">Pseudobulk profiles</dt>
          <dd className="text-sm font-semibold text-gray-900">
            {typeof metrics.n_pseudobulk_profiles === 'number' &&
            Number.isFinite(metrics.n_pseudobulk_profiles)
              ? metrics.n_pseudobulk_profiles.toLocaleString()
              : '—'}
          </dd>
        </div>
      </dl>

      <div className="mt-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Preview</p>
        <p className="mt-1 text-xs text-gray-500" data-testid="de-preview-interpretation">
          {dePreviewInterpretation(deMode)}
        </p>
        <DownstreamPreviewPane
          loading={loading}
          error={error}
          hasArtifactId={Boolean(artifact?.id)}
          hasRenderablePreview={topRows.length > 0}
          noArtifactMessage={PREVIEW_COPY.metricsNoArtifact}
          truncatedNote={
            preview?.truncated ? (
              <p className="mt-2 text-xs text-gray-400">
                Based on a sample of rows from the saved file.
              </p>
            ) : null
          }
        >
          <div
            className="overflow-x-auto rounded-lg border border-gray-100 bg-white/80"
            data-testid="de-preview-table"
          >
            <table className="w-full min-w-[28rem] text-left text-xs">
              <thead>
                <tr className="border-b border-gray-100 text-gray-500">
                  <th className="px-2 py-1.5 font-medium">Gene</th>
                  <th className="px-2 py-1.5 font-medium">Group / contrast</th>
                  <th className="px-2 py-1.5 font-medium text-right">
                    {deEffectSizeColumnLabel(deMode)}
                  </th>
                  <th className="px-2 py-1.5 font-medium text-right">Adj. p</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {topRows.map((row, idx) => (
                  <tr key={idx} className="text-gray-800">
                    <td className="px-2 py-1 font-medium">{deGene(row)}</td>
                    <td className="px-2 py-1 font-mono text-[11px]">{deGroupLabel(row)}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{deLogFc(row).toFixed(3)}</td>
                    <td className="px-2 py-1 text-right tabular-nums">
                      {deAdjustedP(row).toExponential(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DownstreamPreviewPane>
      </div>
    </div>
  );
}
