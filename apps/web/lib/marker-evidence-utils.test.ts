import { describe, expect, it } from 'vitest';
import {
  filterNoiseGenesForDisplay,
  isNoiseGeneMarkerForDisplay,
  rankDistinctiveMarkers,
} from './marker-evidence-utils';

describe('isNoiseGeneMarkerForDisplay', () => {
  it('flags ribosomal, mitochondrial, MRPL/MRPS, and listed housekeeping', () => {
    expect(isNoiseGeneMarkerForDisplay('RPL13')).toBe(true);
    expect(isNoiseGeneMarkerForDisplay('RPS4X')).toBe(true);
    expect(isNoiseGeneMarkerForDisplay('MRPL12')).toBe(true);
    expect(isNoiseGeneMarkerForDisplay('MRPS21')).toBe(true);
    expect(isNoiseGeneMarkerForDisplay('MT-ND1')).toBe(true);
    expect(isNoiseGeneMarkerForDisplay('MALAT1')).toBe(true);
    expect(isNoiseGeneMarkerForDisplay('EEF1A1')).toBe(true);
    expect(isNoiseGeneMarkerForDisplay('TPT1')).toBe(true);
  });

  it('allows typical lineage markers', () => {
    expect(isNoiseGeneMarkerForDisplay('CD3D')).toBe(false);
    expect(isNoiseGeneMarkerForDisplay('CD8A')).toBe(false);
    expect(isNoiseGeneMarkerForDisplay('MS4A1')).toBe(false);
  });
});

describe('filterNoiseGenesForDisplay', () => {
  it('drops ribosomal-heavy prefixes and preserves order of informative genes', () => {
    const genes = ['RPL13', 'RPS4X', 'MRPL12', 'CD3D', 'EEF1A1', 'CD8A', 'TPT1'];
    expect(filterNoiseGenesForDisplay(genes)).toEqual(['CD3D', 'CD8A']);
  });

  it('respects maxOut and dedupes', () => {
    const genes = ['CD3D', 'CD3D', 'CD8A', 'MS4A1'];
    expect(filterNoiseGenesForDisplay(genes, { maxOut: 2 })).toEqual(['CD3D', 'CD8A']);
  });

  it('returns empty when input is all noise', () => {
    expect(filterNoiseGenesForDisplay(['RPL1', 'RPS2', 'MALAT1'])).toEqual([]);
  });
});

describe('rankDistinctiveMarkers', () => {
  it('caps length after filtering', () => {
    const genes = ['CD3D', 'CD8A', 'MS4A1', 'RPL3'];
    expect(rankDistinctiveMarkers(genes, 2)).toEqual(['CD3D', 'CD8A']);
  });
});
