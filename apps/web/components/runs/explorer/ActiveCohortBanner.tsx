'use client';

import { formatExplorerFieldLabel } from '@/lib/explorer-field-metadata';

export default function ActiveCohortBanner({
  visibleCells,
  totalCellsInRun,
  sampled,
  filterFields,
  activeFilters,
  onToggleFilter,
  onClearAllFilters,
  focusLabel,
  onClearFocus,
  geneOverlayGene,
  onClearGeneOverlay,
}: {
  visibleCells: number;
  /** Total cells represented by this run (denominator when sampled). */
  totalCellsInRun: number;
  sampled: boolean;
  filterFields: string[];
  activeFilters: Record<string, Set<string>>;
  onToggleFilter: (field: string, value: string) => void;
  onClearAllFilters: () => void;
  focusLabel: string | null;
  onClearFocus: () => void;
  geneOverlayGene?: string | null;
  onClearGeneOverlay?: () => void;
}) {
  const chips: Array<{ field: string; value: string }> = [];
  for (const field of filterFields) {
    const set = activeFilters[field];
    if (!set || set.size === 0) continue;
    for (const value of set) {
      chips.push({ field, value });
    }
  }

  const hasFilters = chips.length > 0;

  const countLine = sampled
    ? `${visibleCells.toLocaleString()} cells shown · ${totalCellsInRun.toLocaleString()} in run`
    : `${visibleCells.toLocaleString()} cells in view`;

  return (
    <div
      className="rounded-xl border border-blue-200/80 bg-gradient-to-br from-blue-50/95 via-white to-white px-3 py-2.5 shadow-sm ring-1 ring-blue-100/60"
      data-testid="active-cohort-banner"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="text-[11px] font-bold uppercase tracking-wide text-blue-900/80">
            Active cohort
          </span>
          <span
            className="rounded-md bg-white px-2 py-0.5 text-xs font-semibold tabular-nums text-gray-900 shadow-sm ring-1 ring-gray-200/90"
            title={sampled ? 'Subset shown in explorer vs total persisted for this run' : undefined}
          >
            {countLine}
          </span>
          {geneOverlayGene ? (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-indigo-300 bg-indigo-50 px-2 py-0.5 text-[11px] font-semibold text-indigo-950 shadow-sm"
              data-testid="banner-gene-chip"
            >
              Gene · <span className="font-mono">{geneOverlayGene}</span>
              {onClearGeneOverlay ? (
                <button
                  type="button"
                  onClick={onClearGeneOverlay}
                  className="rounded-full px-0.5 text-indigo-700 hover:bg-indigo-100"
                  title="Clear gene overlay"
                >
                  ×
                </button>
              ) : null}
            </span>
          ) : null}
          {focusLabel ? (
            <span
              className="inline-flex items-center gap-1 rounded-full border-2 border-amber-400 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-950 shadow-sm"
              data-testid="focus-chip"
            >
              Focus · {focusLabel}
              <button
                type="button"
                onClick={onClearFocus}
                className="rounded-full px-0.5 text-amber-900 hover:bg-amber-100"
                title="Clear focus"
              >
                ×
              </button>
            </span>
          ) : null}
        </div>

        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          {chips.map(({ field, value }) => (
            <button
              key={`${field}:${value}`}
              type="button"
              onClick={() => onToggleFilter(field, value)}
              className="inline-flex max-w-[14rem] items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-800 shadow-sm hover:border-blue-300 hover:bg-blue-50/80"
              title="Remove filter"
              data-testid="banner-filter-chip"
            >
              <span className="text-slate-500">{formatExplorerFieldLabel(field)}:</span>
              <span className="truncate font-semibold">{value}</span>
              <span className="text-slate-400">×</span>
            </button>
          ))}
          {hasFilters ? (
            <button
              type="button"
              onClick={onClearAllFilters}
              className="rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-semibold text-blue-800 shadow-sm hover:bg-blue-50"
              data-testid="clear-all-filters"
            >
              Clear filters
            </button>
          ) : null}
          {focusLabel ? (
            <button
              type="button"
              onClick={onClearFocus}
              className="rounded-md border border-amber-300 bg-amber-50/80 px-2 py-0.5 text-[11px] font-semibold text-amber-950 hover:bg-amber-100"
              data-testid="clear-focus"
            >
              Clear focus
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
