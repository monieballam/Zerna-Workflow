/**
 * Biology-first display strings for the run explorer (canonical auto_level1–3).
 * Does not mutate structural fields — display / legend / inspector only.
 */

import type { CellMetadata } from '@/lib/embedding-types';
import { EXPLORER_LEVEL3_NO_FINE_PREFIX } from '@/lib/embedding-legend-utils';

export function dominantNonEmptyMetadataField(cells: CellMetadata[], field: string): string {
  const counts = new Map<string, number>();
  for (const m of cells) {
    const v = String(m[field] ?? '').trim();
    if (!v) continue;
    const low = v.toLowerCase();
    if (low === 'nan' || low === 'none') continue;
    counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  let best = '';
  let bestN = 0;
  for (const [k, n] of counts) {
    if (n > bestN) {
      bestN = n;
      best = k;
    }
  }
  return best;
}

/** Primary legend / centroid text when structural L3 is missing: major type only (no placeholder bucket). */
export function formatLevel3UnresolvedPrimary(l2: string): string {
  const t = l2.trim();
  return t || 'Major type unknown';
}

/** Tooltip / metadata sidebar when L3 is display-fallback to L2. */
export function formatLevel3UnresolvedDetail(l2: string): string {
  const t = l2.trim();
  if (!t) return 'Structural fine subtype (auto_level3) not resolved.';
  return `${t} — structural fine subtype (auto_level3) not resolved; showing major type only.`;
}

export function isExplorerSyntheticNoFineLevel3(rawValue: string): boolean {
  return rawValue.startsWith(EXPLORER_LEVEL3_NO_FINE_PREFIX);
}

export function parseExplorerSyntheticNoFineLevel2(rawValue: string): string {
  if (!isExplorerSyntheticNoFineLevel3(rawValue)) return '';
  return rawValue.slice(EXPLORER_LEVEL3_NO_FINE_PREFIX.length).trim();
}

/** Human-readable label for a UMAP / composition Level 3 group key (structural or ``__no_fine__|…``). */
export function formatLevel3ExplorerGroupLabelForUi(groupKey: string): string {
  const k = groupKey.trim();
  if (!k) return '';
  if (isExplorerSyntheticNoFineLevel3(k)) {
    return formatLevel3UnresolvedPrimary(parseExplorerSyntheticNoFineLevel2(k));
  }
  return k;
}

/**
 * Inspector / summary headline: canonical L1 | L2 | L3 when L3 exists; else L1 | L2 only.
 * Never applies cluster display aliases — biology only.
 */
export function biologyClusterHeadlineFromCells(
  cells: CellMetadata[],
  serverFallback: string
): string {
  if (cells.length === 0) return serverFallback;
  const l1 =
    dominantNonEmptyMetadataField(cells, 'lineage') ||
    dominantNonEmptyMetadataField(cells, 'level1');
  const l2 = dominantNonEmptyMetadataField(cells, 'level2');
  const l3 = dominantNonEmptyMetadataField(cells, 'level3');
  if (l3) return [l1, l2, l3].filter(Boolean).join(' | ');
  if (l2) return [l1, l2].filter(Boolean).join(' | ');
  return serverFallback;
}
