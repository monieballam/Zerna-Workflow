'use client';

import { useMemo } from 'react';
import AnnotationEvidenceCard from './AnnotationEvidenceCard';
import type { ClusterInspectorSummary } from './cluster-inspector-types';

export type { ClusterInspectorSummary } from './cluster-inspector-types';

function formatConfidence(confidence: string): string {
  return confidence.replace(/_/g, ' ');
}

/** Global Leiden-style IDs use a # prefix; lineage partition IDs (e.g. Immune:0) stay as-is. */
function formatInspectorTechnicalClusterId(clusterId: string, mode: 'global' | 'lineage'): string {
  if (mode === 'lineage') return clusterId;
  return `#${clusterId}`;
}

function ClusterInspectorChevron() {
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

export default function ClusterInspector({
  clusterSummaries,
  selectedClusterId,
  onSelectCluster,
  selectedCluster,
  geneOverlayGene,
  onMarkerClick,
  listLabelFor,
  aliasForSelected,
  onAliasSave,
  inspectorMode = 'global',
  partitionSubtype,
  userClusterAliases = {},
  biologyFineUnresolvedNote = null,
}: {
  clusterSummaries: ClusterInspectorSummary[];
  selectedClusterId: string | null;
  onSelectCluster: (id: string) => void;
  selectedCluster: ClusterInspectorSummary | null;
  geneOverlayGene: string | null;
  onMarkerClick: (gene: string) => void;
  listLabelFor: (cluster: ClusterInspectorSummary) => string;
  aliasForSelected: string;
  onAliasSave: (clusterId: string, alias: string) => void;
  /** Lineage / fine explorer views use partition IDs and cohort-scoped summaries from the API. */
  inspectorMode?: 'global' | 'lineage';
  /** When ``inspectorMode`` is lineage, distinguishes P2 lineage vs P3 fine embedding views. */
  partitionSubtype?: 'lineage' | 'fine';
  /** Browser-stored display aliases only (do not use for cohort-derived headline diffs). */
  userClusterAliases?: Record<string, string>;
  /** Shown under the biology headline when auto_level3 is missing for the selected cluster. */
  biologyFineUnresolvedNote?: string | null;
}) {
  const hasEvidence = selectedCluster && selectedCluster.evidence_hits.length > 0;
  const hasCandidates = selectedCluster && selectedCluster.top_cell_types.length > 0;

  const unitPlural = inspectorMode === 'lineage' ? 'partitions' : 'clusters';

  const collapsedSummary = useMemo(() => {
    if (clusterSummaries.length === 0) {
      return `No ${unitPlural} for the current filter set.`;
    }
    const n = clusterSummaries.length.toLocaleString();
    if (selectedCluster) {
      const tid = formatInspectorTechnicalClusterId(selectedCluster.cluster_id, inspectorMode);
      return `${n} ${unitPlural} · Inspecting ${listLabelFor(selectedCluster)} (${tid}). Expand for list, markers, and evidence.`;
    }
    return `${n} ${unitPlural} · Select one to inspect annotations, markers, and reference matches.`;
  }, [clusterSummaries.length, selectedCluster, inspectorMode, listLabelFor, unitPlural]);

  return (
    <details
      data-testid="results-cluster-inspector-details"
      className="group card overflow-hidden border-dashed border-gray-200 bg-gray-50/60 [&_summary::-webkit-details-marker]:hidden"
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-6 text-left hover:bg-gray-50/80">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-gray-800">
            Cluster Inspector
            {inspectorMode === 'lineage' ? (
              <span className="ml-1.5 font-normal text-gray-500">
                {partitionSubtype === 'fine' ? '(fine view)' : '(lineage view)'}
              </span>
            ) : null}
          </h2>
          <p
            data-testid="results-cluster-inspector-collapsed-summary"
            className="mt-1 max-w-xl text-xs text-gray-500"
          >
            {collapsedSummary}
          </p>
        </div>
        <ClusterInspectorChevron />
      </summary>
      <div className="border-t border-gray-100 px-6 pb-6 pt-4">
        <div className="grid gap-4 xl:grid-cols-[16rem_minmax(0,1fr)]">
          <div className="card p-4">
            {clusterSummaries.length === 0 ? (
              <p className="text-xs text-gray-400">No clusters for the current filter set.</p>
            ) : (
              <div className="space-y-1">
                {clusterSummaries.map((cluster) => {
                  const primary = listLabelFor(cluster);
                  const aliasText = userClusterAliases[cluster.cluster_id]?.trim() ?? '';
                  const hasUserAlias = Boolean(aliasText);
                  return (
                    <button
                      key={cluster.cluster_id}
                      onClick={() => onSelectCluster(cluster.cluster_id)}
                      type="button"
                      className={`w-full rounded-lg px-3 py-2 text-left transition-colors ${
                        selectedClusterId === cluster.cluster_id
                          ? 'bg-blue-50 text-blue-800'
                          : 'hover:bg-gray-50'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-gray-600">
                          {formatInspectorTechnicalClusterId(cluster.cluster_id, inspectorMode)}
                        </span>
                        <span className="ml-auto text-xs tabular-nums text-gray-500">
                          {cluster.n_cells.toLocaleString()}
                        </span>
                      </div>
                      <p
                        className="mt-0.5 truncate text-sm font-medium text-gray-900"
                        title={primary}
                      >
                        {primary}
                      </p>
                      {hasUserAlias ? (
                        <p
                          className="truncate text-[10px] text-amber-900/80"
                          title="Browser-only; does not change structural biology or saved annotation"
                        >
                          Technical display alias (browser only):{' '}
                          <span className="font-mono font-medium">{aliasText}</span>
                        </p>
                      ) : null}
                      <p className="text-[11px] text-gray-500">
                        {formatConfidence(cluster.confidence)}
                      </p>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <div className="card p-4">
            {selectedCluster == null ? (
              <p className="text-xs text-gray-400">
                Select a cluster to inspect annotations and markers.
              </p>
            ) : (
              <div className="space-y-4" data-testid="cluster-detail">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                      {inspectorMode === 'lineage'
                        ? partitionSubtype === 'fine'
                          ? 'Fine partition'
                          : 'Lineage partition'
                        : 'Cluster'}{' '}
                      {formatInspectorTechnicalClusterId(selectedCluster.cluster_id, inspectorMode)}
                    </p>
                    <p
                      className="mt-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500"
                      data-testid="cluster-detail-biology-headline-caption"
                    >
                      Primary biology headline
                    </p>
                    <h3 className="mt-0.5 text-lg font-semibold text-gray-900">
                      {listLabelFor(selectedCluster)}
                    </h3>
                    {biologyFineUnresolvedNote ? (
                      <p className="mt-1 text-[11px] leading-snug text-slate-600">
                        {biologyFineUnresolvedNote}
                      </p>
                    ) : null}
                    {selectedCluster.display_label_secondary ? (
                      <p className="mt-1 text-xs text-gray-500">
                        Merged cell-type column (when it differs from the structural headline above;
                        still not raw annotation_label):{' '}
                        <span className="font-medium text-gray-800">
                          {selectedCluster.display_label_secondary}
                        </span>
                      </p>
                    ) : null}
                    {selectedCluster.raw_annotation_label_mode &&
                    selectedCluster.raw_annotation_label_mode.trim() !==
                      listLabelFor(selectedCluster).trim() ? (
                      <p
                        className="mt-1 text-xs text-amber-900/85"
                        data-testid="cluster-detail-raw-zerna"
                      >
                        Raw <span className="font-mono">annotation_label</span> (legacy engine —
                        debug only; not the structural hierarchy):{' '}
                        <span className="font-medium">
                          {selectedCluster.raw_annotation_label_mode}
                        </span>
                      </p>
                    ) : null}
                    <p
                      className="mt-1 text-xs text-gray-500"
                      data-testid="cluster-detail-pipeline-saved"
                    >
                      Pipeline / saved label:{' '}
                      <span className="font-medium text-gray-800">{selectedCluster.label}</span>
                    </p>
                    {aliasForSelected ? (
                      <p
                        className="mt-1 text-xs text-amber-900/90"
                        data-testid="cluster-detail-technical-alias"
                        title="Browser-only; does not change structural biology or saved annotation"
                      >
                        Technical display alias (browser only):{' '}
                        <span className="font-mono font-semibold">{aliasForSelected}</span>
                      </p>
                    ) : null}
                    {selectedCluster.summary ? (
                      <p className="mt-2 text-sm text-gray-600">{selectedCluster.summary}</p>
                    ) : null}
                  </div>
                  <div className="rounded-lg bg-gray-50 px-3 py-2 text-right">
                    <p className="text-[10px] text-gray-500">Cells</p>
                    <p className="text-base font-semibold tabular-nums text-gray-900">
                      {selectedCluster.n_cells.toLocaleString()}
                    </p>
                    <p className="text-[10px] text-gray-500">Confidence</p>
                    <p className="text-xs text-gray-700">
                      {formatConfidence(selectedCluster.confidence)}
                    </p>
                  </div>
                </div>

                <AnnotationEvidenceCard
                  cluster={selectedCluster}
                  displayAlias={aliasForSelected}
                  onAliasSave={onAliasSave}
                  geneOverlayGene={geneOverlayGene}
                  onGeneClick={onMarkerClick}
                  technicalIdKind={
                    inspectorMode === 'lineage'
                      ? partitionSubtype === 'fine'
                        ? 'fine_partition'
                        : 'lineage_partition'
                      : 'cluster'
                  }
                />

                {hasCandidates ? (
                  <details className="rounded-lg border border-gray-100 bg-gray-50/50 p-3">
                    <summary className="cursor-pointer text-xs font-semibold text-gray-700">
                      Top candidate labels
                    </summary>
                    <table className="mt-2 w-full text-xs">
                      <thead>
                        <tr className="border-b border-gray-100 text-left text-gray-500">
                          <th className="pb-1.5 font-medium">Cell type</th>
                          <th className="pb-1.5 text-right font-medium">Score</th>
                          <th className="pb-1.5 text-right font-medium">Markers</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50">
                        {selectedCluster!.top_cell_types.map((candidate) => (
                          <tr key={candidate.cell_type}>
                            <td className="py-1.5 text-gray-900">{candidate.cell_type}</td>
                            <td className="py-1.5 text-right font-mono text-gray-600">
                              {candidate.score.toFixed(3)}
                            </td>
                            <td className="py-1.5 text-right font-mono text-gray-600">
                              {candidate.n_markers}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </details>
                ) : null}

                {hasEvidence ? (
                  <details className="rounded-lg border border-gray-100 bg-gray-50/50 p-3">
                    <summary className="cursor-pointer text-xs font-semibold text-gray-700">
                      Reference matches
                    </summary>
                    <div className="mt-2 space-y-2">
                      {selectedCluster!.evidence_hits.map((hit) => (
                        <div
                          key={`${hit.cluster_id ?? 'match'}-${hit.label}`}
                          className="rounded border border-gray-200 bg-white px-2.5 py-1.5"
                        >
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-medium text-gray-900">{hit.label}</span>
                            <span className="ml-auto font-mono text-[11px] text-gray-500">
                              {hit.score.toFixed(3)}
                            </span>
                          </div>
                          <p className="mt-0.5 text-[10px] text-gray-500">
                            {hit.lineage ? `${hit.lineage} lineage` : 'Lineage unavailable'}
                            {hit.cluster_id ? ` · ref ${hit.cluster_id}` : ''}
                          </p>
                        </div>
                      ))}
                    </div>
                  </details>
                ) : selectedCluster.evidence_count === 0 ? (
                  <p className="text-[11px] text-gray-400">
                    No retrieval evidence for this cluster.
                  </p>
                ) : null}
              </div>
            )}
          </div>
        </div>
      </div>
    </details>
  );
}
