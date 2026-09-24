'use client';

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import React from 'react';
import type { Embedding, CellMetadata, ColorMapping } from '@/lib/embedding-types';
import { EmbeddingRenderer, type EmbeddingDebugSnapshot } from '@/lib/embedding-renderer';
import {
  formatExplorerFieldLabel,
  sortExplorerFieldsForUi,
  sortExplorerMetadataEntries,
} from '@/lib/explorer-field-metadata';
import { shortenPlotLabel } from '@/lib/embedding-label-short';

const HIERARCHY_CENTROID_FIELDS = [
  'lineage',
  'level2',
  'level3',
  'displayLabel',
  'cellType',
  'celltype',
] as const;

function resolveLabelFieldForMode(
  mode: 'none' | 'cluster' | 'cellType',
  availableFields: string[],
  colorField: string,
  continuousFields: string[]
): string | null {
  if (mode === 'none') return null;
  if (mode === 'cluster') {
    if (availableFields.includes('cluster')) return 'cluster';
    return null;
  }
  // "cellType" mode = biology-facing centroid labels: prefer the same field as View by when it is
  // a hierarchy column so legend and on-plot text stay aligned.
  const colorIsHierarchy =
    colorField &&
    !continuousFields.includes(colorField) &&
    (HIERARCHY_CENTROID_FIELDS as readonly string[]).includes(colorField) &&
    availableFields.includes(colorField);
  if (colorIsHierarchy) {
    return colorField;
  }
  for (const k of HIERARCHY_CENTROID_FIELDS) {
    if (availableFields.includes(k)) return k;
  }
  return null;
}

interface EmbeddingViewerProps {
  embedding: Embedding;
  metadata: CellMetadata[];
  availableFields: string[];
  continuousFields?: string[];
  fieldRanges?: Record<string, { min: number; max: number }>;
  rendererRef?: React.RefObject<EmbeddingRenderer | null>;
  activeColorField?: string;
  onActiveColorFieldChange?: (field: string) => void;
  formatCategoryLegendLabel?: (field: string, rawValue: string) => string;
  /** On-plot centroid strings only (omit to use {@link formatCategoryLegendLabel}). */
  formatCentroidLabel?: (field: string, rawValue: string) => string;
  formatMetadataDisplayValue?: (field: string, rawValue: string) => string;
  /** Centroid labels: cluster mode uses the ``cluster`` field (label text from ``formatCentroidLabel`` / legend); biology mode tracks View by when possible. */
  labelMode?: 'none' | 'cluster' | 'cellType';
  onLabelModeChange?: (mode: 'none' | 'cluster' | 'cellType') => void;
  /** Parent renders legend (e.g. below workspace); hide inline legend. */
  hideInternalLegend?: boolean;
  /** Dim all but this category (categorical color-by field must match ``field``). */
  focusCategory?: { field: string; rawValue: string } | null;
  /** Legend hover → subtle dim on UMAP. */
  legendHoverRaw?: string | null;
  /** Hide color-by and label controls (e.g. parent toolbar owns them). */
  compactToolbar?: boolean;
}

