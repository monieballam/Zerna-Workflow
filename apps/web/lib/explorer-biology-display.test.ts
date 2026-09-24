import { describe, expect, it } from 'vitest';
import type { CellMetadata } from '@/lib/embedding-types';
import { EXPLORER_LEVEL3_NO_FINE_PREFIX } from '@/lib/embedding-legend-utils';
import {
  biologyClusterHeadlineFromCells,
  dominantNonEmptyMetadataField,
  formatLevel3ExplorerGroupLabelForUi,
  formatLevel3UnresolvedDetail,
  formatLevel3UnresolvedPrimary,
  isExplorerSyntheticNoFineLevel3,
  parseExplorerSyntheticNoFineLevel2,
} from '@/lib/explorer-biology-display';

describe('explorer-biology-display', () => {
  it('formatLevel3UnresolvedPrimary shows major type without placeholder bucket', () => {
    expect(formatLevel3UnresolvedPrimary('Fibroblasts')).toBe('Fibroblasts');
    expect(formatLevel3UnresolvedPrimary('  ')).toBe('Major type unknown');
  });

  it('formatLevel3UnresolvedDetail explains unresolved structural L3 without inventing L3', () => {
    expect(formatLevel3UnresolvedDetail('Myeloid')).toContain('Myeloid');
    expect(formatLevel3UnresolvedDetail('Myeloid')).toContain('auto_level3');
    expect(formatLevel3UnresolvedDetail('')).toBe(
      'Structural fine subtype (auto_level3) not resolved.'
    );
  });

  it('parses synthetic no-fine keys used only for viz grouping', () => {
    const raw = `${EXPLORER_LEVEL3_NO_FINE_PREFIX}NK cells`;
    expect(isExplorerSyntheticNoFineLevel3(raw)).toBe(true);
    expect(parseExplorerSyntheticNoFineLevel2(raw)).toBe('NK cells');
  });

  it('formatLevel3ExplorerGroupLabelForUi matches legend primary for synthetic keys', () => {
    const raw = `${EXPLORER_LEVEL3_NO_FINE_PREFIX}Fibroblasts`;
    expect(formatLevel3ExplorerGroupLabelForUi(raw)).toBe('Fibroblasts');
    expect(formatLevel3ExplorerGroupLabelForUi('CD8')).toBe('CD8');
  });

  it('biologyClusterHeadlineFromCells omits L3 when structural L3 is empty', () => {
    const cells: CellMetadata[] = [
      {
        cellId: 'a',
        lineage: 'Immune',
        level1: 'Immune',
        level2: 'Myeloid',
        level3: '',
        cluster: '0',
      },
    ];
    expect(biologyClusterHeadlineFromCells(cells, 'fallback')).toBe('Immune | Myeloid');
  });

  it('biologyClusterHeadlineFromCells includes L3 when present', () => {
    const cells: CellMetadata[] = [
      {
        cellId: 'a',
        lineage: 'Immune',
        level1: 'Immune',
        level2: 'Myeloid',
        level3: 'Macrophage',
        cluster: '0',
      },
    ];
    expect(biologyClusterHeadlineFromCells(cells, 'fallback')).toBe(
      'Immune | Myeloid | Macrophage'
    );
  });

  it('dominantNonEmptyMetadataField ignores nan-like tokens', () => {
    const cells: CellMetadata[] = [
      { cellId: 'a', lineage: 'nan', level2: 'T cells', level3: '', cluster: '0' },
      { cellId: 'b', lineage: 'Immune', level2: 'T cells', level3: '', cluster: '0' },
    ];
    expect(dominantNonEmptyMetadataField(cells, 'lineage')).toBe('Immune');
  });
});
