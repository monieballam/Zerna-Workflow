import { describe, expect, it } from 'vitest';
import type { CellMetadata } from '@/lib/embedding-types';
import {
  EXPLORER_LEVEL3_NO_FINE_PREFIX,
  applyLevel3ExplorerVizMetadata,
} from '@/lib/embedding-legend-utils';
import {
  aggregateByEffectiveExplorerLevel3,
  buildCompositionRows,
  defaultCompositionGrouping,
  pickBiologyScanField,
  resolveGranularityField,
  topPopulations,
} from '@/lib/run-composition';

describe('run-composition', () => {
  const meta: CellMetadata[] = [
    {
      cellId: 'a',
      lineage: 'Lymphoid',
      cellType: 'T cell',
      level2: 'CD8 T',
      level3: 'Effector',
      condition: 'A',
    },
    {
      cellId: 'b',
      lineage: 'Lymphoid',
      cellType: 'B cell',
      level2: 'Naive B',
      level3: 'IgM',
      condition: 'A',
    },
    {
      cellId: 'c',
      lineage: 'Myeloid',
      cellType: 'Macrophage',
      level2: 'M1',
      level3: '—',
      condition: 'B',
    },
  ];
  const fields = new Set(['lineage', 'cellType', 'level2', 'level3', 'condition', 'sample']);

  it('defaults grouping to condition when multiple conditions exist', () => {
    expect(defaultCompositionGrouping(meta, fields)).toBe('condition');
  });

  it('resolves granularity fields with fallbacks', () => {
    expect(resolveGranularityField(meta, fields, 'broad')).toBe('lineage');
    expect(resolveGranularityField(meta, fields, 'major')).toBe('level2');
    expect(resolveGranularityField(meta, fields, 'fine')).toBe('level3');
  });

  it('pickBiologyScanField prefers structural lineage / level2 / level3 over merged cellType', () => {
    expect(pickBiologyScanField(meta, fields)).toBe('level3');
    const lineageOnly: CellMetadata[] = [{ cellId: 'x', lineage: 'Immune' }];
    expect(
      pickBiologyScanField(lineageOnly, new Set(['lineage', 'cellType', 'level2', 'level3']))
    ).toBe('lineage');
    const debugOnly: CellMetadata[] = [{ cellId: 'x', cellType: 'T cell' }];
    expect(pickBiologyScanField(debugOnly, new Set(['cellType']))).toBe('cellType');
  });

  it('builds stacked rows by condition sorted by total cells', () => {
    const rows = buildCompositionRows(meta, 'condition', 'level2');
    expect(rows.map((r) => r.rowLabel)).toEqual(['A', 'B']);
    expect(rows[0].total).toBe(2);
    expect(rows[1].total).toBe(1);
  });

  it('fine granularity resolves to level3 when only major type is present (effective L3 buckets)', () => {
    const mixed: CellMetadata[] = [
      { cellId: '1', lineage: 'Immune', level2: 'T cells', level3: '', condition: 'A' },
      { cellId: '2', lineage: 'Immune', level2: 'Myeloid', level3: '', condition: 'A' },
    ];
    const fs = new Set(['lineage', 'level2', 'level3', 'condition']);
    expect(resolveGranularityField(mixed, fs, 'fine')).toBe('level3');
  });

  it('composition fine mode counts match UMAP Level 3 viz metadata (resolved + unresolved)', () => {
    const mixed: CellMetadata[] = [
      { cellId: '1', lineage: 'Immune', level2: 'T cells', level3: 'CD8', condition: 'A' },
      { cellId: '2', lineage: 'Immune', level2: 'Myeloid', level3: '', condition: 'A' },
      { cellId: '3', lineage: 'Immune', level2: 'Myeloid', level3: '', condition: 'A' },
    ];
    const fs = new Set(['lineage', 'level2', 'level3', 'condition']);
    expect(resolveGranularityField(mixed, fs, 'fine')).toBe('level3');

    const viz = applyLevel3ExplorerVizMetadata(mixed);
    const fromViz = new Map<string, number>();
    for (const m of viz) {
      const v = String(m.level3 ?? '').trim();
      if (!v) continue;
      fromViz.set(v, (fromViz.get(v) ?? 0) + 1);
    }

    const agg = aggregateByEffectiveExplorerLevel3(mixed);
    expect(agg.get('CD8')).toBe(1);
    expect(agg.get(`${EXPLORER_LEVEL3_NO_FINE_PREFIX}Myeloid`)).toBe(2);
    expect(fromViz.get('CD8')).toBe(1);
    expect(fromViz.get(`${EXPLORER_LEVEL3_NO_FINE_PREFIX}Myeloid`)).toBe(2);

    const [row] = buildCompositionRows(mixed, 'overall', 'level3');
    const compMap = new Map(row.segments.map((s) => [s.category, s.count]));
    expect(compMap.get('CD8')).toBe(1);
    expect(compMap.get(`${EXPLORER_LEVEL3_NO_FINE_PREFIX}Myeloid`)).toBe(2);

    const top = topPopulations(mixed, 'level3', 5);
    expect(top.find((p) => p.label === 'CD8')?.count).toBe(1);
    expect(top.find((p) => p.label === 'Myeloid')?.count).toBe(2);
  });
});
