'use client';

import { useCallback } from 'react';
import type { CellMetadata } from '@/lib/embedding-types';
import { formatExplorerFieldLabel } from '@/lib/explorer-field-metadata';
import {
  formatLevel3UnresolvedDetail,
  formatLevel3UnresolvedPrimary,
  parseExplorerSyntheticNoFineLevel2,
} from '@/lib/explorer-biology-display';
import {
  buildCategoricalLegendEntries,
  EXPLORER_LEVEL3_NO_FINE_PREFIX,
  rgbToCss,
  type CategoricalLegendEntry,
} from '@/lib/embedding-legend-utils';

function emptyCategoricalLegendLabel(colorField: string): string {
  if (colorField === 'level2') return 'No major type assigned';
  if (colorField === 'lineage' || colorField === 'level1') return 'No lineage label';
  return 'Unassigned';
}

export default function EmbeddingBottomLegend({
  metadata,
  countMetadata,
  colorField,
  isCategorical,
  continuousMin,
  continuousMax,
  geneName,
  formatCategoryLegendLabel,
  focusRawValue,
  hoverRawValue,
  onFocusRawValue,
  onHoverRawValue,
}: {
  metadata: CellMetadata[];
  /** When set (e.g. full explorer sample), category counts in the legend use this cohort; plot still uses `metadata`. */
  countMetadata?: CellMetadata[];
  colorField: string;
  isCategorical: boolean;
  continuousMin: number;
  continuousMax: number;
  geneName: string | null;
  formatCategoryLegendLabel?: (field: string, rawValue: string) => string;
  focusRawValue: string | null;
  /** Synced hover from parent for dimming non-hovered items. */
  hoverRawValue: string | null;
  onFocusRawValue: (raw: string | null) => void;
  onHoverRawValue: (raw: string | null) => void;
}) {
  const syncHover = useCallback(
    (raw: string | null) => {
      onHoverRawValue(raw);
    },
    [onHoverRawValue]
  );

  const countSource = countMetadata ?? metadata;
  const legendCountsFullSample = countMetadata != null && countMetadata.length !== metadata.length;
  const entries: CategoricalLegendEntry[] = isCategorical
    ? buildCategoricalLegendEntries(
        countSource,
        colorField,
        undefined,
        32,
        colorField === 'level3'
          ? { countDistinctClustersForPrefix: EXPLORER_LEVEL3_NO_FINE_PREFIX }
          : undefined
      )
    : [];

  if (geneName) {
    return (
      <div
        className="mt-3 rounded-lg border border-gray-200 bg-white/90 px-3 py-2"
        data-testid="embedding-legend-expression"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
            Expression · <span className="font-mono text-gray-700">{geneName}</span>
          </p>
          <span className="text-[10px] tabular-nums text-gray-500">
            min {continuousMin.toPrecision(3)} · max {continuousMax.toPrecision(3)}
          </span>
        </div>
        <div
          className="mt-2 h-3 w-full max-w-md rounded border border-gray-200"
          style={{
            background:
              'linear-gradient(90deg, rgb(68,1,84), rgb(59,82,139), rgb(33,144,140), rgb(92,200,99), rgb(253,231,37))',
          }}
          title="Viridis: low → high expression"
        />
      </div>
    );
  }

  if (!isCategorical || entries.length === 0) {
    return null;
  }

  return (
    <div
      className="mt-3 rounded-lg border border-gray-200 bg-white/90 px-2 py-2"
      data-testid="embedding-legend-categorical"
    >
      <p className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
        Legend · {formatExplorerFieldLabel(colorField)}
      </p>
      {legendCountsFullSample ? (
        <p className="mb-2 px-1 text-[10px] leading-snug text-gray-500">
          Counts are for the full explorer sample; the plot shows the filtered subset.
        </p>
      ) : null}
      <div className="flex flex-wrap gap-x-2 gap-y-2">
        {entries.map((e) => {
          const isNoFineLevel3 =
            colorField === 'level3' && e.rawValue.startsWith(EXPLORER_LEVEL3_NO_FINE_PREFIX);
          const l2ForNoFine = isNoFineLevel3 ? parseExplorerSyntheticNoFineLevel2(e.rawValue) : '';
          const label =
            e.rawValue === ''
              ? emptyCategoricalLegendLabel(colorField)
              : isNoFineLevel3
                ? formatLevel3UnresolvedPrimary(l2ForNoFine)
                : (formatCategoryLegendLabel?.(colorField, e.rawValue) ?? e.rawValue);
          const nc = e.nClustersDistinct ?? 0;
          const clusterTail =
            isNoFineLevel3 && nc > 1
              ? `${nc} clusters`
              : isNoFineLevel3 && nc === 1
                ? '1 cluster'
                : '';
          const detailHint = isNoFineLevel3 ? formatLevel3UnresolvedDetail(l2ForNoFine) : '';
          const titleExtra = isNoFineLevel3 && clusterTail ? ` · ${clusterTail}` : '';
          const buttonTitle = isNoFineLevel3
            ? `${e.count.toLocaleString()} cells${titleExtra}. ${detailHint} Click to focus or blur.`
            : `${e.count.toLocaleString()} cells — click to focus or blur`;
          const focused = focusRawValue === e.rawValue;
          const hovered = hoverRawValue === e.rawValue;
          const hoverDim = hoverRawValue != null && !hovered && !focused;
          return (
            <button
              key={e.rawValue === '' ? '__legend_empty__' : e.rawValue}
              type="button"
              title={buttonTitle}
              onClick={() => {
                const next = focused ? null : e.rawValue;
                onFocusRawValue(next);
              }}
              onMouseEnter={() => syncHover(e.rawValue)}
              onMouseLeave={() => syncHover(null)}
              className={`inline-flex max-w-[18rem] cursor-pointer items-center gap-2 rounded-full border px-2.5 py-1.5 text-left text-[11px] font-medium transition-all ${
                focused
                  ? 'border-blue-500 bg-blue-100/90 text-blue-950 shadow-md ring-2 ring-blue-400/70'
                  : hovered
                    ? 'border-slate-400 bg-white text-gray-900 shadow-sm ring-1 ring-slate-300'
                    : hoverDim
                      ? 'border-transparent bg-gray-50/40 text-gray-500 opacity-45'
                      : 'border-gray-200/80 bg-gray-50 text-gray-800 hover:border-blue-300 hover:bg-white hover:shadow-sm'
              }`}
            >
              <span
                className="h-3.5 w-3.5 shrink-0 rounded-sm border border-black/15 shadow-inner"
                style={{ backgroundColor: rgbToCss(e.rgb) }}
                aria-hidden
              />
              <span className="min-w-0 truncate">{label}</span>
              <span
                className={`shrink-0 tabular-nums ${focused ? 'text-blue-800' : 'text-gray-400'}`}
              >
                {isNoFineLevel3 && clusterTail
                  ? `${e.count.toLocaleString()} · ${clusterTail}`
                  : e.count.toLocaleString()}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
