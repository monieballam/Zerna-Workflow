'use client';

import { useEffect, useMemo, useState } from 'react';
import type { CellMetadata } from '@/lib/embedding-types';
import {
  buildCompositionRows,
  computeBiologicalHighlights,
  defaultCompositionGrouping,
  orderedCategories,
  resolveGranularityField,
  topPopulations,
  type CompositionGranularity,
  type CompositionGrouping,
  type CompositionMetric,
} from '@/lib/run-composition';
import BiologicalSummaryCard from './BiologicalSummaryCard';
import { formatLevel3ExplorerGroupLabelForUi } from '@/lib/explorer-biology-display';
import RunCompositionChart, { CompositionLegend } from './RunCompositionChart';

const GRANULARITY_OPTIONS: Array<{ id: CompositionGranularity; label: string }> = [
  { id: 'broad', label: 'Broad' },
  { id: 'major', label: 'Major' },
  { id: 'fine', label: 'Fine' },
];

const METRIC_OPTIONS: Array<{ id: CompositionMetric; label: string }> = [
  { id: 'count', label: 'Count' },
  { id: 'percent', label: 'Percent' },
];

function ToggleGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: Array<{ id: T; label: string }>;
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
        {label}
      </span>
      <div className="inline-flex rounded-md border border-gray-200 bg-white p-0.5">
        {options.map((opt) => {
          const active = opt.id === value;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => onChange(opt.id)}
              className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                active ? 'bg-blue-600 text-white shadow-sm' : 'text-gray-600 hover:bg-gray-50'
              }`}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function RunCompositionOverview({
  metadata,
  availableFields,
  nSamples,
  nConditions,
  onCompositionCategoryFocus,
}: {
  metadata: CellMetadata[];
  availableFields: string[];
  nSamples: number | null;
  nConditions: number | null;
  /** Map composition chart segment → UMAP focus (uses current granularity field). */
  onCompositionCategoryFocus?: (payload: { field: string; category: string }) => void;
}) {
  const fieldSet = useMemo(() => new Set(availableFields), [availableFields]);

  const groupingOptions = useMemo(() => {
    const opts: Array<{ id: CompositionGrouping; label: string }> = [];
    if (fieldSet.has('condition')) {
      opts.push({ id: 'condition', label: 'By condition' });
    }
    if (fieldSet.has('sample')) {
      opts.push({ id: 'sample', label: 'By sample' });
    }
    opts.push({ id: 'overall', label: 'Overall' });
    return opts;
  }, [fieldSet]);

  const autoGrouping = useMemo(
    () => defaultCompositionGrouping(metadata, fieldSet),
    [metadata, fieldSet]
  );

  /** Default to broad (lineage) to match global explorer “View by” default (auto_level1). */
  const [granularity, setGranularity] = useState<CompositionGranularity>('broad');
  const [metric, setMetric] = useState<CompositionMetric>('percent');
  const [grouping, setGrouping] = useState<CompositionGrouping>(autoGrouping);

  useEffect(() => {
    if (!groupingOptions.some((o) => o.id === grouping)) {
      setGrouping(groupingOptions[groupingOptions.length - 1]?.id ?? 'overall');
    }
  }, [grouping, groupingOptions]);

  const granularityField = useMemo(
    () => resolveGranularityField(metadata, fieldSet, granularity),
    [metadata, fieldSet, granularity]
  );

  const rows = useMemo(
    () => buildCompositionRows(metadata, grouping, granularityField),
    [metadata, grouping, granularityField]
  );

  const categoryOrder = useMemo(() => orderedCategories(rows), [rows]);

  const fineLevel3LabelFormat = useMemo(
    () =>
      granularityField === 'level3'
        ? (key: string) => formatLevel3ExplorerGroupLabelForUi(key)
        : undefined,
    [granularityField]
  );

  const variant: 'stacked' | 'category-bars' = grouping === 'overall' ? 'category-bars' : 'stacked';

  const highlights = useMemo(
    () => computeBiologicalHighlights(metadata, fieldSet),
    [metadata, fieldSet]
  );

  const top5 = useMemo(
    () => topPopulations(metadata, granularityField, 5),
    [metadata, granularityField]
  );

  return (
    <section
      className="card p-4"
      aria-labelledby="cell-composition-heading"
      data-testid="run-composition-overview"
    >
      <div className="flex flex-col gap-2 border-b border-gray-100 pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <h2 id="cell-composition-heading" className="text-base font-semibold text-gray-900">
            Cell Composition
          </h2>
          <p className="mt-1 max-w-xl text-xs text-gray-500">
            Reflects the same cohort as the UMAP and legend: active Explore cells filters subset
            these totals.
          </p>
        </div>
        <div className="flex flex-col gap-3 lg:items-end">
          <ToggleGroup
            label="Granularity"
            options={GRANULARITY_OPTIONS}
            value={granularity}
            onChange={setGranularity}
          />
          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center lg:justify-end">
            <ToggleGroup
              label="Metric"
              options={METRIC_OPTIONS}
              value={metric}
              onChange={setMetric}
            />
            <ToggleGroup
              label="Grouping"
              options={groupingOptions}
              value={grouping}
              onChange={setGrouping}
            />
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)]">
        <div className="min-w-0">
          <RunCompositionChart
            rows={rows}
            categoryOrder={categoryOrder}
            metric={metric}
            variant={variant}
            formatCategoryLabel={fineLevel3LabelFormat}
            onCategoryClick={
              onCompositionCategoryFocus && granularityField
                ? (category) => onCompositionCategoryFocus({ field: granularityField, category })
                : undefined
            }
          />
          <CompositionLegend
            categories={categoryOrder}
            formatCategoryLabel={fineLevel3LabelFormat}
          />
        </div>
        <BiologicalSummaryCard
          highlights={highlights}
          nSamples={nSamples}
          nConditions={nConditions}
          topPopulations={top5}
        />
      </div>
    </section>
  );
}
