'use client';

import { useMemo } from 'react';
import type { CompositionMetric, CompositionRow } from '@/lib/run-composition';

const PALETTE = [
  '#2563eb',
  '#16a34a',
  '#d97706',
  '#dc2626',
  '#7c3aed',
  '#0891b2',
  '#c026d3',
  '#ca8a04',
  '#4f46e5',
  '#059669',
  '#ea580c',
  '#be185d',
];

function categoryColorMap(categories: string[]): Map<string, string> {
  const map = new Map<string, string>();
  categories.forEach((cat, i) => {
    map.set(cat, PALETTE[i % PALETTE.length]);
  });
  return map;
}

function formatBarLabel(
  metric: CompositionMetric,
  count: number,
  rowTotal: number,
  datasetTotal: number
): string {
  if (metric === 'count') {
    return count.toLocaleString();
  }
  const denom = rowTotal > 0 ? rowTotal : datasetTotal;
  const pct = denom > 0 ? (count / denom) * 100 : 0;
  return `${pct.toFixed(1)}%`;
}

export default function RunCompositionChart({
  rows,
  categoryOrder,
  metric,
  variant,
  onCategoryClick,
  formatCategoryLabel,
}: {
  rows: CompositionRow[];
  categoryOrder: string[];
  metric: CompositionMetric;
  variant: 'stacked' | 'category-bars';
  /** Focus embedding on this category (same field as current composition granularity). */
  onCategoryClick?: (category: string) => void;
  /** Display string for segment keys (e.g. fine mode: hide ``__no_fine__|…`` prefix). Raw key is still used for focus. */
  formatCategoryLabel?: (categoryKey: string) => string;
}) {
  const labelFor = (key: string) => (formatCategoryLabel ? formatCategoryLabel(key) : key);
  const colors = useMemo(() => categoryColorMap(categoryOrder), [categoryOrder]);

  const datasetTotal = useMemo(() => {
    if (variant === 'category-bars' && rows[0]) return rows[0].total;
    return rows.reduce((acc, r) => acc + r.total, 0);
  }, [rows, variant]);

  if (rows.length === 0 || categoryOrder.length === 0) {
    return (
      <div className="flex min-h-48 items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50/50 text-sm text-gray-500">
        Not enough annotation fields to chart composition for this selection.
      </div>
    );
  }

  if (variant === 'category-bars') {
    const row = rows[0];
    if (!row || row.segments.length === 0) {
      return (
        <div className="flex min-h-48 items-center justify-center rounded-lg border border-dashed border-gray-200 text-sm text-gray-500">
          No categories to display.
        </div>
      );
    }
    const maxCount = Math.max(...row.segments.map((s) => s.count), 1);
    const maxFraction = Math.max(...row.segments.map((s) => s.fraction), 1e-9);

    return (
      <div className="space-y-2" data-testid="composition-chart-category">
        {row.segments.map((seg) => {
          const widthPct =
            metric === 'count' ? (seg.count / maxCount) * 100 : (seg.fraction / maxFraction) * 100;
          return (
            <div
              key={seg.category}
              className="grid grid-cols-1 gap-1 sm:grid-cols-[minmax(8rem,14rem)_1fr] sm:items-center"
            >
              <span
                className="truncate text-xs font-medium text-gray-700"
                title={labelFor(seg.category)}
              >
                {labelFor(seg.category)}
              </span>
              <div className="flex min-w-0 items-center gap-2">
                <div className="h-6 min-w-0 flex-1 overflow-hidden rounded bg-gray-100">
                  <button
                    type="button"
                    disabled={!onCategoryClick}
                    onClick={() => onCategoryClick?.(seg.category)}
                    className={`h-full rounded transition-all ${onCategoryClick ? 'w-full cursor-pointer hover:brightness-95' : ''}`}
                    style={{
                      width: `${Math.max(widthPct, seg.count > 0 ? 2 : 0)}%`,
                      backgroundColor: colors.get(seg.category) ?? PALETTE[0],
                    }}
                    title={onCategoryClick ? `Focus: ${labelFor(seg.category)}` : undefined}
                  />
                </div>
                <span className="w-24 shrink-0 text-right text-xs tabular-nums text-gray-600">
                  {formatBarLabel(metric, seg.count, row.total, datasetTotal)}
                  {metric === 'count' && (
                    <span className="text-gray-400">
                      {' '}
                      ({row.total > 0 ? ((seg.count / row.total) * 100).toFixed(1) : '0.0'}%)
                    </span>
                  )}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div className="space-y-3 overflow-x-auto" data-testid="composition-chart-stacked">
      {rows.map((row) => (
        <div key={row.rowKey} className="min-w-[280px]">
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="truncate text-xs font-medium text-gray-800" title={row.rowLabel}>
              {row.rowLabel}
            </span>
            <span className="shrink-0 text-xs tabular-nums text-gray-500">
              {row.total.toLocaleString()} cells
            </span>
          </div>
          <div className="flex h-8 w-full overflow-hidden rounded-md bg-gray-100">
            {row.segments.map((seg) => {
              const widthPct =
                metric === 'percent'
                  ? seg.fraction * 100
                  : row.total > 0
                    ? (seg.count / row.total) * 100
                    : 0;
              if (widthPct <= 0) return null;
              return (
                <button
                  key={`${row.rowKey}-${seg.category}`}
                  type="button"
                  disabled={!onCategoryClick}
                  onClick={() => onCategoryClick?.(seg.category)}
                  className={`h-full shrink-0 border-r border-white/40 last:border-r-0 ${onCategoryClick ? 'cursor-pointer hover:brightness-95' : ''}`}
                  style={{
                    width: `${widthPct}%`,
                    backgroundColor: colors.get(seg.category) ?? PALETTE[0],
                  }}
                  title={`${labelFor(seg.category)}: ${seg.count.toLocaleString()} (${row.total > 0 ? ((seg.count / row.total) * 100).toFixed(1) : '0'}% of row)${onCategoryClick ? ' · click to focus' : ''}`}
                />
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export function CompositionLegend({
  categories,
  formatCategoryLabel,
}: {
  categories: string[];
  formatCategoryLabel?: (categoryKey: string) => string;
}) {
  const colors = useMemo(() => categoryColorMap(categories), [categories]);
  const labelFor = (key: string) => (formatCategoryLabel ? formatCategoryLabel(key) : key);
  if (categories.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-2 border-t border-gray-100 pt-3">
      {categories.map((cat) => (
        <div key={cat} className="flex max-w-[14rem] items-center gap-2">
          <span
            className="h-2.5 w-2.5 shrink-0 rounded-sm"
            style={{ backgroundColor: colors.get(cat) ?? PALETTE[0] }}
          />
          <span className="truncate text-xs text-gray-600" title={labelFor(cat)}>
            {labelFor(cat)}
          </span>
        </div>
      ))}
    </div>
  );
}