export default function EmbeddingViewer({
  embedding,
  metadata,
  availableFields,
  continuousFields = [],
  fieldRanges = {},
  rendererRef: externalRendererRef,
  activeColorField,
  onActiveColorFieldChange,
  formatCategoryLegendLabel,
  formatCentroidLabel,
  formatMetadataDisplayValue,
  labelMode: labelModeProp,
  onLabelModeChange,
  hideInternalLegend = false,
  focusCategory = null,
  legendHoverRaw = null,
  compactToolbar = false,
}: EmbeddingViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const canvasBoxRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<EmbeddingRenderer | null>(null);

  const [ready, setReady] = useState(false);
  const [uncontrolledColorField, setUncontrolledColorField] = useState(
    activeColorField ?? availableFields[0] ?? ''
  );
  const [lassoActive, setLassoActive] = useState(false);
  const [uncontrolledLabelMode, setUncontrolledLabelMode] = useState<
    'none' | 'cluster' | 'cellType'
  >('none');
  const labelMode = labelModeProp ?? uncontrolledLabelMode;
  const [selectedCells, setSelectedCells] = useState<string[]>([]);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [devDiag, setDevDiag] = useState<EmbeddingDebugSnapshot | null>(null);
  const colorField = activeColorField ?? uncontrolledColorField;
  const isCategoricalColor = !continuousFields.includes(colorField);

  const resolvedLabelField = useMemo(
    () => resolveLabelFieldForMode(labelMode, availableFields, colorField, continuousFields),
    [labelMode, availableFields, colorField, continuousFields]
  );

  const formatPlotLabelShort = useCallback(
    (field: string, raw: string) => {
      const full =
        formatCentroidLabel?.(field, raw) ?? formatCategoryLegendLabel?.(field, raw) ?? raw;
      return shortenPlotLabel(full);
    },
    [formatCategoryLegendLabel, formatCentroidLabel]
  );

  const labelFocusForRenderer = useMemo(() => {
    if (!focusCategory || !resolvedLabelField) return null;
    if (focusCategory.field !== resolvedLabelField) return null;
    return focusCategory;
  }, [focusCategory, resolvedLabelField]);

  const orderedColorFields = useMemo(
    () => sortExplorerFieldsForUi(availableFields),
    [availableFields]
  );

  const categoricalLegend = useMemo(() => {
    if (continuousFields.includes(colorField)) return null;
    const counts = new Map<string, number>();
    for (const m of metadata) {
      const v = String(m[colorField] ?? '').trim();
      if (!v) continue;
      counts.set(v, (counts.get(v) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 28);
  }, [metadata, colorField, continuousFields]);

  const setLabelMode = useCallback(
    (m: 'none' | 'cluster' | 'cellType') => {
      if (labelModeProp == null) setUncontrolledLabelMode(m);
      onLabelModeChange?.(m);
    },
    [labelModeProp, onLabelModeChange]
  );

  // Lasso drawing state
  const lassoPoints = useRef<{ x: number; y: number }[]>([]);
  const isDrawing = useRef(false);

  // Build a ColorMapping from the selected field
  const buildColorMapping = useCallback(
    (field: string): ColorMapping => {
      if (continuousFields.includes(field)) {
        const range = fieldRanges[field] ?? { min: 0, max: 1 };
        return { type: 'continuous', field, min: range.min, max: range.max };
      }
      return { type: 'categorical', field };
    },
    [continuousFields, fieldRanges]
  );

  const updateColorField = useCallback(
    (field: string) => {
      if (activeColorField == null) {
        setUncontrolledColorField(field);
      }
      onActiveColorFieldChange?.(field);
    },
    [activeColorField, onActiveColorFieldChange]
  );

  useEffect(() => {
    if (activeColorField != null) {
      setUncontrolledColorField(activeColorField);
    }
  }, [activeColorField]);

  useEffect(() => {
    const fallback = orderedColorFields[0] ?? '';
    if (!fallback) return;
    if (colorField && orderedColorFields.includes(colorField)) return;
    updateColorField(fallback);
  }, [orderedColorFields, colorField, updateColorField]);

  // Init renderer
  useEffect(() => {
    const canvas = canvasRef.current;
    const box = canvasBoxRef.current;
    if (!canvas || !box) return;

    let renderer: EmbeddingRenderer | null = null;

    const w = Math.max(4, Math.floor(box.clientWidth));
    const h = Math.max(4, Math.floor(box.clientHeight));
    const dpr = Math.min(typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1, 2);
    if (w >= 4 && h >= 4) {
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
    }

    try {
      const initialColor = buildColorMapping(colorField);
      renderer = new EmbeddingRenderer(
        canvas,
        embedding,
        metadata,
        initialColor,
        (ids) => setSelectedCells(ids),
        {
          formatCategoryLegendLabel,
          formatCentroidLabel,
          formatPlotLabelShort,
        }
      );
      rendererRef.current = renderer;
      if (externalRendererRef) externalRendererRef.current = renderer;
      setRenderError(null);
      setReady(true);
    } catch (error) {
      rendererRef.current = null;
      if (externalRendererRef) externalRendererRef.current = null;
      setReady(false);
      setRenderError(
        error instanceof Error ? error.message : 'Embedding viewer failed to initialize'
      );
    }

    return () => {
      renderer?.destroy();
      rendererRef.current = null;
      if (externalRendererRef) externalRendererRef.current = null;
    };
  }, [
    buildColorMapping,
    colorField,
    embedding,
    externalRendererRef,
    formatCategoryLegendLabel,
    formatCentroidLabel,
    formatPlotLabelShort,
    metadata,
  ]);

  // Update colors when field changes
  useEffect(() => {
    if (!rendererRef.current || !ready) return;
    rendererRef.current.updateColors(buildColorMapping(colorField));
  }, [colorField, buildColorMapping, ready]);

  // Centroid labels (field from label mode; may differ from color-by)
  useEffect(() => {
    if (!rendererRef.current || !ready) return;
    rendererRef.current.setLabelsOptions({
      enabled: Boolean(resolvedLabelField),
      field: resolvedLabelField,
      focusCategory: labelFocusForRenderer,
    });
  }, [resolvedLabelField, ready, labelFocusForRenderer]);

  // Focus / hover dimming (categorical color-by only)
  useEffect(() => {
    if (!rendererRef.current || !ready) return;
    const f = focusCategory;
    if (f && f.field === colorField && isCategoricalColor) {
      rendererRef.current.setFocusCategory(f.field, f.rawValue);
    } else {
      rendererRef.current.setFocusCategory(null, null);
    }
  }, [focusCategory, colorField, isCategoricalColor, ready]);

  useEffect(() => {
    if (!rendererRef.current || !ready) return;
    if (legendHoverRaw && isCategoricalColor) {
      rendererRef.current.setHoverCategory(colorField, legendHoverRaw);
    } else {
      rendererRef.current.setHoverCategory(null, null);
    }
  }, [legendHoverRaw, colorField, isCategoricalColor, ready]);

  // Dev diagnostics snapshot
  useEffect(() => {
    if (process.env.NODE_ENV !== 'development' || !ready || !rendererRef.current) return;
    const id = window.setInterval(() => {
      setDevDiag(rendererRef.current?.getDebugSnapshot() ?? null);
    }, 1000);
    return () => window.clearInterval(id);
  }, [ready, embedding, metadata]);

  // Match WebGL buffer + deck viewport to the canvas box (flex layouts often report 0×0 on first paint).
  useEffect(() => {
    if (!ready || !rendererRef.current || !canvasRef.current || !canvasBoxRef.current) return;

    const canvas = canvasRef.current;
    const box = canvasBoxRef.current;
    const renderer = rendererRef.current;

    const syncSize = () => {
      const w = Math.max(4, Math.floor(box.clientWidth));
      const h = Math.max(4, Math.floor(box.clientHeight));
      if (w < 4 || h < 4) return;
      const dpr = Math.min(typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1, 2);
      const bw = Math.floor(w * dpr);
      const bh = Math.floor(h * dpr);
      if (canvas.width !== bw || canvas.height !== bh) {
        canvas.width = bw;
        canvas.height = bh;
      }
      renderer.resizeViewport(w, h);
    };

    syncSize();
    const ro = new ResizeObserver(() => syncSize());
    ro.observe(box);
    return () => ro.disconnect();
  }, [ready, embedding, metadata]);

  // Lasso mouse handlers
  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!lassoActive) return;
      const rect = (e.target as HTMLCanvasElement).getBoundingClientRect();
      isDrawing.current = true;
      lassoPoints.current = [{ x: e.clientX - rect.left, y: e.clientY - rect.top }];
    },
    [lassoActive]
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!lassoActive || !isDrawing.current) return;
      const rect = (e.target as HTMLCanvasElement).getBoundingClientRect();
      lassoPoints.current.push({ x: e.clientX - rect.left, y: e.clientY - rect.top });
    },
    [lassoActive]
  );

  const handleMouseUp = useCallback(() => {
    if (!lassoActive || !isDrawing.current) return;
    isDrawing.current = false;
    if (rendererRef.current && lassoPoints.current.length >= 3) {
      rendererRef.current.selectCells(lassoPoints.current);
    }
    lassoPoints.current = [];
  }, [lassoActive]);

  const handleReset = () => rendererRef.current?.zoomToFit();

  // Metadata for selected cells
  const metaById = new Map(metadata.map((m) => [m.cellId, m]));
  const selectedMeta = selectedCells
    .slice(0, 50)
    .map((id) => metaById.get(id))
    .filter(Boolean) as CellMetadata[];

  return (
    <div className="flex gap-4">
      {/* Main viewer */}
      <div className="card p-4 flex-1 min-w-0">
        {/* Toolbar */}
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <button
            onClick={handleReset}
            disabled={!ready}
            className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Reset view
          </button>

          <button
            onClick={() => setLassoActive((v) => !v)}
            disabled={!ready}
            className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
              lassoActive
                ? 'border-blue-500 bg-blue-50 text-blue-700'
                : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
            }`}
          >
            {lassoActive ? 'Lasso: on' : 'Lasso: off'}
          </button>

          {!compactToolbar ? (
            <label className="flex items-center gap-1.5 text-sm text-gray-600">
              <span className="whitespace-nowrap">Labels</span>
              <select
                value={labelMode}
                onChange={(e) => setLabelMode(e.target.value as 'none' | 'cluster' | 'cellType')}
                disabled={!ready}
                className="max-w-[10rem] rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700 disabled:opacity-50"
                title="Centroid labels (sparse, largest groups first)"
              >
                <option value="none">Off</option>
                <option value="cluster">Cluster</option>
                <option value="cellType">Match View by</option>
              </select>
            </label>
          ) : null}

          {!compactToolbar ? (
            <div className="flex items-center gap-1.5 ml-auto">
              <label htmlFor="color-by" className="text-sm text-gray-600">
                Color by
              </label>
              <select
                id="color-by"
                value={colorField}
                onChange={(e) => updateColorField(e.target.value)}
                disabled={!ready}
                className="rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {orderedColorFields.map((f) => (
                  <option key={f} value={f}>
                    {formatExplorerFieldLabel(f)}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <div className="ml-auto" />
          )}
        </div>

        {/* Canvas */}
        <div ref={canvasBoxRef} className="relative w-full min-h-[480px] h-[min(600px,70vh)]">
          {!ready && !renderError && (
            <div className="absolute inset-0 flex items-center justify-center bg-gray-50 rounded">
              <span className="text-sm text-gray-500">Loading…</span>
            </div>
          )}
          {renderError && (
            <div className="absolute inset-0 z-10 flex items-center justify-center rounded border border-dashed border-amber-300 bg-amber-50/95 p-4 text-center">
              <span className="text-sm text-amber-800">{renderError}</span>
            </div>
          )}
          <canvas
            ref={canvasRef}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            className={`block h-full w-full rounded border border-gray-200 ${
              lassoActive ? 'cursor-crosshair' : 'cursor-grab'
            }`}
          />
        </div>
        {!hideInternalLegend && categoricalLegend && categoricalLegend.length > 0 ? (
          <div className="mt-3" data-testid="embedding-internal-legend">
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
              Legend · {formatExplorerFieldLabel(colorField)}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {categoricalLegend.map(([rawVal, n]) => (
                <span
                  key={rawVal}
                  title={`${n.toLocaleString()} cells · id: ${rawVal}`}
                  className="inline-flex max-w-[14rem] truncate rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-800"
                >
                  {formatCategoryLegendLabel?.(colorField, rawVal) ?? rawVal}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        {process.env.NODE_ENV === 'development' && devDiag ? (
          <details className="mt-3 rounded border border-dashed border-gray-300 bg-gray-50/80 p-2 text-[11px] text-gray-600">
            <summary className="cursor-pointer font-medium text-gray-700">
              Embedding diagnostics (dev)
            </summary>
            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[10px] leading-snug">
              {JSON.stringify(devDiag, null, 2)}
            </pre>
            <p className="mt-1 text-[10px] text-gray-500">
              Console: one-time fit log in dev; set{' '}
              <code className="rounded bg-gray-200 px-0.5">
                localStorage zerna:embedding:debug=1
              </code>{' '}
              for logs on every resize/reset.
            </p>
          </details>
        ) : null}
      </div>

      {/* Sidebar */}
      {selectedCells.length > 0 && (
        <div className="card p-4 w-64 shrink-0">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-700">
              Selected ({selectedCells.length})
            </h2>
            <button
              onClick={() => setSelectedCells([])}
              className="text-xs text-gray-400 hover:text-gray-600"
            >
              Clear
            </button>
          </div>
          <ul className="space-y-3 overflow-y-auto max-h-[520px]">
            {selectedMeta.map((m) => (
              <li key={m.cellId} className="text-xs border-b border-gray-100 pb-2">
                <p className="font-mono font-medium text-gray-800 mb-1">{m.cellId}</p>
                <dl className="space-y-0.5">
                  {sortExplorerMetadataEntries(
                    Object.entries(m).filter(([k]) => k !== 'cellId')
                  ).map(([k, v]) => (
                    <div key={k} className="flex gap-1">
                      <dt className="text-gray-500 shrink-0">{formatExplorerFieldLabel(k)}:</dt>
                      <dd className="text-gray-700 truncate">
                        {formatMetadataDisplayValue
                          ? formatMetadataDisplayValue(k, String(v ?? ''))
                          : String(v ?? '—')}
                      </dd>
                    </div>
                  ))}
                </dl>
              </li>
            ))}
          </ul>
          {selectedCells.length > 50 && (
            <p className="mt-2 text-xs text-gray-400">Showing 50 of {selectedCells.length}</p>
          )}
        </div>
      )}
    </div>
  );
}
