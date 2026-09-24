/**
 * Dynamically imported components for code splitting.
 * Heavy components (WebGL, large tables, network graphs) are loaded on demand
 * to reduce initial bundle size.
 */

import dynamic from 'next/dynamic';

/** EmbeddingViewer — heavy, uses deck.gl/WebGL. SSR disabled. */
export const LazyEmbeddingViewer = dynamic(() => import('@/components/embedding/EmbeddingViewer'), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center min-h-[400px] bg-gray-50 rounded border border-gray-200 animate-pulse">
      <span className="text-sm text-gray-400">Loading embedding viewer…</span>
    </div>
  ),
});

/** EmbeddingComparison — heavy, renders two embedding viewers. SSR disabled. */
export const LazyEmbeddingComparison = dynamic(
  () => import('@/components/embedding/EmbeddingComparison'),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center min-h-[400px] bg-gray-50 rounded border border-gray-200 animate-pulse">
        <span className="text-sm text-gray-400">Loading comparison view…</span>
      </div>
    ),
  }
);

/** DEViewer — medium, renders large sortable tables with volcano plot. */
export const LazyDEViewer = dynamic(() => import('@/components/analysis/DEViewer'), {
  loading: () => (
    <div className="flex items-center justify-center min-h-[300px] bg-gray-50 rounded animate-pulse">
      <span className="text-sm text-gray-400">Loading DE results…</span>
    </div>
  ),
});

/** PathwayViewer — medium, renders pathway enrichment data. */
export const LazyPathwayViewer = dynamic(() => import('@/components/analysis/PathwayViewer'), {
  loading: () => (
    <div className="flex items-center justify-center min-h-[300px] bg-gray-50 rounded animate-pulse">
      <span className="text-sm text-gray-400">Loading pathway data…</span>
    </div>
  ),
});

/** LigandReceptorViewer — medium, renders network graphs. */
export const LazyLigandReceptorViewer = dynamic(
  () => import('@/components/analysis/LigandReceptorViewer'),
  {
    loading: () => (
      <div className="flex items-center justify-center min-h-[300px] bg-gray-50 rounded animate-pulse">
        <span className="text-sm text-gray-400">Loading interaction data…</span>
      </div>
    ),
  }
);

/** ExportCenter — medium, handles file generation. */
export const LazyExportCenter = dynamic(() => import('@/components/analysis/ExportCenter'), {
  loading: () => (
    <div className="flex items-center justify-center min-h-[200px] bg-gray-50 rounded animate-pulse">
      <span className="text-sm text-gray-400">Loading export options…</span>
    </div>
  ),
});
