import { describe, expect, it } from 'vitest';
import {
  EXPLORER_FILTER_FIELD_HELP,
  explorerColorByHintsForView,
  formatExplorerFieldLabel,
  hierarchyAxesArePopulated,
  hierarchyScopedLevel2Values,
  hierarchyScopedLevel3Values,
  pickDefaultExplorerColorField,
  primaryColorFieldsFromAvailable,
  sortExplorerFieldsForUi,
  sortExplorerMetadataEntries,
  technicalColorFieldsFromAvailable,
} from './explorer-field-metadata';

describe('explorer-field-metadata', () => {
  it('sortExplorerFieldsForUi puts hierarchy keys first', () => {
    expect(
      sortExplorerFieldsForUi(['condition', 'cellType', 'cluster', 'level3', 'lineage'])
    ).toEqual(['lineage', 'level3', 'cluster', 'cellType', 'condition']);
  });

  it('formatExplorerFieldLabel uses canonical names for API keys', () => {
    expect(formatExplorerFieldLabel('cellType')).toBe(
      'Cell type (merged column — final_display first, not raw Zerna)'
    );
    expect(formatExplorerFieldLabel('level3')).toBe('Fine type / subtype');
    expect(formatExplorerFieldLabel('displayLabel')).toBe(
      'Display label (conservative UI — may hide fine subtype)'
    );
    expect(formatExplorerFieldLabel('rawAnnotationLabel')).toBe('Raw Zerna label');
  });

  it('EXPLORER_FILTER_FIELD_HELP covers primary explorer filter keys', () => {
    expect(EXPLORER_FILTER_FIELD_HELP.cellType).toContain('Merged');
    expect(EXPLORER_FILTER_FIELD_HELP.cluster).toContain('Technical');
    expect(EXPLORER_FILTER_FIELD_HELP.level3).toContain('Structural');
    expect(EXPLORER_FILTER_FIELD_HELP.level3).toContain('rawAnnotationLabel');
  });

  it('pickDefaultExplorerColorField prefers lineage on global and major type in compartments', () => {
    expect(
      pickDefaultExplorerColorField(
        ['cluster', 'cellType', 'lineage', 'level2', 'level3'],
        'global'
      )
    ).toBe('lineage');
    expect(pickDefaultExplorerColorField(['cluster', 'condition'], 'global')).toBe('cluster');
    expect(
      pickDefaultExplorerColorField(
        ['cluster', 'lineage', 'level2', 'level3', 'displayLabel'],
        'immune'
      )
    ).toBe('level2');
  });

  it('primaryColorFieldsFromAvailable is global broad+major+fine; compartment major+fine', () => {
    expect(primaryColorFieldsFromAvailable(['level3', 'lineage', 'cluster'], 'global')).toEqual([
      'lineage',
      'level3',
    ]);
    expect(
      primaryColorFieldsFromAvailable(['level3', 'lineage', 'level2', 'cluster'], 'global')
    ).toEqual(['lineage', 'level2', 'level3']);
    expect(primaryColorFieldsFromAvailable(['level3', 'lineage', 'cluster'], 'immune')).toEqual([
      'level3',
    ]);
    expect(
      primaryColorFieldsFromAvailable(['level3', 'lineage', 'level2', 'cluster'], 'immune')
    ).toEqual(['level2', 'level3']);
  });

  it('technicalColorFieldsFromAvailable is allowlisted only; skips primary View by fields', () => {
    expect(
      technicalColorFieldsFromAvailable(
        ['level3', 'displayLabel', 'cluster', 'lineageSubcluster', 'batch'],
        'global'
      )
    ).toEqual(['cluster']);
  });

  it('technicalColorFieldsFromAvailable lists lineage under Advanced in compartment views', () => {
    expect(
      technicalColorFieldsFromAvailable(
        ['fineSubcluster', 'cluster', 'lineage', 'cellType'],
        'global'
      )
    ).toEqual(['fineSubcluster', 'cluster', 'cellType']);
    expect(
      technicalColorFieldsFromAvailable(
        ['fineSubcluster', 'cluster', 'lineage', 'cellType', 'level2', 'level3'],
        'immune'
      )
    ).toEqual(['lineage', 'fineSubcluster', 'cluster', 'cellType']);
  });

  it('explorerColorByHintsForView mentions global lineage/major/fine and Advanced', () => {
    const g = explorerColorByHintsForView('global', { isFinePartitionView: false });
    expect(g.some((l) => /auto_level1|lineage/i.test(l))).toBe(true);
    expect(g.some((l) => /auto_level3|fine subtype/i.test(l))).toBe(true);
    expect(g.some((l) => /Advanced.*technical/i.test(l))).toBe(true);
    const fine = explorerColorByHintsForView('fine_t_cells', { isFinePartitionView: true });
    expect(fine.some((l) => /auto_level3|Fine/i.test(l))).toBe(true);
  });

  it('sortExplorerMetadataEntries orders hierarchy before other keys', () => {
    const sorted = sortExplorerMetadataEntries([
      ['batch', 'b1'],
      ['cellType', 'X'],
      ['lineage', 'Immune'],
      ['level2', 'T cell'],
      ['level3', 'CD8'],
    ]);
    expect(sorted.map(([k]) => k)).toEqual(['lineage', 'level2', 'level3', 'cellType', 'batch']);
  });

  const sampleAxes = {
    level2_by_lineage: {
      Immune: ['T cells', 'Myeloid'],
      Stromal: ['Fibroblasts', 'Smooth muscle'],
    },
    level3_by_lineage_major: {
      'Immune|T cells': ['CD4', 'CD8'],
      'Stromal|Fibroblasts': ['iCAF', 'myCAF'],
    },
  };

  it('hierarchyScopedLevel2Values is empty until lineage is selected; then lineage-specific only', () => {
    const allL2 = ['T cells', 'Myeloid', 'Fibroblasts', 'Smooth muscle'];
    expect(hierarchyScopedLevel2Values(undefined, allL2, new Set())).toEqual(allL2);
    expect(hierarchyScopedLevel2Values(sampleAxes, allL2, new Set())).toEqual([]);
    expect(hierarchyScopedLevel2Values(sampleAxes, allL2, new Set(['Immune']))).toEqual([
      'T cells',
      'Myeloid',
    ]);
    expect(hierarchyScopedLevel2Values(sampleAxes, allL2, new Set(['Stromal']))).toEqual([
      'Fibroblasts',
      'Smooth muscle',
    ]);
    expect(
      hierarchyScopedLevel2Values(sampleAxes, allL2, new Set(['Immune', 'Stromal'])).sort()
    ).toEqual(['Fibroblasts', 'Myeloid', 'Smooth muscle', 'T cells']);
  });

  it('hierarchyScopedLevel3Values requires L1 and L2; scopes to branch keys', () => {
    const allL3 = ['CD4', 'CD8', 'iCAF', 'myCAF', 'Macrophage'];
    expect(hierarchyScopedLevel3Values(sampleAxes, allL3, new Set(['Immune']), new Set())).toEqual(
      []
    );
    expect(hierarchyScopedLevel3Values(sampleAxes, allL3, new Set(), new Set(['T cells']))).toEqual(
      []
    );
    expect(
      hierarchyScopedLevel3Values(sampleAxes, allL3, new Set(['Immune']), new Set(['T cells']))
    ).toEqual(['CD4', 'CD8']);
    expect(
      hierarchyScopedLevel3Values(sampleAxes, allL3, new Set(['Stromal']), new Set(['Fibroblasts']))
    ).toEqual(['iCAF', 'myCAF']);
  });

  it('hierarchyAxesArePopulated reflects non-empty level2_by_lineage', () => {
    expect(hierarchyAxesArePopulated(undefined)).toBe(false);
    expect(hierarchyAxesArePopulated({ level2_by_lineage: {}, level3_by_lineage_major: {} })).toBe(
      false
    );
    expect(hierarchyAxesArePopulated(sampleAxes)).toBe(true);
  });
});
