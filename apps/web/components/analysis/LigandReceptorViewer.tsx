'use client';

import { useCallback, useMemo, useState } from 'react';
import type { AxisSortMode, LrPairMetric, NormalizedLRRow } from '@/lib/ligand-receptor';
import {
  allowedLrPairMetrics,
  getDatasetScoreSemantics,
  normalizeLigandReceptorRows,
} from '@/lib/ligand-receptor';
import LigandReceptorDetailPanel from '@/components/analysis/lr/LigandReceptorDetailPanel';
import LigandReceptorOverview from '@/components/analysis/lr/LigandReceptorOverview';
import LigandReceptorRankedTable from '@/components/analysis/lr/LigandReceptorRankedTable';

/** @deprecated Prefer passing raw `rows`; kept for tests and legacy call sites. */
export interface LRInteraction {
  source_cluster: string;
  target_cluster: string;
  ligand: string;
  receptor: string;
  interaction_score: number;
  p_value: number;
}

function formatValue(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (Math.abs(value) >= 1000 || Number.isInteger(value)) return String(value);
    return String(value);
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

function csvEscape(cell: string): string {
  if (/[",\n\r]/.test(cell)) return `"${cell.replace(/"/g, '""')}"`;
  return cell;
}

function downloadCsv(filename: string, headers: string[], lines: string[][]) {
  const body = [
    headers.map(csvEscape).join(','),
    ...lines.map((row) => row.map(csvEscape).join(',')),
  ].join('\r\n');
  const blob = new Blob([body], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function lineagePrefix(label: string): string | null {
  const idx = label.indexOf(':');
  if (idx <= 0) return null;
  return label.slice(0, idx);
}

function uniqueLineagePrefixes(rows: NormalizedLRRow[]): string[] {
  const s = new Set<string>();
  for (const r of rows) {
    const ps = lineagePrefix(r.sender);
    const pr = lineagePrefix(r.receiver);
    if (ps) s.add(ps);
    if (pr) s.add(pr);
  }
  return [...s].sort((a, b) => a.localeCompare(b));
}

export interface LigandReceptorViewerProps {
  /** Raw artifact rows (preferred). */
  rows?: Record<string, unknown>[];
  columns?: string[];
  /** Legacy shape — used only when `rows` is omitted. */
  interactions?: LRInteraction[];
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** API `truncated`: preview row cap is below total file rows. */
  previewTruncated?: boolean;
  /** Rows returned in the current preview payload (for messaging). */
  previewLoadedRowCount?: number | null;
  /** Optional total rows from artifact metadata when known. */
  previewTotalRows?: number | null;
}

function legacyToRows(interactions: LRInteraction[]): Record<string, unknown>[] {
  return interactions.map((i) => ({
    source_cluster: i.source_cluster,
    target_cluster: i.target_cluster,
    ligand: i.ligand,
    receptor: i.receptor,
    interaction_score: i.interaction_score,
    p_value: i.p_value,
  }));
}

export default function LigandReceptorViewer({
  rows: rowsProp,
  columns = [],
  interactions,
  isLoading = false,
  error = null,
  onRetry,
  previewTruncated = false,
  previewLoadedRowCount = null,
  previewTotalRows = null,
}: LigandReceptorViewerProps) {
  const rawRows = rowsProp ?? legacyToRows(interactions ?? []);

  const normalizedAll = useMemo(() => normalizeLigandReceptorRows(rawRows), [rawRows]);

  const datasetSemantics = useMemo(() => getDatasetScoreSemantics(normalizedAll), [normalizedAll]);

  const allowedMetrics = useMemo(() => allowedLrPairMetrics(datasetSemantics), [datasetSemantics]);

  const [senderFilter, setSenderFilter] = useState('');
  const [receiverFilter, setReceiverFilter] = useState('');
  const [lrSearch, setLrSearch] = useState('');
  const [minScore, setMinScore] = useState(0);
  const [maxP, setMaxP] = useState(0.05);
  const [includeNoP, setIncludeNoP] = useState(true);
  const [selfOnly, setSelfOnly] = useState(false);
  const [lineageFilter, setLineageFilter] = useState('');

  const [pairMetric, setPairMetric] = useState<LrPairMetric>('count');
  const [axisSort, setAxisSort] = useState<AxisSortMode>('strength');
  const [overviewTab, setOverviewTab] = useState<'heatmap' | 'network'>('heatmap');

  const [selectedPair, setSelectedPair] = useState<{ sender: string; receiver: string } | null>(
    null
  );
  const [pinnedPair, setPinnedPair] = useState<{ sender: string; receiver: string } | null>(null);

  const [explorerTab, setExplorerTab] = useState<'explorer' | 'raw'>('explorer');

  const pairMetricEffective = allowedMetrics.includes(pairMetric) ? pairMetric : 'count';

  const senderOptions = useMemo(() => {
    const u = new Set<string>();
    for (const r of normalizedAll) u.add(r.sender);
    return [...u].sort((a, b) => a.localeCompare(b));
  }, [normalizedAll]);

  const receiverOptions = useMemo(() => {
    const u = new Set<string>();
    for (const r of normalizedAll) u.add(r.receiver);
    return [...u].sort((a, b) => a.localeCompare(b));
  }, [normalizedAll]);

  const lineageOptions = useMemo(() => uniqueLineagePrefixes(normalizedAll), [normalizedAll]);

  const filteredRows = useMemo(() => {
    const q = lrSearch.trim().toLowerCase();
    return normalizedAll.filter((r) => {
      if (senderFilter && r.sender !== senderFilter) return false;
      if (receiverFilter && r.receiver !== receiverFilter) return false;
      if (r.score < minScore) return false;
      if (selfOnly && r.sender !== r.receiver) return false;
      if (lineageFilter) {
        const ps = lineagePrefix(r.sender);
        const pr = lineagePrefix(r.receiver);
        if (ps !== lineageFilter && pr !== lineageFilter) return false;
      }
      if (q) {
        const hit =
          r.ligand.toLowerCase().includes(q) ||
          r.receptor.toLowerCase().includes(q) ||
          r.interaction_name.toLowerCase().includes(q);
        if (!hit) return false;
      }
      if (r.p_value_numeric == null) {
        if (!includeNoP) return false;
      } else if (r.p_value_numeric > maxP) {
        return false;
      }
      return true;
    });
  }, [
    normalizedAll,
    senderFilter,
    receiverFilter,
    lrSearch,
    minScore,
    maxP,
    includeNoP,
    selfOnly,
    lineageFilter,
  ]);

  const effectiveHighlight = pinnedPair ?? selectedPair;

  const summary = useMemo(() => {
    const significant = filteredRows.filter(
      (r) => r.p_value_numeric != null && r.p_value_numeric <= maxP
    );
    const senders = new Set(filteredRows.map((r) => r.sender));
    const receivers = new Set(filteredRows.map((r) => r.receiver));
    const byName = new Map<string, number>();
    const outDeg = new Map<string, number>();
    const inDeg = new Map<string, number>();
    for (const r of filteredRows) {
      byName.set(r.interaction_name, (byName.get(r.interaction_name) ?? 0) + 1);
      outDeg.set(r.sender, (outDeg.get(r.sender) ?? 0) + 1);
      inDeg.set(r.receiver, (inDeg.get(r.receiver) ?? 0) + 1);
    }
    const topName = [...byName.entries()].sort((a, b) => b[1] - a[1])[0];
    const topSender = [...outDeg.entries()].sort((a, b) => b[1] - a[1])[0];
    const topReceiver = [...inDeg.entries()].sort((a, b) => b[1] - a[1])[0];
    return {
      nSig: significant.length,
      nSenders: senders.size,
      nReceivers: receivers.size,
      topInteraction: topName ? `${topName[0]} (${topName[1]})` : '—',
      topSender: topSender ? `${topSender[0]} (${topSender[1]})` : '—',
      topReceiver: topReceiver ? `${topReceiver[0]} (${topReceiver[1]})` : '—',
    };
  }, [filteredRows, maxP]);

  const detailPair = pinnedPair ?? selectedPair;
  const pinnedHiddenByFilters =
    pinnedPair != null &&
    !filteredRows.some((r) => r.sender === pinnedPair.sender && r.receiver === pinnedPair.receiver);
  const canExportPair =
    detailPair != null &&
    filteredRows.some((r) => r.sender === detailPair.sender && r.receiver === detailPair.receiver);

  const onSelectPair = useCallback((p: { sender: string; receiver: string } | null) => {
    setSelectedPair(p);
  }, []);

  const exportFiltered = useCallback(() => {
    const headers = [
      'sender',
      'receiver',
      'ligand',
      'receptor',
      'interaction_name',
      'score',
      'p_value',
    ];
    const lines = filteredRows.map((r) => [
      r.sender,
      r.receiver,
      r.ligand,
      r.receptor,
      r.interaction_name,
      String(r.score),
      r.p_value,
    ]);
    downloadCsv('ligand_receptor_filtered.csv', headers, lines);
  }, [filteredRows]);

  const exportSelectedPair = useCallback(() => {
    if (!detailPair) return;
    const pr = filteredRows.filter(
      (r) => r.sender === detailPair.sender && r.receiver === detailPair.receiver
    );
    const headers = [
      'sender',
      'receiver',
      'ligand',
      'receptor',
      'interaction_name',
      'score',
      'p_value',
    ];
    const lines = pr.map((r) => [
      r.sender,
      r.receiver,
      r.ligand,
      r.receptor,
      r.interaction_name,
      String(r.score),
      r.p_value,
    ]);
    const safe = `${detailPair.sender}_${detailPair.receiver}`
      .replace(/[^\w.-]+/g, '_')
      .slice(0, 80);
    downloadCsv(`ligand_receptor_pair_${safe}.csv`, headers, lines);
  }, [detailPair, filteredRows]);

  if (isLoading) {
    return (
      <div
        className="card p-6 flex items-center justify-center min-h-64"
        data-testid="lr-viewer-loading"
      >
        <div className="flex flex-col items-center gap-3 text-gray-500">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600" />
          <span className="text-sm">Loading interaction data…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="card p-6 flex items-center justify-center min-h-64"
        data-testid="lr-viewer-error"
      >
        <div className="flex flex-col items-center gap-3 text-center">
          <p className="text-sm text-red-600">{error}</p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
            >
              Retry
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="lr-viewer">
      <div className="flex flex-wrap gap-2 rounded-lg border border-gray-200 bg-white p-1 text-sm font-medium">
        <button
          type="button"
          className={`rounded-md px-3 py-1.5 ${explorerTab === 'explorer' ? 'bg-violet-600 text-white' : 'text-gray-600'}`}
          onClick={() => setExplorerTab('explorer')}
          data-testid="lr-mode-explorer"
        >
          Explorer
        </button>
        <button
          type="button"
          className={`rounded-md px-3 py-1.5 ${explorerTab === 'raw' ? 'bg-violet-600 text-white' : 'text-gray-600'}`}
          onClick={() => setExplorerTab('raw')}
          data-testid="lr-mode-raw"
        >
          Raw artifact table
        </button>
      </div>

      {explorerTab === 'raw' ? (
        <div className="card overflow-x-auto p-4" data-testid="lr-raw-table">
          <h3 className="text-sm font-semibold text-gray-800">Original columns (preview rows)</h3>
          <p className="mt-1 text-xs text-gray-500">
            Unmodified fields from the results file. The explorer uses normalized sender, receiver,
            ligand, receptor, score, and p-value columns.
          </p>
          {columns.length === 0 ? (
            <p className="mt-4 text-sm text-gray-500">No column metadata available.</p>
          ) : (
            <table className="mt-4 w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-xs text-gray-500">
                  {columns.map((c) => (
                    <th key={c} className="pb-2 pr-3 text-left font-medium">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rawRows.slice(0, 200).map((row, index) => (
                  <tr key={index}>
                    {columns.map((col) => (
                      <td key={col} className="py-1.5 pr-3 align-top text-xs text-gray-700">
                        <span className="font-mono">{formatValue(row[col])}</span>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {rawRows.length > 200 && (
            <p className="mt-2 text-xs text-gray-400">
              Showing first 200 of {rawRows.length.toLocaleString()} loaded preview rows.
            </p>
          )}
        </div>
      ) : normalizedAll.length === 0 ? (
        <div
          className="card border border-amber-200 bg-amber-50/60 p-5 text-sm text-amber-950"
          data-testid="lr-normalize-empty"
        >
          <p className="font-medium">
            No ligand–receptor rows could be normalized from this preview.
          </p>
          <p className="mt-2 text-amber-900/90">
            Expected columns such as sender/source, receiver/target, ligand, receptor, and a numeric
            score. Open the raw artifact table tab to inspect column names, or increase the preview
            row limit if the file is large.
          </p>
        </div>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="lr-summary-cards">
            <div className="rounded-lg border border-violet-100 bg-white p-3 shadow-sm">
              <p className="text-xs font-medium text-gray-500">
                Significant interactions (p ≤ {maxP})
              </p>
              <p className="mt-1 text-lg font-semibold text-gray-900">
                {summary.nSig.toLocaleString()}
              </p>
              <p className="mt-0.5 text-[10px] text-gray-400">Within filtered rows</p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-white p-3 shadow-sm">
              <p className="text-xs font-medium text-gray-500">Unique senders</p>
              <p className="mt-1 text-lg font-semibold text-gray-900">
                {summary.nSenders.toLocaleString()}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-white p-3 shadow-sm">
              <p className="text-xs font-medium text-gray-500">Unique receivers</p>
              <p className="mt-1 text-lg font-semibold text-gray-900">
                {summary.nReceivers.toLocaleString()}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-white p-3 shadow-sm sm:col-span-2 lg:col-span-1">
              <p className="text-xs font-medium text-gray-500">Top recurrent interaction</p>
              <p
                className="mt-1 break-words text-sm font-semibold text-gray-900"
                title={summary.topInteraction}
              >
                {summary.topInteraction}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-white p-3 shadow-sm">
              <p className="text-xs font-medium text-gray-500">Top sender (outgoing count)</p>
              <p
                className="mt-1 break-words text-sm font-semibold text-gray-900"
                title={summary.topSender}
              >
                {summary.topSender}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-white p-3 shadow-sm">
              <p className="text-xs font-medium text-gray-500">Top receiver (incoming count)</p>
              <p
                className="mt-1 break-words text-sm font-semibold text-gray-900"
                title={summary.topReceiver}
              >
                {summary.topReceiver}
              </p>
            </div>
          </div>

          {previewTruncated ? (
            <div
              className="rounded-lg border border-amber-200 bg-amber-50/90 px-3 py-2.5 text-xs text-amber-950"
              data-testid="lr-preview-truncation-warning"
            >
              <span className="font-semibold">Preview truncated.</span> Summaries, heatmap, network,
              table, and exports reflect <strong>loaded preview rows only</strong>
              {previewLoadedRowCount != null ? (
                <>
                  {' '}
                  (currently {previewLoadedRowCount.toLocaleString()}
                  {previewTotalRows != null
                    ? ` of ${previewTotalRows.toLocaleString()} in the file`
                    : ''}
                  ).
                </>
              ) : (
                '.'
              )}{' '}
              Download the full artifact for complete results.
            </div>
          ) : null}

          <div className="card p-4 space-y-3" data-testid="lr-global-filters">
            <h3 className="text-sm font-semibold text-gray-800">Filters</h3>
            {normalizedAll[0] ? (
              <p className="text-xs text-gray-500">
                Numeric column:{' '}
                <span className="font-mono text-gray-700">{normalizedAll[0].score_source}</span>
                {' · '}
                {normalizedAll[0].score_semantics === 'strength' ? (
                  <span>interpreted as communication strength (higher = stronger)</span>
                ) : normalizedAll[0].score_semantics === 'rank' ? (
                  <span>interpreted as rank (lower = better); pair overview uses counts only</span>
                ) : (
                  <span>interpretation unclear; pair overview uses counts only</span>
                )}
              </p>
            ) : null}
            <div className="flex flex-wrap gap-3 text-sm">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-gray-500">Sender</span>
                <select
                  value={senderFilter}
                  onChange={(e) => setSenderFilter(e.target.value)}
                  className="min-w-[10rem] rounded-md border border-gray-300 bg-white px-2 py-1 text-xs"
                >
                  <option value="">All senders</option>
                  {senderOptions.map((s) => (
                    <option key={s} value={s}>
                      {s.length > 48 ? `${s.slice(0, 45)}…` : s}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-gray-500">Receiver</span>
                <select
                  value={receiverFilter}
                  onChange={(e) => setReceiverFilter(e.target.value)}
                  className="min-w-[10rem] rounded-md border border-gray-300 bg-white px-2 py-1 text-xs"
                >
                  <option value="">All receivers</option>
                  {receiverOptions.map((s) => (
                    <option key={s} value={s}>
                      {s.length > 48 ? `${s.slice(0, 45)}…` : s}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-gray-500">Ligand / receptor search</span>
                <input
                  type="search"
                  value={lrSearch}
                  onChange={(e) => setLrSearch(e.target.value)}
                  placeholder="Substring match"
                  className="w-48 rounded-md border border-gray-300 bg-white px-2 py-1 text-xs"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-gray-500">Min score</span>
                <input
                  type="number"
                  step={0.001}
                  value={minScore}
                  onChange={(e) => setMinScore(Number(e.target.value) || 0)}
                  className="w-24 rounded-md border border-gray-300 bg-white px-2 py-1 text-xs"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-gray-500">Max p (numeric)</span>
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  value={maxP}
                  onChange={(e) => setMaxP(Number(e.target.value) || 1)}
                  className="w-24 rounded-md border border-gray-300 bg-white px-2 py-1 text-xs"
                />
              </label>
              <label className="flex items-center gap-2 pt-5 text-xs text-gray-600">
                <input
                  type="checkbox"
                  checked={includeNoP}
                  onChange={(e) => setIncludeNoP(e.target.checked)}
                />
                Include rows without parseable p-values
              </label>
              <label className="flex items-center gap-2 pt-5 text-xs text-gray-600">
                <input
                  type="checkbox"
                  checked={selfOnly}
                  onChange={(e) => setSelfOnly(e.target.checked)}
                />
                Self-interactions only
              </label>
            </div>
            {lineageOptions.length > 0 ? (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-gray-500">Lineage / group</span>
                <button
                  type="button"
                  onClick={() => setLineageFilter('')}
                  className={`rounded-full px-2.5 py-0.5 text-xs ${lineageFilter === '' ? 'bg-gray-800 text-white' : 'bg-gray-100 text-gray-700'}`}
                >
                  All
                </button>
                {lineageOptions.map((ln) => (
                  <button
                    key={ln}
                    type="button"
                    onClick={() => setLineageFilter((cur) => (cur === ln ? '' : ln))}
                    className={`rounded-full px-2.5 py-0.5 text-xs ${
                      lineageFilter === ln
                        ? 'bg-violet-600 text-white'
                        : 'bg-gray-100 text-gray-700'
                    }`}
                  >
                    {ln}
                  </button>
                ))}
              </div>
            ) : null}
            <p className="text-xs text-gray-400">
              {filteredRows.length.toLocaleString()} row-level interactions after filters
              {normalizedAll.length !== filteredRows.length
                ? ` (${normalizedAll.length.toLocaleString()} total parsed)`
                : ''}
            </p>
          </div>

          <div className="grid gap-4 lg:grid-cols-[1fr_min(22rem,100%)] lg:items-start">
            <div className="min-w-0 space-y-4">
              <LigandReceptorOverview
                rows={filteredRows}
                datasetSemantics={datasetSemantics}
                metric={pairMetricEffective}
                onMetricChange={setPairMetric}
                axisSort={axisSort}
                onAxisSortChange={setAxisSort}
                tab={overviewTab}
                onTabChange={setOverviewTab}
                selectedPair={effectiveHighlight}
                onSelectPair={onSelectPair}
              />
              <LigandReceptorRankedTable
                rows={filteredRows}
                datasetSemantics={datasetSemantics}
                selectedPair={effectiveHighlight}
                onSelectPair={(p) => setSelectedPair(p)}
                onExportCsv={exportFiltered}
              />
            </div>
            <div className="min-w-0 space-y-3">
              {pinnedHiddenByFilters ? (
                <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  Pinned pair is hidden by current filters. Adjust filters or unpin to see it again.
                </p>
              ) : null}
              <LigandReceptorDetailPanel
                pair={selectedPair}
                rows={filteredRows}
                pinned={pinnedPair}
                datasetSemantics={datasetSemantics}
                onClear={() => {
                  setSelectedPair(null);
                  setPinnedPair(null);
                }}
                onPin={() => {
                  if (selectedPair) setPinnedPair(selectedPair);
                }}
                onUnpin={() => setPinnedPair(null)}
              />
              {canExportPair ? (
                <button
                  type="button"
                  onClick={exportSelectedPair}
                  className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50"
                  data-testid="lr-export-pair-csv"
                >
                  Export selected pair CSV
                </button>
              ) : null}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
