'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

interface EmbeddingCell {
  id: string;
  x: number;
  y: number;
}

interface CellMeta {
  cellId: string;
  cluster: string | null;
  cellType: string | null;
}

interface EmbeddingData {
  embedding_key: string;
  cells: EmbeddingCell[];
  metadata: CellMeta[];
  cluster_labels?: Record<string, string>;
  bounds: { minX: number; maxX: number; minY: number; maxY: number };
  available_fields: string[];
  total_cells: number;
  sampled: boolean;
}

function sortClusterKeys(values: string[]): string[] {
  return [...values].sort((a, b) => {
    const aNum = Number(a);
    const bNum = Number(b);
    const aNumeric = Number.isFinite(aNum);
    const bNumeric = Number.isFinite(bNum);
    if (aNumeric && bNumeric) return aNum - bNum;
    if (aNumeric) return -1;
    if (bNumeric) return 1;
    return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
  });
}

function getEmbeddingKindLabel(embeddingKey?: string | null): string {
  if (embeddingKey === 'X_tsne') return 't-SNE';
  return 'UMAP';
}

function getAxisLabels(embeddingKey?: string | null): { x: string; y: string } {
  if (embeddingKey === 'X_tsne') return { x: 't-SNE 1', y: 't-SNE 2' };
  return { x: 'UMAP 1', y: 'UMAP 2' };
}

function formatClusterLegendLabel(clusterId: string, clusterLabel?: string): string {
  if (!clusterLabel || clusterLabel.trim() === '' || clusterLabel === clusterId) {
    return `Cluster ${clusterId}`;
  }
  return `Cluster ${clusterId} · ${clusterLabel}`;
}

