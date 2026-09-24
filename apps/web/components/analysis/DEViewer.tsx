'use client';

import { useMemo, useState } from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface DEResult {
  gene: string;
  cluster: string;
  log_fold_change: number;
  p_value: number;
  p_value_adj: number;
}

export interface DEViewerProps {
  results: DEResult[];
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
}

type SortKey = 'gene' | 'cluster' | 'log_fold_change' | 'p_value' | 'p_value_adj';
type SortDir = 'asc' | 'desc';

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtNum(v: number, decimals = 3): string {
  if (Math.abs(v) < 0.001 && v !== 0) return v.toExponential(2);
  return v.toFixed(decimals);
}

function fmtLfc(v: number): string {
  return v >= 0 ? `+${v.toFixed(3)}` : v.toFixed(3);
}

// ── Volcano plot (canvas-based) ───────────────────────────────────────────────

interface VolcanoProps {
  results: DEResult[];
  pThreshold: number;
  lfcThreshold: number;
}

function VolcanoPlot({ results, pThreshold, lfcThreshold }: VolcanoProps) {
  if (results.length === 0) return null;

  const W = 400;
  const H = 280;
  const PAD = { top: 16, right: 16, bottom: 36, left: 48 };

  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const lfcValues = results.map((r) => r.log_fold_change);
  const negLogP = results.map((r) => -Math.log10(Math.max(r.p_value_adj, 1e-300)));

  const lfcMin = Math.min(...lfcValues);
  const lfcMax = Math.max(...lfcValues);
  const yMax = Math.max(...negLogP) * 1.05;

  const xScale = (v: number) => PAD.left + ((v - lfcMin) / (lfcMax - lfcMin || 1)) * plotW;
  const yScale = (v: number) => PAD.top + plotH - (v / (yMax || 1)) * plotH;

  const negLogThreshold = -Math.log10(pThreshold);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      data-testid="volcano-plot"
      aria-label="Volcano plot of differential expression results"
    >
      {/* Threshold lines */}
      <line
        x1={PAD.left}
        x2={W - PAD.right}
        y1={yScale(negLogThreshold)}
        y2={yScale(negLogThreshold)}
        stroke="#e5e7eb"
        strokeDasharray="4 2"
      />
      <line
        x1={xScale(-lfcThreshold)}
        x2={xScale(-lfcThreshold)}
        y1={PAD.top}
        y2={H - PAD.bottom}
        stroke="#e5e7eb"
        strokeDasharray="4 2"
      />
      <line
        x1={xScale(lfcThreshold)}
        x2={xScale(lfcThreshold)}
        y1={PAD.top}
        y2={H - PAD.bottom}
        stroke="#e5e7eb"
        strokeDasharray="4 2"
      />

      {/* Points */}
      {results.map((r, i) => {
        const sig = r.p_value_adj < pThreshold && Math.abs(r.log_fold_change) >= lfcThreshold;
        const up = r.log_fold_change >= 0;
        const fill = sig ? (up ? '#16a34a' : '#dc2626') : '#9ca3af';
        return (
          <circle
            key={i}
            cx={xScale(r.log_fold_change)}
            cy={yScale(-Math.log10(Math.max(r.p_value_adj, 1e-300)))}
            r={3}
            fill={fill}
            fillOpacity={0.7}
          >
            <title>{`${r.gene} (LFC: ${fmtLfc(r.log_fold_change)}, adj.p: ${fmtNum(r.p_value_adj)})`}</title>
          </circle>
        );
      })}

      {/* Axes */}
      <line
        x1={PAD.left}
        x2={W - PAD.right}
        y1={H - PAD.bottom}
        y2={H - PAD.bottom}
        stroke="#d1d5db"
      />
      <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={H - PAD.bottom} stroke="#d1d5db" />

      {/* Axis labels */}
      <text x={W / 2} y={H - 4} textAnchor="middle" fontSize={10} fill="#6b7280">
        Log fold change
      </text>
      <text
        x={12}
        y={PAD.top + plotH / 2}
        textAnchor="middle"
        fontSize={10}
        fill="#6b7280"
        transform={`rotate(-90, 12, ${PAD.top + plotH / 2})`}
      >
        -log10(adj. p)
      </text>
    </svg>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function DEViewer({
  results,
  isLoading = false,
  error = null,
  onRetry,
}: DEViewerProps) {
  const [sortKey, setSortKey] = useState<SortKey>('p_value_adj');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [pThreshold, setPThreshold] = useState(0.05);
  const [lfcThreshold, setLfcThreshold] = useState(1.0);
  const [clusterFilter, setClusterFilter] = useState('all');
  const [showVolcano, setShowVolcano] = useState(true);

  const clusters = useMemo(
    () => ['all', ...Array.from(new Set(results.map((r) => r.cluster))).sort()],
    [results]
  );

  const filtered = useMemo(() => {
    let rows = results;
    if (clusterFilter !== 'all') rows = rows.filter((r) => r.cluster === clusterFilter);
    return [...rows].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : av - (bv as number);
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [results, clusterFilter, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  }

  function SortIcon({ col }: { col: SortKey }) {
    if (sortKey !== col) return <span className="text-gray-300 ml-1">↕</span>;
    return <span className="text-blue-600 ml-1">{sortDir === 'asc' ? '↑' : '↓'}</span>;
  }

  if (isLoading) {
    return (
      <div
        className="card p-6 flex items-center justify-center min-h-64"
        data-testid="de-viewer-loading"
      >
        <div className="flex flex-col items-center gap-3 text-gray-500">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600" />
          <span className="text-sm">Loading DE results…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="card p-6 flex items-center justify-center min-h-64"
        data-testid="de-viewer-error"
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
    <div className="space-y-4" data-testid="de-viewer">
      {/* Controls */}
      <div className="card p-4 flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-600" htmlFor="cluster-filter">
            Cluster
          </label>
          <select
            id="cluster-filter"
            value={clusterFilter}
            onChange={(e) => setClusterFilter(e.target.value)}
            className="rounded-md border border-gray-300 bg-white px-2 py-1 text-sm text-gray-700"
            data-testid="cluster-filter"
          >
            {clusters.map((c) => (
              <option key={c} value={c}>
                {c === 'all' ? 'All clusters' : c}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-600" htmlFor="p-threshold">
            Adj. p ≤
          </label>
          <input
            id="p-threshold"
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={pThreshold}
            onChange={(e) => setPThreshold(Number(e.target.value))}
            className="w-20 rounded-md border border-gray-300 bg-white px-2 py-1 text-sm text-gray-700"
            data-testid="p-threshold-input"
          />
        </div>

        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-600" htmlFor="lfc-threshold">
            |LFC| ≥
          </label>
          <input
            id="lfc-threshold"
            type="number"
            min={0}
            step={0.1}
            value={lfcThreshold}
            onChange={(e) => setLfcThreshold(Number(e.target.value))}
            className="w-20 rounded-md border border-gray-300 bg-white px-2 py-1 text-sm text-gray-700"
            data-testid="lfc-threshold-input"
          />
        </div>

        <button
          onClick={() => setShowVolcano((v) => !v)}
          className="ml-auto rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          data-testid="toggle-volcano"
        >
          {showVolcano ? 'Hide' : 'Show'} volcano plot
        </button>
      </div>

      <div className={showVolcano ? 'flex gap-4' : ''}>
        {/* Volcano plot */}
        {showVolcano && (
          <div className="card p-4 w-96 shrink-0">
            <h2 className="text-sm font-semibold text-gray-700 mb-2">Volcano plot</h2>
            <VolcanoPlot results={filtered} pThreshold={pThreshold} lfcThreshold={lfcThreshold} />
            <div className="flex gap-4 mt-2 text-xs text-gray-500">
              <span className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-green-600" /> Up-regulated
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-red-600" /> Down-regulated
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-gray-400" /> Not significant
              </span>
            </div>
          </div>
        )}

        {/* Table */}
        <div className="card p-4 flex-1 min-w-0 overflow-x-auto">
          <p className="text-xs text-gray-500 mb-2">{filtered.length.toLocaleString()} genes</p>
          <table className="w-full text-sm" data-testid="de-results-table">
            <thead>
              <tr className="text-xs text-gray-500 border-b border-gray-100">
                {(
                  [
                    ['gene', 'Gene'],
                    ['cluster', 'Cluster'],
                    ['log_fold_change', 'Log FC'],
                    ['p_value', 'p-value'],
                    ['p_value_adj', 'Adj. p-value'],
                  ] as [SortKey, string][]
                ).map(([key, label]) => (
                  <th
                    key={key}
                    className="text-left pb-2 font-medium cursor-pointer select-none hover:text-gray-700"
                    onClick={() => toggleSort(key)}
                  >
                    {label}
                    <SortIcon col={key} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {filtered.slice(0, 200).map((r, i) => {
                const sig =
                  r.p_value_adj < pThreshold && Math.abs(r.log_fold_change) >= lfcThreshold;
                return (
                  <tr key={i} className={sig ? 'bg-blue-50/30' : ''}>
                    <td className="py-1.5 font-mono text-gray-900">{r.gene}</td>
                    <td className="py-1.5 text-gray-600">{r.cluster}</td>
                    <td
                      className={`py-1.5 font-mono ${r.log_fold_change >= 0 ? 'text-green-700' : 'text-red-600'}`}
                    >
                      {fmtLfc(r.log_fold_change)}
                    </td>
                    <td className="py-1.5 text-gray-600">{fmtNum(r.p_value)}</td>
                    <td
                      className={`py-1.5 font-mono ${sig ? 'font-semibold text-blue-700' : 'text-gray-600'}`}
                    >
                      {fmtNum(r.p_value_adj)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {filtered.length > 200 && (
            <p className="text-xs text-gray-400 mt-2">
              Showing first 200 of {filtered.length.toLocaleString()} results.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
