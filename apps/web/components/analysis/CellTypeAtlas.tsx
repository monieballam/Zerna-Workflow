'use client';

import { useState, useMemo } from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface MarkerGene {
  gene: string;
  score: number;
  pValue: number;
  logFoldChange: number;
}

export interface CellTypeEntry {
  cellType: string;
  count: number;
  proportion: number;
  confidence: number;
  markers: MarkerGene[];
  expressionProfile?: Record<string, number>; // gene -> mean expression
}

export interface CellTypeAtlasProps {
  cellTypes: CellTypeEntry[];
  totalCells: number;
  datasetName?: string;
}

// ── Confidence Badge ──────────────────────────────────────────────────────────

function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  let colorClass = 'bg-green-100 text-green-700';
  if (value < 0.5) colorClass = 'bg-red-100 text-red-700';
  else if (value < 0.75) colorClass = 'bg-yellow-100 text-yellow-700';

  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${colorClass}`}
      data-testid="confidence-badge"
    >
      {pct}%
    </span>
  );
}

// ── Marker Table ──────────────────────────────────────────────────────────────

function MarkerTable({ markers }: { markers: MarkerGene[] }) {
  if (markers.length === 0) {
    return <p className="text-xs text-gray-400 italic">No markers available</p>;
  }

  return (
    <table className="w-full text-xs" data-testid="marker-table">
      <thead>
        <tr className="text-left text-gray-500 border-b border-gray-200">
          <th className="py-1 pr-3 font-medium">Gene</th>
          <th className="py-1 pr-3 font-medium">Score</th>
          <th className="py-1 pr-3 font-medium">log₂FC</th>
          <th className="py-1 font-medium">p-value</th>
        </tr>
      </thead>
      <tbody>
        {markers.map((m) => (
          <tr key={m.gene} className="border-b border-gray-100">
            <td className="py-1 pr-3 font-mono font-medium text-gray-800">{m.gene}</td>
            <td className="py-1 pr-3 text-gray-600">{m.score.toFixed(3)}</td>
            <td className="py-1 pr-3 text-gray-600">{m.logFoldChange.toFixed(2)}</td>
            <td className="py-1 text-gray-600">
              {m.pValue < 0.001 ? m.pValue.toExponential(2) : m.pValue.toFixed(4)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Expression Bar Plot ───────────────────────────────────────────────────────

function ExpressionPlot({ profile }: { profile: Record<string, number> }) {
  const entries = Object.entries(profile)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 10);
  const maxVal = Math.max(...entries.map(([, v]) => v), 1);

  return (
    <div className="space-y-1" data-testid="expression-plot">
      <h4 className="text-xs font-medium text-gray-500">Top expressed genes</h4>
      {entries.map(([gene, value]) => (
        <div key={gene} className="flex items-center gap-2">
          <span className="text-xs font-mono text-gray-600 w-16 truncate">{gene}</span>
          <div className="flex-1 h-3 bg-gray-100 rounded overflow-hidden">
            <div
              className="h-full bg-indigo-400 rounded"
              style={{ width: `${(value / maxVal) * 100}%` }}
            />
          </div>
          <span className="text-xs text-gray-400 w-10 text-right">{value.toFixed(1)}</span>
        </div>
      ))}
    </div>
  );
}

// ── Cell Type Card ────────────────────────────────────────────────────────────

function CellTypeCard({
  entry,
  isExpanded,
  onToggle,
}: {
  entry: CellTypeEntry;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className="border border-gray-200 rounded-lg"
      data-testid={`celltype-card-${entry.cellType}`}
    >
      <button
        onClick={onToggle}
        className="w-full text-left px-4 py-3 flex items-center gap-3 hover:bg-gray-50"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-900">{entry.cellType}</h3>
            <ConfidenceBadge value={entry.confidence} />
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            {entry.count.toLocaleString()} cells ({(entry.proportion * 100).toFixed(1)}%)
          </p>
        </div>
        <span className="text-gray-400 text-sm">{isExpanded ? '▲' : '▼'}</span>
      </button>

      {isExpanded && (
        <div className="px-4 pb-4 space-y-4 border-t border-gray-100">
          <div className="pt-3">
            <h4 className="text-xs font-medium text-gray-500 mb-2">Marker genes</h4>
            <MarkerTable markers={entry.markers} />
          </div>
          {entry.expressionProfile && Object.keys(entry.expressionProfile).length > 0 && (
            <ExpressionPlot profile={entry.expressionProfile} />
          )}
        </div>
      )}
    </div>
  );
}

// ── Summary Stats ─────────────────────────────────────────────────────────────

function AtlasSummary({
  cellTypes,
  totalCells,
}: {
  cellTypes: CellTypeEntry[];
  totalCells: number;
}) {
  const avgConfidence =
    cellTypes.length > 0
      ? cellTypes.reduce((sum, ct) => sum + ct.confidence, 0) / cellTypes.length
      : 0;

  return (
    <div className="grid grid-cols-3 gap-4 mb-4" data-testid="atlas-summary">
      <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
        <p className="text-2xl font-bold text-gray-900">{totalCells.toLocaleString()}</p>
        <p className="text-xs text-gray-500">Total cells</p>
      </div>
      <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
        <p className="text-2xl font-bold text-gray-900">{cellTypes.length}</p>
        <p className="text-xs text-gray-500">Cell types</p>
      </div>
      <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
        <p className="text-2xl font-bold text-gray-900">{(avgConfidence * 100).toFixed(0)}%</p>
        <p className="text-xs text-gray-500">Avg confidence</p>
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function CellTypeAtlas({ cellTypes, totalCells, datasetName }: CellTypeAtlasProps) {
  const [expandedType, setExpandedType] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<'count' | 'confidence' | 'name'>('count');
  const [search, setSearch] = useState('');

  const sorted = useMemo(() => {
    let filtered = cellTypes;
    if (search) {
      const q = search.toLowerCase();
      filtered = cellTypes.filter((ct) => ct.cellType.toLowerCase().includes(q));
    }
    return [...filtered].sort((a, b) => {
      if (sortBy === 'count') return b.count - a.count;
      if (sortBy === 'confidence') return b.confidence - a.confidence;
      return a.cellType.localeCompare(b.cellType);
    });
  }, [cellTypes, sortBy, search]);

  return (
    <div className="space-y-4" data-testid="cell-type-atlas">
      {datasetName && (
        <h2 className="text-lg font-semibold text-gray-900">{datasetName} — Cell Type Atlas</h2>
      )}

      <AtlasSummary cellTypes={cellTypes} totalCells={totalCells} />

      {/* Controls */}
      <div className="flex items-center gap-3">
        <input
          type="text"
          placeholder="Search cell types…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm flex-1"
        />
        <div className="flex items-center gap-1.5">
          <label htmlFor="atlas-sort" className="text-xs text-gray-500">
            Sort by
          </label>
          <select
            id="atlas-sort"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          >
            <option value="count">Cell count</option>
            <option value="confidence">Confidence</option>
            <option value="name">Name</option>
          </select>
        </div>
      </div>

      {/* Cell type list */}
      <div className="space-y-2">
        {sorted.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-8">No cell types found</p>
        ) : (
          sorted.map((entry) => (
            <CellTypeCard
              key={entry.cellType}
              entry={entry}
              isExpanded={expandedType === entry.cellType}
              onToggle={() =>
                setExpandedType(expandedType === entry.cellType ? null : entry.cellType)
              }
            />
          ))
        )}
      </div>
    </div>
  );
}
