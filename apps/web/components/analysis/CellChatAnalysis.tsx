'use client';

import { useState, useMemo } from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface CellChatEdge {
  source: string;
  target: string;
  pathway: string;
  probability: number;
  pValue: number;
}

export interface PathwayEnrichment {
  pathway: string;
  enrichmentScore: number;
  pValue: number;
  involvedCellTypes: string[];
}

export interface CellChatAnalysisProps {
  edges: CellChatEdge[];
  enrichments: PathwayEnrichment[];
  cellTypes: string[];
  datasetName?: string;
}

// ── Network Summary ───────────────────────────────────────────────────────────

function NetworkSummary({
  edges,
  enrichments,
  cellTypes,
}: {
  edges: CellChatEdge[];
  enrichments: PathwayEnrichment[];
  cellTypes: string[];
}) {
  const significantEdges = edges.filter((e) => e.pValue < 0.05).length;
  const significantPathways = enrichments.filter((e) => e.pValue < 0.05).length;

  return (
    <div className="grid grid-cols-4 gap-4 mb-4" data-testid="cellchat-summary">
      <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
        <p className="text-2xl font-bold text-gray-900">{cellTypes.length}</p>
        <p className="text-xs text-gray-500">Cell types</p>
      </div>
      <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
        <p className="text-2xl font-bold text-gray-900">{edges.length}</p>
        <p className="text-xs text-gray-500">Network edges</p>
      </div>
      <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
        <p className="text-2xl font-bold text-gray-900">{significantEdges}</p>
        <p className="text-xs text-gray-500">Significant edges</p>
      </div>
      <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
        <p className="text-2xl font-bold text-gray-900">{significantPathways}</p>
        <p className="text-xs text-gray-500">Enriched pathways</p>
      </div>
    </div>
  );
}

// ── Edge Table ────────────────────────────────────────────────────────────────

function EdgeTable({ edges }: { edges: CellChatEdge[] }) {
  if (edges.length === 0) {
    return <p className="text-sm text-gray-400 text-center py-4">No edges to display</p>;
  }

  return (
    <div className="overflow-x-auto border border-gray-200 rounded-lg">
      <table className="min-w-full divide-y divide-gray-200" data-testid="edge-table">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
              Source
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
              Target
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
              Pathway
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
              Probability
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
              p-value
            </th>
          </tr>
        </thead>
        <tbody>
          {edges.map((edge, idx) => (
            <tr
              key={`${edge.source}-${edge.target}-${edge.pathway}-${idx}`}
              className="border-b border-gray-100 hover:bg-gray-50"
            >
              <td className="px-3 py-2 text-sm text-gray-700">{edge.source}</td>
              <td className="px-3 py-2 text-sm text-gray-700">{edge.target}</td>
              <td className="px-3 py-2 text-sm font-medium text-gray-800">{edge.pathway}</td>
              <td className="px-3 py-2 text-sm text-gray-600">{edge.probability.toFixed(4)}</td>
              <td className="px-3 py-2 text-sm text-gray-600">
                {edge.pValue < 0.001 ? edge.pValue.toExponential(2) : edge.pValue.toFixed(4)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Pathway Enrichment Table ──────────────────────────────────────────────────

function EnrichmentTable({ enrichments }: { enrichments: PathwayEnrichment[] }) {
  if (enrichments.length === 0) {
    return <p className="text-sm text-gray-400 text-center py-4">No enrichments to display</p>;
  }

  return (
    <div className="overflow-x-auto border border-gray-200 rounded-lg">
      <table className="min-w-full divide-y divide-gray-200" data-testid="enrichment-table">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
              Pathway
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
              Score
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
              p-value
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
              Cell types
            </th>
          </tr>
        </thead>
        <tbody>
          {enrichments.map((e) => (
            <tr key={e.pathway} className="border-b border-gray-100 hover:bg-gray-50">
              <td className="px-3 py-2 text-sm font-medium text-gray-800">{e.pathway}</td>
              <td className="px-3 py-2 text-sm text-gray-600">{e.enrichmentScore.toFixed(3)}</td>
              <td className="px-3 py-2 text-sm text-gray-600">
                {e.pValue < 0.001 ? e.pValue.toExponential(2) : e.pValue.toFixed(4)}
              </td>
              <td className="px-3 py-2 text-xs text-gray-500">{e.involvedCellTypes.join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function CellChatAnalysis({
  edges,
  enrichments,
  cellTypes,
  datasetName,
}: CellChatAnalysisProps) {
  const [activeTab, setActiveTab] = useState<'network' | 'enrichment'>('network');
  const [pathwayFilter, setPathwayFilter] = useState<string>('all');

  const pathways = useMemo(() => [...new Set(edges.map((e) => e.pathway))].sort(), [edges]);

  const filteredEdges = useMemo(() => {
    if (pathwayFilter === 'all') return edges;
    return edges.filter((e) => e.pathway === pathwayFilter);
  }, [edges, pathwayFilter]);

  return (
    <div className="space-y-4" data-testid="cellchat-analysis">
      {datasetName && (
        <h2 className="text-lg font-semibold text-gray-900">{datasetName} — CellChat Analysis</h2>
      )}

      <NetworkSummary edges={edges} enrichments={enrichments} cellTypes={cellTypes} />

      {/* Tab bar */}
      <div className="flex border-b border-gray-200">
        <button
          onClick={() => setActiveTab('network')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'network'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Network Edges
        </button>
        <button
          onClick={() => setActiveTab('enrichment')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'enrichment'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Pathway Enrichments
        </button>
      </div>

      {activeTab === 'network' && (
        <div className="space-y-3">
          <select
            value={pathwayFilter}
            onChange={(e) => setPathwayFilter(e.target.value)}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm"
            aria-label="Filter by pathway"
          >
            <option value="all">All pathways</option>
            {pathways.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <EdgeTable edges={filteredEdges} />
        </div>
      )}

      {activeTab === 'enrichment' && <EnrichmentTable enrichments={enrichments} />}
    </div>
  );
}
