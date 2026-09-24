import type { CellMetadata } from '@/lib/embedding-types';
import { formatLevel3ExplorerGroupLabelForUi } from '@/lib/explorer-biology-display';
import { effectiveLevel3ExplorerGroupKeyFromStructuralMetadata } from '@/lib/embedding-legend-utils';

export type CompositionGranularity = 'broad' | 'major' | 'fine';
export type CompositionMetric = 'count' | 'percent';
export type CompositionGrouping = 'condition' | 'sample' | 'overall';

export interface CompositionSegment {
  category: string;
  count: number;
  /** 0–1 within row */
  fraction: number;
}

export interface CompositionRow {
  rowKey: string;
  rowLabel: string;
  total: number;
  segments: CompositionSegment[];
}

/** Align with explorer canonical biology: auto_level1 → lineage, L2/L3 metadata keys. */
const BROAD_CANDIDATES = ['lineage', 'level2'] as const;
const MAJOR_CANDIDATES = ['level2', 'lineage'] as const;
const FINE_CANDIDATES = ['level3', 'level2'] as const;

function nonEmptyValue(m: CellMetadata, field: string): string | null {
  const v = m[field];
  if (v == null) return null;
  const s = String(v).trim();
  return s.length > 0 ? s : null;
}

function fieldHasValues(metadata: CellMetadata[], field: string): boolean {
  for (const m of metadata) {
    if (nonEmptyValue(m, field)) return true;
  }
  return false;
}

function fieldHasEffectiveExplorerLevel3Buckets(metadata: CellMetadata[]): boolean {
  return metadata.some((m) => Boolean(effectiveLevel3ExplorerGroupKeyFromStructuralMetadata(m)));
}

/**
 * Aggregate composition segments the same way as UMAP Level 3 coloring (structural L3 or
 * ``__no_fine__|{L2}``). Keys are explorer raw values; use {@link formatLevel3ExplorerGroupLabelForUi} for UI.
 */
export function aggregateByEffectiveExplorerLevel3(metadata: CellMetadata[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const m of metadata) {
    const k = effectiveLevel3ExplorerGroupKeyFromStructuralMetadata(m);
    if (!k) continue;
    map.set(k, (map.get(k) ?? 0) + 1);
  }
  return map;
}

function aggregateCompositionByGranularityField(
  metadata: CellMetadata[],
  field: string
): Map<string, number> {
  if (field === 'level3') {
    return aggregateByEffectiveExplorerLevel3(metadata);
  }
  return aggregateByField(metadata, field);
}

/** First candidate that exists in `availableFields` and has at least one non-empty value. */
export function resolveGranularityField(
  metadata: CellMetadata[],
  availableFields: Set<string>,
  granularity: CompositionGranularity
): string | null {
  if (granularity === 'fine' && availableFields.has('level3')) {
    if (fieldHasEffectiveExplorerLevel3Buckets(metadata)) {
      return 'level3';
    }
  }
  const candidates =
    granularity === 'broad'
      ? BROAD_CANDIDATES
      : granularity === 'major'
        ? MAJOR_CANDIDATES
        : FINE_CANDIDATES;
  for (const field of candidates) {
    if (!availableFields.has(field)) continue;
    if (fieldHasValues(metadata, field)) return field;
  }
  return null;
}

export function countUniqueMetadataValues(metadata: CellMetadata[], field: string): number {
  const set = new Set<string>();
  for (const m of metadata) {
    const v = nonEmptyValue(m, field);
    if (v) set.add(v);
  }
  return set.size;
}

export function defaultCompositionGrouping(
  metadata: CellMetadata[],
  availableFields: Set<string>
): CompositionGrouping {
  if (availableFields.has('condition') && countUniqueMetadataValues(metadata, 'condition') > 1) {
    return 'condition';
  }
  if (availableFields.has('sample') && countUniqueMetadataValues(metadata, 'sample') > 1) {
    return 'sample';
  }
  return 'overall';
}

function aggregateByField(metadata: CellMetadata[], field: string): Map<string, number> {
  const map = new Map<string, number>();
  for (const m of metadata) {
    const v = nonEmptyValue(m, field);
    if (!v) continue;
    map.set(v, (map.get(v) ?? 0) + 1);
  }
  return map;
}

/** Global category totals for legend ordering (descending count). */
export function orderedCategories(rows: CompositionRow[]): string[] {
  const totals = new Map<string, number>();
  for (const row of rows) {
    for (const seg of row.segments) {
      totals.set(seg.category, (totals.get(seg.category) ?? 0) + seg.count);
    }
  }
  return Array.from(totals.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([k]) => k);
}

