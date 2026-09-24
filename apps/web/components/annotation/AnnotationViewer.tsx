'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import React from 'react';
import type { AnnotationRevision } from '@zerna/sdk';
import { EmbeddingRenderer } from '../../lib/embedding-renderer';
import type { Embedding, CellMetadata, ColorMapping } from '../../lib/embedding-types';

// ── Types ─────────────────────────────────────────────────────────────────────

export type AnnotationLevel = 'tissue' | 'lineage' | 'cell_type';

export interface CellAnnotation {
  tissue: string;
  lineage: string;
  cell_type: string;
  confidence: number;
}

export interface AnnotationViewerProps {
  embedding: Embedding;
  revision: AnnotationRevision | null;
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onCellSelect?: (cellId: string, annotation: CellAnnotation | null) => void;
  rendererRef?: React.RefObject<EmbeddingRenderer | null>;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const LEVEL_LABELS: Record<AnnotationLevel, string> = {
  tissue: 'Tissue',
  lineage: 'Lineage',
  cell_type: 'Cell type',
};

function buildMetadataFromRevision(revision: AnnotationRevision | null): CellMetadata[] {
  if (!revision) return [];
  return Object.entries(revision.annotations).map(([cellId, ann]) => {
    const a = ann as Partial<CellAnnotation>;
    return {
      cellId,
      tissue: a.tissue ?? '',
      lineage: a.lineage ?? '',
      cell_type: a.cell_type ?? '',
      confidence: a.confidence ?? 0,
    };
  });
}

function buildColorMapping(level: AnnotationLevel): ColorMapping {
  return { type: 'categorical', field: level };
}

function buildLegend(metadata: CellMetadata[], level: AnnotationLevel): string[] {
  const values = new Set<string>();
  for (const m of metadata) {
    const v = m[level as keyof CellMetadata];
    if (v != null && v !== '') values.add(String(v));
  }
  return Array.from(values).sort();
}

// ── Component ─────────────────────────────────────────────────────────────────

const CANVAS_WIDTH = 800;
const CANVAS_HEIGHT = 560;

export default function AnnotationViewer({
  embedding,
  revision,
  isLoading = false,
  error = null,
  onRetry,
  onCellSelect,
  rendererRef: externalRendererRef,
}: AnnotationViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<EmbeddingRenderer | null>(null);

  const [ready, setReady] = useState(false);
  const [level, setLevel] = useState<AnnotationLevel>('cell_type');
  const [selectedCellId, setSelectedCellId] = useState<string | null>(null);

  const metadata = buildMetadataFromRevision(revision);
  const metaById = new Map(metadata.map((m) => [m.cellId, m]));
  const legend = buildLegend(metadata, level);

  const handleSelection = useCallback(
    (cellIds: string[]) => {
      const id = cellIds[0] ?? null;
      setSelectedCellId(id);
      if (onCellSelect && id) {
        const m = metaById.get(id);
        const ann: CellAnnotation | null = m
          ? {
              tissue: String(m.tissue ?? ''),
              lineage: String(m.lineage ?? ''),
              cell_type: String(m.cell_type ?? ''),
              confidence: Number(m.confidence ?? 0),
            }
          : null;
        onCellSelect(id, ann);
      }
    },
    [metaById, onCellSelect]
  );

  // Init renderer
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || isLoading || error) return;

    const renderer = new EmbeddingRenderer(
      canvas,
      embedding,
      metadata,
      buildColorMapping(level),
      handleSelection
    );
    rendererRef.current = renderer;
    if (externalRendererRef) externalRendererRef.current = renderer;
    setReady(true);

