'use client';

import { useMemo } from 'react';
import {
  EXPLORER_FILTER_FIELD_HELP,
  type ExplorerHierarchyFilterAxes,
  formatExplorerFieldLabel,
  hierarchyAxesArePopulated,
  hierarchyScopedLevel2Values,
  hierarchyScopedLevel3Values,
  sortExplorerFieldsForUi,
} from '@/lib/explorer-field-metadata';

/** Matches ``_EXPLORER_PRIMARY_FILTER_FIELD_KEYS`` in ``run_explorer_service.py``. */
const PRIMARY_FIELD_ORDER = [
  'lineage',
  'sample',
  'condition',
  'batch',
  'patient',
  'tissue',
  'confidenceBucket',
] as const;

/** Advanced filters: readable summary, merged debug, raw engine, technical partitions. */
const ADVANCED_DIAGNOSTIC_ORDER = [
  'displayLabel',
  'cellType',
  'rawAnnotationLabel',
  'level2',
  'level3',
  'cluster',
  'globalCluster',
  'lineageSubcluster',
  'fineSubcluster',
] as const;

const ADVANCED_DIAGNOSTIC_SET = new Set<string>(ADVANCED_DIAGNOSTIC_ORDER);

function filterHelp(field: string): string | undefined {
  return EXPLORER_FILTER_FIELD_HELP[field];
}

function FilterPanel({
  field,
  values,
  activeValues,
  helpText,
  getValueLabel,
  onToggle,
  onClear,
}: {
  field: string;
  values: string[];
  activeValues: Set<string>;
  helpText?: string;
  getValueLabel?: (value: string) => string;
  onToggle: (value: string) => void;
  onClear: () => void;
}) {
  const n = values.length;
  const sel = activeValues.size;
  const label = (v: string) => (getValueLabel ? getValueLabel(v) : v);

  return (
    <details
      className="group rounded-md border border-gray-100 bg-white/90"
      data-testid={`explorer-filter-group-${field}`}
    >
      <summary className="cursor-pointer list-none px-2 py-1.5 [&::-webkit-details-marker]:hidden">
        <div className="flex items-center gap-2">
          <span
            className="text-[10px] text-gray-400 transition-transform group-open:rotate-90"
            aria-hidden
          >
            ▸
          </span>
          <span className="min-w-0 flex-1 text-sm font-medium leading-tight text-gray-800">
            {formatExplorerFieldLabel(field)}
          </span>
          <span className="shrink-0 tabular-nums text-[11px] text-gray-500">
            {n} values
            {sel > 0 ? ` · ${sel} on` : ''}
          </span>
        </div>
        {sel > 0 ? (
          <div
            className="mt-1.5 flex flex-wrap gap-1 pl-5"
            onClick={(e) => {
              e.preventDefault();
            }}
          >
            {[...activeValues].map((value) => (
              <button
                key={value}
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  e.preventDefault();
                  onToggle(value);
                }}
                className="inline-flex max-w-[min(100%,14rem)] items-center gap-0.5 rounded-full border border-blue-200 bg-blue-50/90 px-2 py-0.5 text-[11px] font-medium text-blue-900 hover:bg-blue-100"
                title="Remove filter"
              >
                <span className="truncate">{label(value)}</span>
                <span className="text-blue-600">×</span>
              </button>
            ))}
          </div>
        ) : null}
      </summary>

      <div className="space-y-2 border-t border-gray-100 px-2 pb-2 pt-1.5">
        {helpText ? <p className="text-[11px] leading-snug text-gray-500">{helpText}</p> : null}
        <div className="flex items-center justify-end gap-2">
          {sel > 0 ? (
            <button
              onClick={onClear}
              className="text-[11px] font-medium text-blue-600 hover:text-blue-800"
              type="button"
            >
              Clear group
            </button>
          ) : null}
        </div>

        <div className="max-h-36 space-y-0.5 overflow-y-auto pr-1">
          {values.map((value) => (
            <label
              key={value}
              className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-sm hover:bg-gray-50"
            >
              <input
                checked={activeValues.has(value)}
                onChange={() => onToggle(value)}
                type="checkbox"
                className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="truncate text-gray-700" title={label(value)}>
                {label(value)}
              </span>
            </label>
          ))}
        </div>
      </div>
    </details>
  );
}

function renderFilterPanel(
  field: string,
  props: {
    filterValues: Record<string, string[]>;
    activeFilters: Record<string, Set<string>>;
    clusterFilterLabels: Map<string, string>;
    onToggle: (field: string, value: string) => void;
    onClear: (field: string) => void;
    valuesOverride?: string[];
  }
) {
  const { filterValues, activeFilters, clusterFilterLabels, onToggle, onClear, valuesOverride } =
    props;
  return (
    <FilterPanel
      key={field}
      field={field}
      values={valuesOverride ?? filterValues[field] ?? []}
      activeValues={activeFilters[field] ?? new Set<string>()}
      helpText={filterHelp(field)}
      getValueLabel={
        field === 'cluster'
          ? (value) => clusterFilterLabels.get(value) ?? `Cluster ${value}`
          : undefined
      }
      onToggle={(value) => onToggle(field, value)}
      onClear={() => onClear(field)}
    />
  );
}

