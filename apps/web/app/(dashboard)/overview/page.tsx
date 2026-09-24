'use client';

import { useState, useEffect } from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

interface DatasetStats {
  totalDatasets: number;
  totalCells: number;
  totalGenes: number;
  formats: Record<string, number>;
}

interface RunStatusSummary {
  total: number;
  completed: number;
  running: number;
  failed: number;
  queued: number;
}

interface QualityMetrics {
  avgDoubletRate: number;
  avgMitoPercent: number;
  avgGenesPerCell: number;
  avgCellsPerDataset: number;
}

interface OverviewData {
  datasets: DatasetStats;
  runs: RunStatusSummary;
  quality: QualityMetrics;
}

// ── Stat Card ─────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  subtitle,
  colorClass = 'text-gray-900',
}: {
  label: string;
  value: string | number;
  subtitle?: string;
  colorClass?: string;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4" data-testid={`stat-${label}`}>
      <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-2xl font-bold ${colorClass}`}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>
      {subtitle && <p className="text-xs text-gray-400 mt-1">{subtitle}</p>}
    </div>
  );
}

// ── Run Status Bar ────────────────────────────────────────────────────────────

function RunStatusBar({ runs }: { runs: RunStatusSummary }) {
  const total = runs.total || 1;
  const segments = [
    { key: 'completed', count: runs.completed, color: 'bg-green-500', label: 'Completed' },
    { key: 'running', count: runs.running, color: 'bg-blue-500', label: 'Running' },
    { key: 'queued', count: runs.queued, color: 'bg-yellow-400', label: 'Queued' },
    { key: 'failed', count: runs.failed, color: 'bg-red-500', label: 'Failed' },
  ];

  return (
    <div data-testid="run-status-bar">
      <div className="flex h-4 rounded-full overflow-hidden bg-gray-100 mb-2">
        {segments.map((seg) =>
          seg.count > 0 ? (
            <div
              key={seg.key}
              className={`${seg.color} transition-all`}
              style={{ width: `${(seg.count / total) * 100}%` }}
              title={`${seg.label}: ${seg.count}`}
            />
          ) : null
        )}
      </div>
      <div className="flex gap-4 text-xs text-gray-500">
        {segments.map((seg) => (
          <div key={seg.key} className="flex items-center gap-1">
            <span className={`inline-block w-2 h-2 rounded-full ${seg.color}`} />
            <span>
              {seg.label}: {seg.count}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Format Distribution ───────────────────────────────────────────────────────

function FormatDistribution({ formats }: { formats: Record<string, number> }) {
  const entries = Object.entries(formats).sort(([, a], [, b]) => b - a);
  const total = entries.reduce((sum, [, v]) => sum + v, 0) || 1;

  return (
    <div data-testid="format-distribution">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Dataset formats
      </h3>
      <div className="space-y-1.5">
        {entries.map(([fmt, count]) => (
          <div key={fmt} className="flex items-center gap-2">
            <span className="text-xs font-mono text-gray-600 w-12">{fmt}</span>
            <div className="flex-1 h-3 bg-gray-100 rounded overflow-hidden">
              <div
                className="h-full bg-indigo-400 rounded"
                style={{ width: `${(count / total) * 100}%` }}
              />
            </div>
            <span className="text-xs text-gray-400 w-8 text-right">{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Quality Metrics Panel ─────────────────────────────────────────────────────

function QualityPanel({ quality }: { quality: QualityMetrics }) {
  const metrics = [
    { label: 'Avg doublet rate', value: `${(quality.avgDoubletRate * 100).toFixed(1)}%` },
    { label: 'Avg mito %', value: `${quality.avgMitoPercent.toFixed(1)}%` },
    { label: 'Avg genes/cell', value: quality.avgGenesPerCell.toLocaleString() },
    { label: 'Avg cells/dataset', value: quality.avgCellsPerDataset.toLocaleString() },
  ];

  return (
    <div data-testid="quality-panel">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Quality metrics
      </h3>
      <dl className="grid grid-cols-2 gap-3">
        {metrics.map((m) => (
          <div key={m.label} className="bg-gray-50 rounded-lg p-3">
            <dt className="text-xs text-gray-500">{m.label}</dt>
            <dd className="text-sm font-semibold text-gray-900 mt-0.5">{m.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const PLACEHOLDER_DATA: OverviewData = {
  datasets: { totalDatasets: 0, totalCells: 0, totalGenes: 0, formats: {} },
  runs: { total: 0, completed: 0, running: 0, failed: 0, queued: 0 },
  quality: { avgDoubletRate: 0, avgMitoPercent: 0, avgGenesPerCell: 0, avgCellsPerDataset: 0 },
};

export default function OverviewPage() {
  const [data, setData] = useState<OverviewData>(PLACEHOLDER_DATA);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchOverview() {
      try {
        const res = await fetch('/api/proxy/overview');
        if (!res.ok) throw new Error(`Failed to load overview: ${res.status}`);
        const rawData: unknown = await res.json();
        const json = rawData as OverviewData;
        if (!cancelled) setData(json);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void fetchOverview();
    return () => {
      cancelled = true;
    };
  }, []);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-64" data-testid="overview-loading">
        <div className="flex flex-col items-center gap-3 text-gray-500">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600" />
          <span className="text-sm">Loading overview…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-64" data-testid="overview-error">
        <p className="text-sm text-red-600">{error}</p>
      </div>
    );
  }

  const { datasets, runs, quality } = data;

  return (
    <div className="space-y-6" data-testid="overview-dashboard">
      <h1 className="text-xl font-bold text-gray-900">Overview</h1>

      {/* Top-level stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Datasets" value={datasets.totalDatasets} />
        <StatCard label="Total cells" value={datasets.totalCells} />
        <StatCard label="Total genes" value={datasets.totalGenes} />
        <StatCard label="Pipeline runs" value={runs.total} />
      </div>

      {/* Run status */}
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Run status</h2>
        <RunStatusBar runs={runs} />
      </div>

      {/* Bottom panels */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <FormatDistribution formats={datasets.formats} />
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <QualityPanel quality={quality} />
        </div>
      </div>
    </div>
  );
}
