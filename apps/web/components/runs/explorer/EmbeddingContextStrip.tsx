'use client';

/** Compact state row above the embedding: view-by layer, focus, inspector cluster. */
export default function EmbeddingContextStrip({
  colorFieldLabel,
  geneOverlayGene,
  focusLabel,
  selectedClusterLine,
  viewContextLine,
  clusterInspectorLabel,
}: {
  colorFieldLabel: string;
  geneOverlayGene: string | null;
  focusLabel: string | null;
  /** e.g. "Cluster 3 · Memory T cell" — always from inspector when present */
  selectedClusterLine: string | null;
  /** Short line describing Global vs lineage embedding + coordinate source */
  viewContextLine?: string | null;
  /** Label for the inspector cluster slot, e.g. "Partition" in lineage views */
  clusterInspectorLabel?: string;
}) {
  const clusterHeading = clusterInspectorLabel ?? 'Cluster';
  return (
    <div
      className="rounded-lg border border-slate-200/90 bg-gradient-to-r from-slate-50/90 to-white px-3 py-2 text-xs text-gray-700 shadow-sm"
      data-testid="embedding-context-strip"
    >
      {viewContextLine ? (
        <p className="mb-1.5 border-b border-slate-100 pb-1.5 text-[11px] text-slate-600">
          {viewContextLine}
        </p>
      ) : null}
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span>
          <span className="font-semibold text-gray-500">View by</span>{' '}
          <span className="text-gray-900">{colorFieldLabel}</span>
          {geneOverlayGene ? (
            <span
              className="ml-1.5 rounded-md border border-indigo-200 bg-indigo-50 px-1.5 py-0.5 font-mono text-[11px] font-medium text-indigo-900"
              data-testid="context-gene-chip"
            >
              {geneOverlayGene}
            </span>
          ) : null}
        </span>
        {focusLabel ? (
          <span className="hidden sm:inline text-gray-400" aria-hidden>
            ·
          </span>
        ) : null}
        {focusLabel ? (
          <span data-testid="context-focus-line">
            <span className="font-semibold text-amber-800/90">Focused</span>{' '}
            <span className="text-amber-950">{focusLabel}</span>
          </span>
        ) : null}
        {selectedClusterLine ? (
          <>
            <span className="hidden sm:inline text-gray-400" aria-hidden>
              ·
            </span>
            <span data-testid="context-cluster-line">
              <span className="font-semibold text-slate-600">{clusterHeading}</span>{' '}
              <span className="text-slate-900">{selectedClusterLine}</span>
            </span>
          </>
        ) : null}
      </div>
    </div>
  );
}
