'use client';

import type { FormEvent, ReactNode } from 'react';
import { formatExplorerFieldLabel } from '@/lib/explorer-field-metadata';

export default function EmbeddingExplorerCard({
  splitField,
  splitFieldOptions,
  onSplitFieldChange,
  geneInput,
  onGeneInputChange,
  onGeneSubmit,
  geneLoading,
  geneError,
  geneOverlayGene,
  onClearGene,
  visibleCells,
  children,
}: {
  splitField: string;
  splitFieldOptions: string[];
  onSplitFieldChange: (field: string) => void;
  geneInput: string;
  onGeneInputChange: (value: string) => void;
  onGeneSubmit: (event: FormEvent<HTMLFormElement>) => void;
  geneLoading: boolean;
  geneError: string | null;
  geneOverlayGene: string | null;
  onClearGene: () => void;
  visibleCells: number;
  children: ReactNode;
}) {
  return (
    <div className="card p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-gray-800">Embedding Explorer</h2>
            <button
              type="button"
              className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-gray-200 text-[10px] font-bold text-gray-500 hover:bg-gray-50"
              title="Global: View by Broad + Major (auto_level1–2); fine subtype (auto_level3) and final_display are under Advanced. Lineage / fine views: View by Major + Fine. Overlay a gene, lasso cells, split by sample or condition. Partition IDs, clusters, merged cellType, and rawAnnotationLabel stay under Advanced."
              aria-label="Embedding explorer help"
            >
              ?
            </button>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            Explore cells by annotation, metadata, or gene expression.
          </p>
        </div>
        <span className="shrink-0 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium tabular-nums text-gray-600">
          {visibleCells.toLocaleString()} visible cells
        </span>
      </div>

      <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-end">
        <label className="flex min-w-[10rem] flex-1 flex-col gap-1 lg:max-w-[14rem]">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
            Split view
          </span>
          <select
            value={splitField}
            onChange={(event) => onSplitFieldChange(event.target.value)}
            className="w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700"
          >
            <option value="">Single panel</option>
            {splitFieldOptions.map((field) => (
              <option key={field} value={field}>
                {formatExplorerFieldLabel(field)}
              </option>
            ))}
          </select>
        </label>

        <form onSubmit={onGeneSubmit} className="flex min-w-0 flex-[2] flex-col gap-1">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
            Gene overlay
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={geneInput}
              onChange={(event) => onGeneInputChange(event.target.value)}
              placeholder="Gene, e.g. EPCAM"
              className="min-w-0 flex-1 rounded-md border border-gray-300 px-2 py-1.5 text-sm text-gray-700"
            />
            <button
              type="submit"
              disabled={geneLoading || geneInput.trim().length === 0}
              className="rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-700 transition-colors hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {geneLoading ? '…' : 'Plot'}
            </button>
            {geneOverlayGene && (
              <button
                type="button"
                onClick={onClearGene}
                className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Reset
              </button>
            )}
          </div>
          {geneError && <p className="text-xs text-red-600">{geneError}</p>}
          {!geneError && geneOverlayGene && (
            <p className="text-xs text-gray-500">
              Overlaying <span className="font-mono text-gray-700">{geneOverlayGene}</span>.
            </p>
          )}
        </form>
      </div>

      {children}
    </div>
  );
}
