'use client';

import { useState } from 'react';
import type {
  CrossDatasetPathwayResponse,
  InterpretPathwayResponse,
  PathwayPattern,
} from '@zerna/sdk';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface PathwayCellScore {
  cell_id: string;
  pathway: string;
  score: number;
}

export interface PathwayViewerProps {
  /** Per-cell pathway scores from the run artifact */
  cellScores?: PathwayCellScore[];
  /** Cross-dataset analysis result */
  crossDatasetAnalysis?: CrossDatasetPathwayResponse | null;
  /** LLM interpretation result */
  interpretation?: InterpretPathwayResponse | null;
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onRequestInterpretation?: () => void;
  isInterpreting?: boolean;
}

type Tab = 'enrichment' | 'cross-dataset' | 'interpretation';

// ── Helpers ───────────────────────────────────────────────────────────────────

function confidenceBadge(confidence: number) {
  const pct = (confidence * 100).toFixed(0);
  const color =
    confidence >= 0.8
      ? 'bg-green-100 text-green-700'
      : confidence >= 0.5
        ? 'bg-yellow-100 text-yellow-700'
        : 'bg-gray-100 text-gray-600';
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {pct}%
    </span>
  );
}

// ── Enrichment table ──────────────────────────────────────────────────────────

function EnrichmentTable({ patterns }: { patterns: PathwayPattern[] }) {
  if (patterns.length === 0) {
    return <p className="text-sm text-gray-400">No pathway enrichment data available.</p>;
  }

  const sorted = [...patterns].sort((a, b) => b.aggregated_score - a.aggregated_score);

  return (
    <table className="w-full text-sm" data-testid="pathway-enrichment-table">
      <thead>
        <tr className="text-xs text-gray-500 border-b border-gray-100">
          <th className="text-left pb-2 font-medium">Pathway</th>
          <th className="text-right pb-2 font-medium">Score</th>
          <th className="text-right pb-2 font-medium">p-value</th>
          <th className="text-right pb-2 font-medium">Confidence</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-50">
        {sorted.map((p) => (
          <tr key={p.pathway_id}>
            <td className="py-2">
              <span className="text-gray-900 font-medium">{p.pathway_name}</span>
              <span className="ml-2 text-xs text-gray-400 font-mono">{p.pathway_id}</span>
            </td>
            <td className="py-2 text-right">
              <div className="flex items-center justify-end gap-2">
                <div className="w-20 bg-gray-100 rounded-full h-1.5">
                  <div
                    className="bg-blue-500 h-1.5 rounded-full"
                    style={{ width: `${Math.min(Math.abs(p.aggregated_score) * 100, 100)}%` }}
                  />
                </div>
                <span className="font-mono text-gray-700 w-12 text-right">
                  {p.aggregated_score.toFixed(3)}
                </span>
              </div>
            </td>
            <td className="py-2 text-right font-mono text-gray-600">
              {p.p_value < 0.001 ? '<0.001' : p.p_value.toFixed(3)}
            </td>
            <td className="py-2 text-right">{confidenceBadge(p.confidence)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Cross-dataset panel ───────────────────────────────────────────────────────

function CrossDatasetPanel({
  analysis,
  onRequestInterpretation,
  isInterpreting,
}: {
  analysis: CrossDatasetPathwayResponse;
  onRequestInterpretation?: () => void;
  isInterpreting?: boolean;
}) {
  return (
    <div className="space-y-4" data-testid="cross-dataset-panel">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-gray-600">
            <span className="font-medium">{analysis.dataset_ids.length}</span> datasets ·{' '}
            <span className="font-medium">{analysis.pathway_database}</span> ·{' '}
            <span
              className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                analysis.status === 'completed'
                  ? 'bg-green-100 text-green-700'
                  : analysis.status === 'running'
                    ? 'bg-blue-100 text-blue-700'
                    : 'bg-gray-100 text-gray-600'
              }`}
            >
              {analysis.status}
            </span>
          </p>
        </div>
        {analysis.status === 'completed' && onRequestInterpretation && (
          <button
            onClick={onRequestInterpretation}
            disabled={isInterpreting}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            data-testid="interpret-btn"
          >
            {isInterpreting ? 'Interpreting…' : 'Interpret with LLM'}
          </button>
        )}
      </div>

      {analysis.pathway_patterns && analysis.pathway_patterns.length > 0 ? (
        <EnrichmentTable patterns={analysis.pathway_patterns} />
      ) : (
        <p className="text-sm text-gray-400">
          {analysis.status === 'running' ? 'Analysis in progress…' : 'No patterns found.'}
        </p>
      )}
    </div>
  );
}

// ── Interpretation panel ──────────────────────────────────────────────────────

function InterpretationPanel({ interp }: { interp: InterpretPathwayResponse }) {
  return (
    <div className="space-y-4" data-testid="interpretation-panel">
      <div className="flex items-center gap-2 text-xs text-gray-500">
        <span>
          Model: <span className="font-mono">{interp.model_used}</span>
        </span>
        {interp.from_cache && <span className="rounded-full bg-gray-100 px-2 py-0.5">cached</span>}
      </div>

      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-2">Interpretation</h3>
        <p className="text-sm text-gray-700 leading-relaxed">{interp.interpretation}</p>
      </div>

      {interp.hypotheses.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Hypotheses</h3>
          <ul className="space-y-1.5" data-testid="hypotheses-list">
            {interp.hypotheses.map((h, i) => (
              <li key={i} className="flex gap-2 text-sm text-gray-700">
                <span className="text-blue-500 font-bold shrink-0">{i + 1}.</span>
                <span>{h}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {interp.suggested_experiments.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Suggested experiments</h3>
          <ul className="space-y-1.5" data-testid="experiments-list">
            {interp.suggested_experiments.map((e, i) => (
              <li key={i} className="flex gap-2 text-sm text-gray-700">
                <span className="text-gray-400 shrink-0">→</span>
                <span>{e}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function PathwayViewer({
  cellScores = [],
  crossDatasetAnalysis,
  interpretation,
  isLoading = false,
  error = null,
  onRetry,
  onRequestInterpretation,
  isInterpreting = false,
}: PathwayViewerProps) {
  const [tab, setTab] = useState<Tab>('enrichment');

  const pathways = Array.from(new Set(cellScores.map((s) => s.pathway))).sort();
  const [selectedPathway, setSelectedPathway] = useState<string>(pathways[0] ?? '');

  if (isLoading) {
    return (
      <div
        className="card p-6 flex items-center justify-center min-h-64"
        data-testid="pathway-viewer-loading"
      >
        <div className="flex flex-col items-center gap-3 text-gray-500">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600" />
          <span className="text-sm">Loading pathway data…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="card p-6 flex items-center justify-center min-h-64"
        data-testid="pathway-viewer-error"
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

  const tabs: { id: Tab; label: string; show: boolean }[] = [
    { id: 'enrichment', label: 'Enrichment', show: true },
    { id: 'cross-dataset', label: 'Cross-dataset', show: !!crossDatasetAnalysis },
    { id: 'interpretation', label: 'LLM interpretation', show: !!interpretation },
  ];

  return (
    <div className="space-y-4" data-testid="pathway-viewer">
      {/* Tab bar */}
      <div className="flex gap-1 border-b border-gray-200">
        {tabs
          .filter((t) => t.show)
          .map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              data-testid={`tab-${t.id}`}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                tab === t.id
                  ? 'border-blue-600 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {t.label}
            </button>
          ))}
      </div>

      {/* Enrichment tab */}
      {tab === 'enrichment' && (
        <div className="card p-4">
          {pathways.length > 0 ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <label className="text-sm text-gray-600" htmlFor="pathway-select">
                  Pathway
                </label>
                <select
                  id="pathway-select"
                  value={selectedPathway}
                  onChange={(e) => setSelectedPathway(e.target.value)}
                  className="rounded-md border border-gray-300 bg-white px-2 py-1 text-sm text-gray-700"
                  data-testid="pathway-select"
                >
                  {pathways.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </div>
              <p className="text-xs text-gray-500">
                Showing per-cell scores for{' '}
                <span className="font-mono font-medium">{selectedPathway}</span>. Use the embedding
                viewer to color cells by pathway score.
              </p>
              <div className="text-sm text-gray-600">
                {cellScores.filter((s) => s.pathway === selectedPathway).length.toLocaleString()}{' '}
                cells scored
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-400">
              No per-cell pathway scores available for this run.
            </p>
          )}
        </div>
      )}

      {/* Cross-dataset tab */}
      {tab === 'cross-dataset' && crossDatasetAnalysis && (
        <div className="card p-4">
          <CrossDatasetPanel
            analysis={crossDatasetAnalysis}
            onRequestInterpretation={onRequestInterpretation}
            isInterpreting={isInterpreting}
          />
        </div>
      )}

      {/* Interpretation tab */}
      {tab === 'interpretation' && interpretation && (
        <div className="card p-4">
          <InterpretationPanel interp={interpretation} />
        </div>
      )}
    </div>
  );
}
