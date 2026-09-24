'use client';

import { useState } from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface MarkerGene {
  gene: string;
  log_fold_change: number;
  p_value_adj: number;
}

export interface ClusterStat {
  cluster_id: string;
  cell_count: number;
  total_cells: number;
  top_marker_genes: MarkerGene[];
  pathway_scores: Record<string, number>;
}

export interface ClusterStatsProps {
  clusters: ClusterStat[];
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function pct(count: number, total: number): string {
  if (total === 0) return '0%';
  return `${((count / total) * 100).toFixed(1)}%`;
}

function fmtLfc(v: number): string {
  return v >= 0 ? `+${v.toFixed(2)}` : v.toFixed(2);
}

function fmtPval(v: number): string {
  if (v < 0.001) return '<0.001';
  return v.toFixed(3);
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function ClusterStats({
  clusters,
  isLoading = false,
  error = null,
  onRetry,
}: ClusterStatsProps) {
  const [selected, setSelected] = useState<string | null>(clusters[0]?.cluster_id ?? null);

  if (isLoading) {
    return (
      <div
        className="card p-6 flex items-center justify-center min-h-64"
        data-testid="cluster-stats-loading"
      >
        <div className="flex flex-col items-center gap-3 text-gray-500">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600" />
          <span className="text-sm">Loading cluster statistics…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="card p-6 flex items-center justify-center min-h-64"
        data-testid="cluster-stats-error"
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

  if (clusters.length === 0) {
    return (
      <div className="card p-6 text-center text-sm text-gray-500" data-testid="cluster-stats-empty">
        No cluster data available.
      </div>
    );
  }

  const totalCells = clusters[0]?.total_cells ?? clusters.reduce((s, c) => s + c.cell_count, 0);
  const active = clusters.find((c) => c.cluster_id === selected) ?? clusters[0];

  return (
    <div className="flex gap-4" data-testid="cluster-stats">
      {/* Cluster list + composition bar */}
      <div className="card p-4 w-64 shrink-0">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Clusters</h2>

        {/* Stacked composition bar */}
        <div
          className="flex h-4 rounded overflow-hidden mb-4"
          data-testid="composition-bar"
          title="Cluster composition"
        >
          {clusters.map((c, i) => (
            <div
              key={c.cluster_id}
              style={{
                width: pct(c.cell_count, totalCells),
                backgroundColor: `hsl(${(i * 47) % 360}, 65%, 55%)`,
              }}
              title={`${c.cluster_id}: ${pct(c.cell_count, totalCells)}`}
            />
          ))}
        </div>

        <ul className="space-y-1">
          {clusters.map((c) => (
            <li key={c.cluster_id}>
              <button
                onClick={() => setSelected(c.cluster_id)}
                data-testid={`cluster-btn-${c.cluster_id}`}
                className={`w-full text-left rounded-md px-3 py-2 text-sm transition-colors ${
                  selected === c.cluster_id
                    ? 'bg-blue-50 text-blue-700 font-medium'
                    : 'text-gray-700 hover:bg-gray-50'
                }`}
              >
                <span className="font-mono">{c.cluster_id}</span>
                <span className="ml-2 text-xs text-gray-400">
                  {c.cell_count.toLocaleString()} ({pct(c.cell_count, totalCells)})
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      {/* Detail panel */}
      <div className="flex-1 min-w-0 space-y-4">
        {/* Summary */}
        <div className="card p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-2">
            Cluster <span className="font-mono">{active.cluster_id}</span>
          </h2>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-1 text-sm">
            <div>
              <dt className="text-gray-500">Cells</dt>
              <dd className="text-gray-900 font-medium">{active.cell_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-gray-500">% of total</dt>
              <dd className="text-gray-900 font-medium">{pct(active.cell_count, totalCells)}</dd>
            </div>
          </dl>
        </div>

        {/* Top marker genes */}
        <div className="card p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Top marker genes</h2>
          {active.top_marker_genes.length === 0 ? (
            <p className="text-sm text-gray-400">No marker genes available.</p>
          ) : (
            <table className="w-full text-sm" data-testid="marker-genes-table">
              <thead>
                <tr className="text-xs text-gray-500 border-b border-gray-100">
                  <th className="text-left pb-2 font-medium">Gene</th>
                  <th className="text-right pb-2 font-medium">Log FC</th>
                  <th className="text-right pb-2 font-medium">Adj. p-value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {active.top_marker_genes.map((g) => (
                  <tr key={g.gene}>
                    <td className="py-1.5 font-mono text-gray-900">{g.gene}</td>
                    <td
                      className={`py-1.5 text-right font-mono ${
                        g.log_fold_change >= 0 ? 'text-green-700' : 'text-red-600'
                      }`}
                    >
                      {fmtLfc(g.log_fold_change)}
                    </td>
                    <td className="py-1.5 text-right text-gray-600">{fmtPval(g.p_value_adj)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pathway scores */}
        {Object.keys(active.pathway_scores).length > 0 && (
          <div className="card p-4">
            <h2 className="text-sm font-semibold text-gray-700 mb-3">Pathway scores</h2>
            <ul className="space-y-2" data-testid="pathway-scores-list">
              {Object.entries(active.pathway_scores)
                .sort(([, a], [, b]) => b - a)
                .map(([pathway, score]) => (
                  <li key={pathway} className="flex items-center gap-3">
                    <span className="text-sm text-gray-700 flex-1 truncate" title={pathway}>
                      {pathway}
                    </span>
                    <div className="w-32 bg-gray-100 rounded-full h-2 shrink-0">
                      <div
                        className="bg-blue-500 h-2 rounded-full"
                        style={{ width: `${Math.min(Math.abs(score) * 100, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs font-mono text-gray-500 w-12 text-right">
                      {score.toFixed(3)}
                    </span>
                  </li>
                ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