export default function ExplorerFilterGroups({
  filterFields,
  advancedFilterFields = [],
  filterValues,
  hierarchyFilterAxes,
  hierarchyAxesPopulated = false,
  activeFilters,
  clusterFilterLabels,
  onToggle,
  onClear,
}: {
  filterFields: string[];
  advancedFilterFields?: string[];
  filterValues: Record<string, string[]>;
  hierarchyFilterAxes?: ExplorerHierarchyFilterAxes;
  hierarchyAxesPopulated?: boolean;
  activeFilters: Record<string, Set<string>>;
  clusterFilterLabels: Map<string, string>;
  onToggle: (field: string, value: string) => void;
  onClear: (field: string) => void;
}) {
  const presentPrimary = new Set(filterFields);
  const presentAdv = new Set(advancedFilterFields);

  const primaryFields = PRIMARY_FIELD_ORDER.filter((f) => presentPrimary.has(f));

  const biologyPrimary = primaryFields.filter((f) => f === 'lineage');
  const studyPrimary = primaryFields.filter(
    (f) =>
      f === 'sample' ||
      f === 'condition' ||
      f === 'batch' ||
      f === 'patient' ||
      f === 'tissue' ||
      f === 'confidenceBucket'
  );

  const advancedDiagnosticFields = ADVANCED_DIAGNOSTIC_ORDER.filter((f) => presentAdv.has(f));

  const otherFields = sortExplorerFieldsForUi(
    advancedFilterFields.filter((f) => !ADVANCED_DIAGNOSTIC_SET.has(f))
  );

  const level2BranchScoped = useMemo(() => {
    const all = filterValues.level2;
    if (!hierarchyFilterAxes || !hierarchyAxesArePopulated(hierarchyFilterAxes)) {
      return all ?? [];
    }
    return hierarchyScopedLevel2Values(
      hierarchyFilterAxes,
      all,
      activeFilters.lineage ?? new Set()
    );
  }, [hierarchyFilterAxes, filterValues.level2, activeFilters.lineage]);

  const level3BranchScoped = useMemo(() => {
    const all = filterValues.level3;
    if (!hierarchyFilterAxes || !hierarchyAxesArePopulated(hierarchyFilterAxes)) {
      return all ?? [];
    }
    return hierarchyScopedLevel3Values(
      hierarchyFilterAxes,
      all,
      activeFilters.lineage ?? new Set(),
      activeFilters.level2 ?? new Set()
    );
  }, [
    hierarchyFilterAxes,
    filterValues.level3,
    activeFilters.lineage,
    activeFilters.level2,
  ]);

  const panelProps = { filterValues, activeFilters, clusterFilterLabels, onToggle, onClear };

  const hasPrimary = biologyPrimary.length > 0 || studyPrimary.length > 0;
  const hasAdvancedBlock = advancedDiagnosticFields.length > 0 || otherFields.length > 0;

  if (!hasPrimary && !hasAdvancedBlock) {
    return (
      <p className="text-sm text-gray-400">No filterable metadata was found in the saved run.</p>
    );
  }

  return (
    <div className="space-y-1.5" data-testid="explorer-filter-groups">
      {hasPrimary ? (
        <div className="space-y-1.5 rounded-lg border border-gray-100/80 bg-gray-50/40 p-2">
          {hierarchyAxesPopulated && biologyPrimary.length > 0 ? (
            <p className="px-0.5 text-[11px] leading-snug text-gray-500">
              Broad lineage here first. On canonical runs, major type (Advanced → auto_level2) and
              fine subtype (Advanced → structural auto_level3) cohort choices are lineage- and
              branch-scoped so incompatible combinations do not appear. Use View by for coloring.
              One lineage + one major unlocks fine-branch embeddings. Partitions and merged cellType
              / rawAnnotationLabel stay under Advanced.
            </p>
          ) : null}
          {biologyPrimary.length > 0 ? (
            <div className="space-y-1">
              {biologyPrimary.map((field) => renderFilterPanel(field, panelProps))}
            </div>
          ) : null}

          {studyPrimary.length > 0 ? (
            <div className="space-y-1">
              {studyPrimary.map((field) => renderFilterPanel(field, panelProps))}
            </div>
          ) : null}
        </div>
      ) : null}

      {hasAdvancedBlock ? (
        <details className="rounded-lg border border-dashed border-gray-200 bg-gray-50/50 p-1.5">
          <summary className="cursor-pointer list-none px-1.5 py-1 text-sm font-medium text-gray-700 [&::-webkit-details-marker]:hidden">
            <span className="flex items-center justify-between gap-2">
              <span>
                Advanced: final_display summary, debug merged cell type, raw Zerna, Leiden / P2 / P3
                partitions
              </span>
              <span className="text-xs font-normal text-gray-500">
                {advancedDiagnosticFields.length + otherFields.length} fields
              </span>
            </span>
          </summary>

          <div className="mt-1.5 space-y-1 border-t border-gray-200/80 pt-1.5">
            {advancedDiagnosticFields.length > 0 ? (
              <div className="space-y-1">
                {advancedDiagnosticFields.map((field) =>
                  renderFilterPanel(field, {
                    ...panelProps,
                    ...(field === 'level2'
                      ? { valuesOverride: level2BranchScoped }
                      : field === 'level3'
                        ? { valuesOverride: level3BranchScoped }
                        : {}),
                  })
                )}
              </div>
            ) : null}

            {otherFields.length > 0 ? (
              <div className="space-y-1">
                {otherFields.map((field) => renderFilterPanel(field, panelProps))}
              </div>
            ) : null}
          </div>
        </details>
      ) : null}
    </div>
  );
}