export function buildCompositionRows(
  metadata: CellMetadata[],
  grouping: CompositionGrouping,
  granularityField: string | null
): CompositionRow[] {
  if (!granularityField || metadata.length === 0) return [];

  if (grouping === 'overall') {
    const counts = aggregateCompositionByGranularityField(metadata, granularityField);
    const total = metadata.length;
    const segments = Array.from(counts.entries())
      .map(([category, count]) => ({
        category,
        count,
        fraction: total > 0 ? count / total : 0,
      }))
      .sort((a, b) => b.count - a.count);
    return [
      {
        rowKey: '__overall__',
        rowLabel: 'All cells',
        total,
        segments,
      },
    ];
  }

  const groupField = grouping === 'condition' ? 'condition' : 'sample';
  const byGroup = new Map<string, CellMetadata[]>();
  for (const m of metadata) {
    const g = nonEmptyValue(m, groupField);
    if (!g) continue;
    const list = byGroup.get(g) ?? [];
    list.push(m);
    byGroup.set(g, list);
  }

  const rows: CompositionRow[] = [];
  for (const [groupLabel, cells] of byGroup.entries()) {
    const counts = aggregateCompositionByGranularityField(cells, granularityField);
    const rowTotal = cells.length;
    const segments = Array.from(counts.entries())
      .map(([category, count]) => ({
        category,
        count,
        fraction: rowTotal > 0 ? count / rowTotal : 0,
      }))
      .sort((a, b) => b.count - a.count);
    rows.push({
      rowKey: groupLabel,
      rowLabel: groupLabel,
      total: rowTotal,
      segments,
    });
  }

  return rows.sort((a, b) => b.total - a.total);
}

export interface PopulationCount {
  label: string;
  count: number;
  pct: number;
}

export function topPopulations(
  metadata: CellMetadata[],
  field: string | null,
  limit: number
): PopulationCount[] {
  if (!field || metadata.length === 0) return [];
  const counts = aggregateCompositionByGranularityField(metadata, field);
  const total = metadata.length;
  return Array.from(counts.entries())
    .map(([key, count]) => ({
      label: field === 'level3' ? formatLevel3ExplorerGroupLabelForUi(key) : key,
      count,
      pct: total > 0 ? (count / total) * 100 : 0,
    }))
    .sort((a, b) => b.count - a.count)
    .slice(0, limit);
}

function dominantLabel(counts: Map<string, number>): string | null {
  let best: { label: string; count: number } | null = null;
  for (const [label, count] of counts) {
    if (!best || count > best.count) best = { label, count };
  }
  return best?.label ?? null;
}

const STROMAL_RE = /\bStromal\b|stromal|fibroblast|CAF|fibro|mesenchym|pericyte|endothelial/i;
const IMMUNE_RE =
  /\bImmune\b|\bT cell\b|T-cell|CD[48]\+|CD3|B cell|B-cell|plasma|NK\b|natural killer|myeloid|macrophage|neutroph|mono|dendritic|\bDC\b|lymphoid|granulocyte|mast cell|innate lymphoid/i;

/**
 * Field used for composition “biology” summaries (dominant type / immune / stromal hints).
 * Match the explorer contract: pipeline auto_level3 → auto_level2 → auto_level1 (`lineage`),
 * never prefer merged `cellType` when structural hierarchy columns carry values.
 */
export function pickBiologyScanField(
  metadata: CellMetadata[],
  available: Set<string>
): string | null {
  for (const f of ['level3', 'level2', 'lineage', 'cellType'] as const) {
    if (available.has(f) && fieldHasValues(metadata, f)) return f;
  }
  return null;
}

export interface BiologicalHighlights {
  dominantCellType: string | null;
  dominantStromalSubtype: string | null;
  dominantImmuneSubtype: string | null;
}

export function computeBiologicalHighlights(
  metadata: CellMetadata[],
  availableFields: Set<string>
): BiologicalHighlights {
  const scanField = pickBiologyScanField(metadata, availableFields);
  if (!scanField) {
    return {
      dominantCellType: null,
      dominantStromalSubtype: null,
      dominantImmuneSubtype: null,
    };
  }
  const counts = aggregateByField(metadata, scanField);
  const dominantCellType = dominantLabel(counts);

  let dominantStromalSubtype: string | null = null;
  let dominantImmuneSubtype: string | null = null;
  let bestStromal = 0;
  let bestImmune = 0;
  for (const [label, count] of counts) {
    if (STROMAL_RE.test(label) && count > bestStromal) {
      bestStromal = count;
      dominantStromalSubtype = label;
    }
    if (IMMUNE_RE.test(label) && count > bestImmune) {
      bestImmune = count;
      dominantImmuneSubtype = label;
    }
  }

  return { dominantCellType, dominantStromalSubtype, dominantImmuneSubtype };
}
