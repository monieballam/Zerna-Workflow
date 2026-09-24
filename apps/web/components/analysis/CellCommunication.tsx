'use client';

import { useState, useMemo } from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface LRInteraction {
  ligand: string;
  receptor: string;
  sourceCellType: string;
  targetCellType: string;
  interactionScore: number;
  pValue: number;
  pathwayAnnotations: string[];
}

export interface CellCommunicationProps {
  interactions: LRInteraction[];
  cellTypes: string[];
  datasetName?: string;
}

// ── Interaction Row ───────────────────────────────────────────────────────────

function InteractionRow({ interaction }: { interaction: LRInteraction }) {
  const significanceClass =
    interaction.pValue < 0.001
      ? 'text-green-700 bg-green-50'
      : interaction.pValue < 0.05
        ? 'text-yellow-700 bg-yellow-50'
        : 'text-gray-500 bg-gray-50';

  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50">
      <td className="px-3 py-2 text-sm font-mono text-gray-800">{interaction.ligand}</td>
      <td className="px-3 py-2 text-sm font-mono text-gray-800">{interaction.receptor}</td>
      <td className="px-3 py-2 text-sm text-gray-600">{interaction.sourceCellType}</td>
      <td className="px-3 py-2 text-sm text-gray-600">{interaction.targetCellType}</td>
      <td className="px-3 py-2 text-sm text-gray-700 font-medium">
        {interaction.interactionScore.toFixed(3)}
      </td>
      <td className="px-3 py-2">
        <span
          className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${significanceClass}`}
        >
          {interaction.pValue < 0.001
            ? interaction.pValue.toExponential(2)
            : interaction.pValue.toFixed(4)}
        </span>
      </td>
      <td className="px-3 py-2 text-xs text-gray-500">
        {interaction.pathwayAnnotations.length > 0
          ? interaction.pathwayAnnotations.join(', ')
          : '—'}
      </td>
    </tr>
  );
}

// ── Summary Stats ─────────────────────────────────────────────────────────────

function CommunicationSummary({
  interactions,
  cellTypes,
}: {
  interactions: LRInteraction[];
  cellTypes: string[];
}) {
  const significantCount = interactions.filter((i) => i.pValue < 0.05).length;

  return (
    <div className="grid grid-cols-3 gap-4 mb-4" data-testid="communication-summary">
      <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
        <p className="text-2xl font-bold text-gray-900">{interactions.length}</p>
        <p className="text-xs text-gray-500">LR pairs</p>
      </div>
      <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
        <p className="text-2xl font-bold text-gray-900">{significantCount}</p>
        <p className="text-xs text-gray-500">Significant (p&lt;0.05)</p>
      </div>
      <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
        <p className="text-2xl font-bold text-gray-900">{cellTypes.length}</p>
        <p className="text-xs text-gray-500">Cell types</p>
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function CellCommunication({
  interactions,
  cellTypes,
  datasetName,
}: CellCommunicationProps) {
  const [search, setSearch] = useState('');
  const [sourceCellFilter, setSourceCellFilter] = useState<string>('all');
  const [targetCellFilter, setTargetCellFilter] = useState<string>('all');
  const [sortBy, setSortBy] = useState<'score' | 'pvalue'>('score');

  const filtered = useMemo(() => {
    let result = interactions;
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (i) =>
          i.ligand.toLowerCase().includes(q) ||
          i.receptor.toLowerCase().includes(q) ||
          i.pathwayAnnotations.some((p) => p.toLowerCase().includes(q))
      );
    }
    if (sourceCellFilter !== 'all') {
      result = result.filter((i) => i.sourceCellType === sourceCellFilter);
    }
    if (targetCellFilter !== 'all') {
      result = result.filter((i) => i.targetCellType === targetCellFilter);
    }
    return [...result].sort((a, b) =>
      sortBy === 'score' ? b.interactionScore - a.interactionScore : a.pValue - b.pValue
    );
  }, [interactions, search, sourceCellFilter, targetCellFilter, sortBy]);

  return (
    <div className="space-y-4" data-testid="cell-communication">
      {datasetName && (
        <h2 className="text-lg font-semibold text-gray-900">{datasetName} — Cell Communication</h2>
      )}

      <CommunicationSummary interactions={interactions} cellTypes={cellTypes} />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="text"
          placeholder="Search ligand, receptor, pathway…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm flex-1 min-w-[200px]"
          aria-label="Search interactions"
        />
        <select
          value={sourceCellFilter}
          onChange={(e) => setSourceCellFilter(e.target.value)}
          className="rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          aria-label="Filter by source cell type"
        >
          <option value="all">All sources</option>
          {cellTypes.map((ct) => (
            <option key={ct} value={ct}>
              {ct}
            </option>
          ))}
        </select>
        <select
          value={targetCellFilter}
          onChange={(e) => setTargetCellFilter(e.target.value)}
          className="rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          aria-label="Filter by target cell type"
        >
          <option value="all">All targets</option>
          {cellTypes.map((ct) => (
            <option key={ct} value={ct}>
              {ct}
            </option>
          ))}
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as 'score' | 'pvalue')}
          className="rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          aria-label="Sort by"
        >
          <option value="score">Score ↓</option>
          <option value="pvalue">p-value ↑</option>
        </select>
      </div>

      {/* Table */}
      {filtered.length === 0 ? (
        <p className="text-sm text-gray-400 text-center py-8">No interactions found</p>
      ) : (
        <div className="overflow-x-auto border border-gray-200 rounded-lg">
          <table className="min-w-full divide-y divide-gray-200" data-testid="interaction-table">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                  Ligand
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                  Receptor
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                  Source
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                  Target
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                  Score
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                  p-value
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                  Pathways
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((interaction, idx) => (
                <InteractionRow
                  key={`${interaction.ligand}-${interaction.receptor}-${idx}`}
                  interaction={interaction}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
