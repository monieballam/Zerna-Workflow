'use client';

import React, { useRef, useState } from 'react';
import EmbeddingViewer from './EmbeddingViewer';
import type { EmbeddingRenderer } from '@/lib/embedding-renderer';
import type { Embedding, CellMetadata } from '@/lib/embedding-types';

export interface EmbeddingEntry {
  label: string;
  embedding: Embedding;
  metadata: CellMetadata[];
  availableFields: string[];
  continuousFields?: string[];
  fieldRanges?: Record<string, { min: number; max: number }>;
}

export interface EmbeddingComparisonProps {
  entries: EmbeddingEntry[];
  syncViewports?: boolean;
  activeColorField?: string;
  onActiveColorFieldChange?: (field: string) => void;
  formatCategoryLegendLabel?: (field: string, rawValue: string) => string;
  formatCentroidLabel?: (field: string, rawValue: string) => string;
  formatMetadataDisplayValue?: (field: string, rawValue: string) => string;
  labelMode?: 'none' | 'cluster' | 'cellType';
  onLabelModeChange?: (mode: 'none' | 'cluster' | 'cellType') => void;
  focusCategory?: { field: string; rawValue: string } | null;
  legendHoverRaw?: string | null;
  hideInternalLegend?: boolean;
  compactToolbar?: boolean;
}

export default function EmbeddingComparison({
  entries,
  syncViewports: initialSync = true,
  activeColorField,
  onActiveColorFieldChange,
  formatCategoryLegendLabel,
  formatCentroidLabel,
  formatMetadataDisplayValue,
  labelMode,
  onLabelModeChange,
  focusCategory,
  legendHoverRaw,
  hideInternalLegend,
  compactToolbar,
}: EmbeddingComparisonProps) {
  const [syncEnabled, setSyncEnabled] = useState(initialSync);

  // One ref per entry — created unconditionally (rules of hooks)
  const rendererRefs = useRef<Array<React.RefObject<EmbeddingRenderer | null>>>(
    entries.map(() => React.createRef<EmbeddingRenderer | null>())
  );

  // Ensure we always have enough refs if entries grow
  while (rendererRefs.current.length < entries.length) {
    rendererRefs.current.push(React.createRef<EmbeddingRenderer | null>());
  }

  const handleReset = () => {
    if (!syncEnabled) return;
    rendererRefs.current.forEach((ref) => ref.current?.zoomToFit());
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Sync toggle */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setSyncEnabled((v) => !v)}
          className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
            syncEnabled
              ? 'border-blue-500 bg-blue-50 text-blue-700'
              : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
          }`}
          aria-pressed={syncEnabled}
        >
          {syncEnabled ? 'Sync viewports: on' : 'Sync viewports: off'}
        </button>
        {syncEnabled && (
          <button
            onClick={handleReset}
            className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          >
            Reset all views
          </button>
        )}
      </div>

      {/* Panels grid */}
      <div
        className="grid gap-4"
        style={{ gridTemplateColumns: `repeat(${Math.min(entries.length, 2)}, 1fr)` }}
      >
        {entries.map((entry, i) => (
          <div key={i} className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold text-gray-700">{entry.label}</h3>
            <EmbeddingViewer
              embedding={entry.embedding}
              metadata={entry.metadata}
              availableFields={entry.availableFields}
              continuousFields={entry.continuousFields}
              fieldRanges={entry.fieldRanges}
              rendererRef={rendererRefs.current[i]}
              activeColorField={activeColorField}
              onActiveColorFieldChange={onActiveColorFieldChange}
              formatCategoryLegendLabel={formatCategoryLegendLabel}
              formatCentroidLabel={formatCentroidLabel}
              formatMetadataDisplayValue={formatMetadataDisplayValue}
              labelMode={labelMode}
              onLabelModeChange={onLabelModeChange}
              focusCategory={focusCategory}
              legendHoverRaw={legendHoverRaw}
              hideInternalLegend={hideInternalLegend}
              compactToolbar={compactToolbar}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
