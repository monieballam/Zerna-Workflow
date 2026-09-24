import type { CellMetadata } from '@/lib/embedding-types';
import { categoricalRgbForValue } from '@/lib/embedding-renderer';

/** Synthetic level3 value when structural fine subtype is missing; suffix is dominant major type (level2). */
export const EXPLORER_LEVEL3_NO_FINE_PREFIX = '__no_fine__|' as const;

export interface CategoricalLegendEntry {
  rawValue: string;
  count: number;
  rgb: [number, number, number];
  /** Populated for ``EXPLORER_LEVEL3_NO_FINE_PREFIX`` buckets when cluster ids exist on metadata. */
  nClustersDistinct?: number;
}

export interface BuildCategoricalLegendOptions {
  /** When set, count distinct ``metadata.cluster`` values per bucket whose raw key starts with this prefix. */
  countDistinctClustersForPrefix?: string;
}

/**
 * Single source for UMAP Level 3 coloring, bottom legend, and composition fine mode:
 * structural ``level3`` when non-empty; otherwise synthetic ``__no_fine__|{level2}``; else ``""``.
 * Does not mutate pipeline fields — pass structural ``m.level3`` / ``m.level2`` from API metadata.
 */
export function effectiveLevel3ExplorerGroupKeyFromStructuralMetadata(m: CellMetadata): string {
  const l3 = String(m.level3 ?? '').trim();
  if (l3) return l3;
  const l2 = String(m.level2 ?? '').trim();
  return l2 ? `${EXPLORER_LEVEL3_NO_FINE_PREFIX}${l2}` : '';
}

/**
 * Map empty explorer ``level3`` to ``__no_fine__|{level2}`` so UMAP colors and legend break out by major type.
 */
export function applyLevel3ExplorerVizMetadata(metadata: CellMetadata[]): CellMetadata[] {
  return metadata.map((m) => {
    const structural = String(m.level3 ?? '').trim();
    if (structural) return m;
    const v = effectiveLevel3ExplorerGroupKeyFromStructuralMetadata(m);
    return { ...m, level3: v || '' };
  });
}

/** Build sorted categorical legend rows (same ordering as prior EmbeddingViewer legend). */
export function buildCategoricalLegendEntries(
  metadata: CellMetadata[],
  colorField: string,
  palette?: Record<string, [number, number, number]>,
  maxItems = 32,
  opts?: BuildCategoricalLegendOptions
): CategoricalLegendEntry[] {
  const prefix = opts?.countDistinctClustersForPrefix;
  const counts = new Map<string, number>();
  const clusterSets = prefix ? new Map<string, Set<string>>() : null;

  for (const m of metadata) {
    const raw = m[colorField];
    const v = raw == null || String(raw).trim() === '' ? '' : String(raw).trim();
    counts.set(v, (counts.get(v) ?? 0) + 1);
    if (clusterSets && prefix && v.startsWith(prefix)) {
      const cid =
        m.cluster != null && String(m.cluster).trim() !== '' ? String(m.cluster).trim() : '';
      if (cid) {
        let set = clusterSets.get(v);
        if (!set) {
          set = new Set<string>();
          clusterSets.set(v, set);
        }
        set.add(cid);
      }
    }
  }

  const sorted = [...counts.entries()].sort((a, b) => {
    if (a[0] === '' && b[0] !== '') return 1;
    if (b[0] === '' && a[0] !== '') return -1;
    return b[1] - a[1];
  });
  return sorted.slice(0, maxItems).map(([rawValue, count]) => ({
    rawValue,
    count,
    rgb: categoricalRgbForValue(rawValue, palette),
    nClustersDistinct:
      clusterSets && prefix && rawValue.startsWith(prefix)
        ? (clusterSets.get(rawValue)?.size ?? 0)
        : undefined,
  }));
}

export function rgbToCss(rgb: [number, number, number]): string {
  return `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
}
