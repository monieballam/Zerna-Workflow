'use client';

import type { ReactNode } from 'react';
import type { ExplorerHierarchyFilterAxes } from '@/lib/explorer-field-metadata';
import ActiveCohortBanner from './ActiveCohortBanner';
import ExplorerFilterGroups from './ExplorerFilterGroups';

export default function ExploreCellsWorkspace({
  totalCellsInRun,
  sampled,
  visibleCells,
  filterFields,
  advancedFilterFields = [],
  cohortFilterFields,
  filterValues,
  hierarchyFilterAxes,
  hierarchyAxesPopulated = false,
  activeFilters,
  clusterFilterLabels,
  onToggleFilter,
  onClearFilter,
  onClearAllFilters,
  focusLabel,
  onClearFocus,
  geneOverlayGene,
  onClearGeneOverlay,
  toolbar,
  embeddingContext,
  children,
}: {
  totalCellsInRun: number;
  sampled: boolean;
  visibleCells: number;
  filterFields: string[];
  advancedFilterFields?: string[];
  /** Primary + advanced filter keys (cohort chips iterate this list). */
  cohortFilterFields: string[];
  filterValues: Record<string, string[]>;
  /** Full-obs co-occurrence axes (L2 per L1, L3 per L1|L2) for branch-aware filter choices. */
  hierarchyFilterAxes?: ExplorerHierarchyFilterAxes;
  /** True when API sent non-empty ``hierarchy_filter_axes`` (used for lineage filter hint copy). */
  hierarchyAxesPopulated?: boolean;
  activeFilters: Record<string, Set<string>>;
  clusterFilterLabels: Map<string, string>;
  onToggleFilter: (field: string, value: string) => void;
  onClearFilter: (field: string) => void;
  onClearAllFilters: () => void;
  focusLabel: string | null;
  onClearFocus: () => void;
  geneOverlayGene?: string | null;
  onClearGeneOverlay?: () => void;
  /** Gene row, split, color-by, label mode — primary embedding controls. */
  toolbar: ReactNode;
  /** State strip directly above the plot (coloring / focus / cluster). */
  embeddingContext: ReactNode;
  /** Embedding canvas + bottom legend. */
  children: ReactNode;
}) {
  return (
    <section
      className="card overflow-hidden border-gray-200 shadow-sm"
      data-testid="explore-cells-workspace"
    >
      <div className="border-b border-gray-100 bg-gray-50/50 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Explore cells</h2>
            <p className="mt-0.5 text-xs text-gray-500">
              Define a subset with filters, pick embedding coordinates above, then inspect clusters
              below.
            </p>
          </div>
        </div>
        <div className="mt-3">
          <ActiveCohortBanner
            visibleCells={visibleCells}
            totalCellsInRun={totalCellsInRun}
            sampled={sampled}
            filterFields={cohortFilterFields}
            activeFilters={activeFilters}
            onToggleFilter={onToggleFilter}
            onClearAllFilters={onClearAllFilters}
            focusLabel={focusLabel}
            onClearFocus={onClearFocus}
            geneOverlayGene={geneOverlayGene}
            onClearGeneOverlay={onClearGeneOverlay}
          />
        </div>
      </div>

      <div className="space-y-4 p-4">
        <div>
          <h3 className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
            Filters
          </h3>
          <div className="mt-2">
            {filterFields.length === 0 && advancedFilterFields.length === 0 ? (
              <p className="text-sm text-gray-400">No filterable metadata in this run.</p>
            ) : (
              <ExplorerFilterGroups
                filterFields={filterFields}
                advancedFilterFields={advancedFilterFields}
                filterValues={filterValues}
                hierarchyFilterAxes={hierarchyFilterAxes}
                hierarchyAxesPopulated={hierarchyAxesPopulated}
                activeFilters={activeFilters}
                clusterFilterLabels={clusterFilterLabels}
                onToggle={onToggleFilter}
                onClear={onClearFilter}
              />
            )}
          </div>
        </div>

        <div className="rounded-lg border border-gray-100 bg-white p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
            Embedding
          </p>
          <div className="mt-3">{toolbar}</div>
        </div>

        <div className="space-y-2 rounded-lg border border-gray-200 bg-gray-50/30 p-2">
          {embeddingContext}
          {children}
        </div>
      </div>
    </section>
  );
}