function SnapshotCollapseChevron() {
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

const CLUSTER_COLORS = [
  '#1f77b4',
  '#ff7f0e',
  '#2ca02c',
  '#d62728',
  '#9467bd',
  '#8c564b',
  '#e377c2',
  '#7f7f7f',
  '#bcbd22',
  '#17becf',
  '#aec7e8',
  '#ffbb78',
  '#98df8a',
  '#ff9896',
  '#c5b0d5',
  '#c49c94',
  '#f7b6d2',
  '#c7c7c7',
  '#dbdb8d',
  '#9edae5',
  '#393b79',
  '#5254a3',
  '#6b6ecf',
  '#9c9ede',
  '#637939',
];

export default function UMAPViewer({ runId }: { runId: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [data, setData] = useState<EmbeddingData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hoveredCluster, setHoveredCluster] = useState<string | null>(null);
  const [maxCells] = useState(50000);

  useEffect(() => {
    async function fetchEmbedding() {
      try {
        const res = await fetch(`/api/proxy/v1/runs/${runId}/embedding?max_cells=${maxCells}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const payload = (await res.json()) as EmbeddingData;
        setData(payload);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load embedding');
      } finally {
        setLoading(false);
      }
    }
    void fetchEmbedding();
  }, [runId, maxCells]);

  const draw = useCallback(() => {
    if (!data || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth;
    const H = canvas.clientHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.scale(dpr, dpr);

    // Clear
    ctx.fillStyle = '#fafafa';
    ctx.fillRect(0, 0, W, H);

    const { bounds, cells, metadata } = data;
    const pad = 30;
    const plotW = W - pad * 2;
    const plotH = H - pad * 2;

    // Map data coords to canvas coords
    const rangeX = bounds.maxX - bounds.minX || 1;
    const rangeY = bounds.maxY - bounds.minY || 1;
    const scale = Math.min(plotW / rangeX, plotH / rangeY);
    const offsetX = pad + (plotW - rangeX * scale) / 2;
    const offsetY = pad + (plotH - rangeY * scale) / 2;

    // Build cluster color map
    const clusterSet = new Set<string>();
    for (const m of metadata) {
      if (m.cluster != null) clusterSet.add(m.cluster);
    }
    const clusters = sortClusterKeys(Array.from(clusterSet));
    const colorMap: Record<string, string> = {};
    clusters.forEach((c, i) => {
      colorMap[c] = CLUSTER_COLORS[i % CLUSTER_COLORS.length];
    });
    const axisLabels = getAxisLabels(data.embedding_key);

    // Draw points
    const pointSize = cells.length > 20000 ? 1 : cells.length > 5000 ? 1.5 : 2;
    for (let i = 0; i < cells.length; i++) {
      const cell = cells[i];
      const meta = metadata[i];
      const cx = offsetX + (cell.x - bounds.minX) * scale;
      const cy = offsetY + (bounds.maxY - cell.y) * scale; // flip Y

      const cluster = meta.cluster ?? '0';
      const color = colorMap[cluster] ?? '#999';

      // Dim non-hovered clusters
      if (hoveredCluster !== null && cluster !== hoveredCluster) {
        ctx.globalAlpha = 0.08;
      } else {
        ctx.globalAlpha = 0.7;
      }

      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(cx, cy, pointSize, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    // Draw axis labels
    ctx.fillStyle = '#9ca3af';
    ctx.font = '11px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(axisLabels.x, W / 2, H - 6);
    ctx.save();
    ctx.translate(12, H / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(axisLabels.y, 0, 0);
    ctx.restore();
  }, [data, hoveredCluster]);

  useEffect(() => {
    draw();
  }, [draw]);

  // Resize handler
  useEffect(() => {
    const handleResize = () => draw();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [draw]);

  if (loading) {
    return (
      <div className="card border-dashed border-gray-200 bg-gray-50/60 p-6">
        <h2 className="mb-3 text-sm font-semibold text-gray-800">Saved Embedding Snapshot</h2>
        <div className="flex h-96 items-center justify-center text-sm text-gray-400 animate-pulse">
          Loading embedding data…
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="card border-dashed border-gray-200 bg-gray-50/60 p-6">
        <h2 className="mb-3 text-sm font-semibold text-gray-800">Saved Embedding Snapshot</h2>
        <p className="text-sm text-gray-500">{error ?? 'No embedding data available.'}</p>
      </div>
    );
  }

  // Build legend
  const clusterSet = new Set<string>();
  for (const m of data.metadata) {
    if (m.cluster != null) clusterSet.add(m.cluster);
  }
  const clusters = sortClusterKeys(Array.from(clusterSet));
  const clusterCounts: Record<string, number> = {};
  for (const m of data.metadata) {
    const c = m.cluster ?? '?';
    clusterCounts[c] = (clusterCounts[c] || 0) + 1;
  }
  const colorMap: Record<string, string> = {};
  clusters.forEach((c, i) => {
    colorMap[c] = CLUSTER_COLORS[i % CLUSTER_COLORS.length];
  });
  const kind = getEmbeddingKindLabel(data.embedding_key);
  const cellSummary = `${data.total_cells.toLocaleString()} cells${
    data.sampled ? ` (showing ${data.cells.length.toLocaleString()})` : ''
  }`;

  return (
    <details
      data-testid="results-embedding-snapshot-details"
      className="group card overflow-hidden border-dashed border-gray-200 bg-gray-50/60 [&_summary::-webkit-details-marker]:hidden"
      onToggle={(e) => {
        const el = e.currentTarget;
        if (el.open) {
          requestAnimationFrame(() => draw());
        }
      }}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-6 text-left hover:bg-gray-50/80">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-gray-800">Saved Embedding Snapshot</h2>
          <p
            data-testid="results-embedding-snapshot-collapsed-summary"
            className="mt-1 max-w-xl text-xs text-gray-500"
          >
            Static {kind} preview · {cellSummary} — colored by cluster. Expand for the static plot;
            use Explorer for interactive view.
          </p>
        </div>
        <SnapshotCollapseChevron />
      </summary>
      <div className="border-t border-gray-100 px-6 pb-6 pt-4">
        <p className="mb-4 max-w-xl text-xs text-gray-500">
          Use the Explorer tab for the interactive embedding, filters, and gene overlays.
        </p>

        <div className="flex gap-4">
          <div className="flex-1">
            <canvas
              ref={canvasRef}
              className="w-full rounded border border-gray-200"
              style={{ height: 480 }}
            />
          </div>

          <div className="w-40 max-h-[480px] overflow-y-auto">
            <p className="mb-2 text-xs font-medium text-gray-500">Clusters</p>
            <div className="space-y-1">
              {clusters.map((c) => (
                <button
                  key={c}
                  type="button"
                  className={`flex w-full items-center gap-2 rounded px-1.5 py-0.5 text-left text-xs transition-colors ${
                    hoveredCluster === c ? 'bg-gray-100' : 'hover:bg-gray-50'
                  }`}
                  onMouseEnter={() => setHoveredCluster(c)}
                  onMouseLeave={() => setHoveredCluster(null)}
                >
                  <span
                    className="h-2.5 w-2.5 flex-shrink-0 rounded-full"
                    style={{ backgroundColor: colorMap[c] ?? '#999' }}
                  />
                  <span className="text-gray-700">
                    {formatClusterLegendLabel(c, data.cluster_labels?.[c])}
                  </span>
                  <span className="ml-auto text-gray-400">{clusterCounts[c]}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </details>
  );
}
