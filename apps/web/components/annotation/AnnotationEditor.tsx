'use client';

import { useState, useCallback } from 'react';
import React from 'react';
import type { AnnotationRevision } from '@zerna/sdk';
import AnnotationViewer from './AnnotationViewer';
import type { CellAnnotation } from './AnnotationViewer';
import { formatDateTime } from '../../lib/dates';
import type { Embedding } from '../../lib/embedding-types';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface AnnotationEditorProps {
  runId: string;
  embedding: Embedding;
  revisions: AnnotationRevision[];
  currentRevision: AnnotationRevision | null;
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** Called after a new revision is successfully created. */
  onRevisionCreated?: (revision: AnnotationRevision) => void;
  /** Async function that calls POST /v1/runs/{id}/annotations */
  createRevision: (
    runId: string,
    annotations: Record<string, unknown>
  ) => Promise<AnnotationRevision>;
}

interface HierarchicalLabel {
  tissue: string;
  lineage: string;
  cell_type: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

// ── Component ─────────────────────────────────────────────────────────────────

export default function AnnotationEditor({
  runId,
  embedding,
  revisions,
  currentRevision,
  isLoading = false,
  error = null,
  onRetry,
  onRevisionCreated,
  createRevision,
}: AnnotationEditorProps) {
  const [selectedCells, setSelectedCells] = useState<Map<string, CellAnnotation | null>>(new Map());
  const [label, setLabel] = useState<HierarchicalLabel>({
    tissue: '',
    lineage: '',
    cell_type: '',
  });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const handleCellSelect = useCallback((cellId: string, annotation: CellAnnotation | null) => {
    setSelectedCells((prev) => {
      const next = new Map(prev);
      if (next.has(cellId)) {
        next.delete(cellId);
      } else {
        next.set(cellId, annotation);
      }
      return next;
    });
  }, []);

  const canSave =
    selectedCells.size > 0 &&
    label.tissue.trim() !== '' &&
    label.lineage.trim() !== '' &&
    label.cell_type.trim() !== '';

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    setSaveError(null);

    // Build annotations: merge existing + overrides for selected cells
    const base: Record<string, unknown> = currentRevision ? { ...currentRevision.annotations } : {};

    for (const cellId of selectedCells.keys()) {
      base[cellId] = {
        tissue: label.tissue.trim(),
        lineage: label.lineage.trim(),
        cell_type: label.cell_type.trim(),
        confidence: 1.0,
      };
    }

    try {
      const newRevision = await createRevision(runId, base);
      setSelectedCells(new Map());
      setLabel({ tissue: '', lineage: '', cell_type: '' });
      onRevisionCreated?.(newRevision);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save revision');
    } finally {
      setSaving(false);
    }
  };

  const sortedRevisions = [...revisions].sort((a, b) => b.revision_number - a.revision_number);

  return (
    <div className="space-y-4" data-testid="annotation-editor">
      {/* Embedding viewer */}
      <AnnotationViewer
        embedding={embedding}
        revision={currentRevision}
        isLoading={isLoading}
        error={error}
        onRetry={onRetry}
        onCellSelect={handleCellSelect}
      />

      {/* Edit panel */}
      {!isLoading && !error && (
        <div className="card p-4 space-y-4">
          <h2 className="text-sm font-semibold text-gray-700">
            Re-annotate selected cells
            {selectedCells.size > 0 && (
              <span className="ml-2 text-blue-600">({selectedCells.size} selected)</span>
            )}
          </h2>

          {/* Hierarchical label selectors */}
          <div className="grid grid-cols-3 gap-3" data-testid="label-selectors">
            <div>
              <label htmlFor="tissue-input" className="block text-xs text-gray-500 mb-1">
                Tissue
              </label>
              <input
                id="tissue-input"
                type="text"
                value={label.tissue}
                onChange={(e) => setLabel((l) => ({ ...l, tissue: e.target.value }))}
                placeholder="e.g. blood"
                className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                data-testid="tissue-input"
              />
            </div>
            <div>
              <label htmlFor="lineage-input" className="block text-xs text-gray-500 mb-1">
                Lineage
              </label>
              <input
                id="lineage-input"
                type="text"
                value={label.lineage}
                onChange={(e) => setLabel((l) => ({ ...l, lineage: e.target.value }))}
                placeholder="e.g. myeloid"
                className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                data-testid="lineage-input"
              />
            </div>
            <div>
              <label htmlFor="cell-type-input" className="block text-xs text-gray-500 mb-1">
                Cell type
              </label>
              <input
                id="cell-type-input"
                type="text"
                value={label.cell_type}
                onChange={(e) => setLabel((l) => ({ ...l, cell_type: e.target.value }))}
                placeholder="e.g. monocyte"
                className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                data-testid="cell-type-input"
              />
            </div>
          </div>

          {saveError && (
            <p className="text-sm text-red-600" data-testid="save-error">
              {saveError}
            </p>
          )}

          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                void handleSave();
              }}
              disabled={!canSave || saving}
              data-testid="save-btn"
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? 'Saving…' : 'Save revision'}
            </button>
            {selectedCells.size > 0 && (
              <button
                onClick={() => setSelectedCells(new Map())}
                className="text-sm text-gray-500 hover:text-gray-700"
              >
                Clear selection
              </button>
            )}
          </div>
        </div>
      )}

      {/* Revision history */}
      {sortedRevisions.length > 0 && (
        <div className="card p-4" data-testid="revision-history">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Revision history</h2>
          <ul className="divide-y divide-gray-100">
            {sortedRevisions.map((rev) => (
              <li
                key={rev.id}
                className="py-3 flex items-center justify-between text-sm"
                data-testid={`revision-item-${rev.revision_number}`}
              >
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-900">
                      Revision #{rev.revision_number}
                    </span>
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {rev.method ?? 'unknown'}
                    </span>
                    {rev.approved_at && (
                      <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-700">
                        Approved
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400">{formatDateTime(rev.created_at)}</p>
                </div>
                <span className="text-xs text-gray-400 font-mono">
                  {Object.keys(rev.annotations).length} cells
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