    return () => {
      renderer.destroy();
      rendererRef.current = null;
      if (externalRendererRef) externalRendererRef.current = null;
      setReady(false);
    };
  }, [embedding, metadata, level, handleSelection, externalRendererRef, isLoading, error]);

  // Update colors when level changes
  useEffect(() => {
    if (!rendererRef.current || !ready) return;
    rendererRef.current.updateColors(buildColorMapping(level));
  }, [level, ready]);

  const selectedMeta = selectedCellId ? metaById.get(selectedCellId) : null;
  const selectedAnn = selectedMeta
    ? {
        tissue: String(selectedMeta.tissue ?? ''),
        lineage: String(selectedMeta.lineage ?? ''),
        cell_type: String(selectedMeta.cell_type ?? ''),
        confidence: Number(selectedMeta.confidence ?? 0),
      }
    : null;

  // ── Render ──────────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div
        className="card p-6 flex items-center justify-center"
        style={{ minHeight: 400 }}
        data-testid="annotation-viewer-loading"
      >
        <div className="flex flex-col items-center gap-3 text-gray-500">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600" />
          <span className="text-sm">Loading annotations…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="card p-6 flex items-center justify-center"
        style={{ minHeight: 400 }}
        data-testid="annotation-viewer-error"
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

  return (
    <div className="flex gap-4" data-testid="annotation-viewer">
      {/* Main viewer */}
      <div className="card p-4 flex-1 min-w-0">
        {/* Toolbar */}
        <div className="flex items-center gap-3 mb-3 flex-wrap">
          <span className="text-sm text-gray-600">Color by</span>
          <div className="flex gap-1">
            {(['tissue', 'lineage', 'cell_type'] as AnnotationLevel[]).map((l) => (
              <button
                key={l}
                onClick={() => setLevel(l)}
                data-testid={`level-btn-${l}`}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  level === l
                    ? 'bg-blue-600 text-white'
                    : 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
                }`}
              >
                {LEVEL_LABELS[l]}
              </button>
            ))}
          </div>
        </div>

        {/* Canvas */}
        <div className="relative">
          {!ready && (
            <div className="absolute inset-0 flex items-center justify-center bg-gray-50 rounded">
              <span className="text-sm text-gray-500">Initialising renderer…</span>
            </div>
          )}
          <canvas
            ref={canvasRef}
            width={CANVAS_WIDTH}
            height={CANVAS_HEIGHT}
            className="block w-full rounded border border-gray-200 cursor-pointer"
            data-testid="annotation-canvas"
          />
        </div>

        {/* Legend */}
        {legend.length > 0 && (
          <div className="mt-3" data-testid="annotation-legend">
            <p className="text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">
              {LEVEL_LABELS[level]}
            </p>
            <div className="flex flex-wrap gap-2">
              {legend.map((label) => (
                <span
                  key={label}
                  className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-700"
                >
                  {label}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Cell info panel */}
      {selectedCellId && (
        <div className="card p-4 w-64 shrink-0" data-testid="cell-info-panel">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-700">Cell info</h2>
            <button
              onClick={() => setSelectedCellId(null)}
              className="text-xs text-gray-400 hover:text-gray-600"
            >
              Close
            </button>
          </div>
          <p className="font-mono text-xs text-gray-500 mb-3 truncate">{selectedCellId}</p>
          {selectedAnn ? (
            <dl className="space-y-2 text-sm">
              <div>
                <dt className="text-gray-500 text-xs">Tissue</dt>
                <dd className="text-gray-900 font-medium">{selectedAnn.tissue || '—'}</dd>
              </div>
              <div>
                <dt className="text-gray-500 text-xs">Lineage</dt>
                <dd className="text-gray-900 font-medium">{selectedAnn.lineage || '—'}</dd>
              </div>
              <div>
                <dt className="text-gray-500 text-xs">Cell type</dt>
                <dd className="text-gray-900 font-medium">{selectedAnn.cell_type || '—'}</dd>
              </div>
              <div>
                <dt className="text-gray-500 text-xs">Confidence</dt>
                <dd className="text-gray-900 font-medium">
                  {(selectedAnn.confidence * 100).toFixed(1)}%
                </dd>
              </div>
            </dl>
          ) : (
            <p className="text-xs text-gray-400">No annotation data</p>
          )}
        </div>
      )}
    </div>
  );
}
