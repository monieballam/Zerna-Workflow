import { describe, expect, it } from 'vitest';
import { getDatasetScoreSemantics, normalizeLigandReceptorRows, parsePValue } from './normalize';
import type { NormalizedLRRow } from './normalize';

describe('parsePValue', () => {
  it('parses <0.001 as numeric 0.001', () => {
    const r = parsePValue('<0.001');
    expect(r.numeric).toBe(0.001);
    expect(r.display).toBe('<0.001');
  });

  it('parses plain floats', () => {
    expect(parsePValue('0.04').numeric).toBe(0.04);
    expect(parsePValue(0.02).numeric).toBe(0.02);
  });

  it('returns null numeric for unparseable', () => {
    expect(parsePValue('NS').numeric).toBeNull();
  });
});

describe('normalizeLigandReceptorRows', () => {
  it('maps alias columns and builds interaction_name', () => {
    const rows = normalizeLigandReceptorRows([
      {
        source: 'A',
        target: 'B',
        ligand_gene: 'L1',
        receptor_gene: 'R1',
        interaction_score: 0.9,
        p_val: '<0.001',
      },
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      sender: 'A',
      receiver: 'B',
      ligand: 'L1',
      receptor: 'R1',
      score: 0.9,
      score_semantics: 'strength',
      p_value_numeric: 0.001,
      interaction_name: 'L1–R1',
    });
    expect(rows[0].score_source).toBeTruthy();
  });

  it('classifies aggregate_rank as rank semantics', () => {
    const rows = normalizeLigandReceptorRows([
      {
        source: 'S',
        target: 'T',
        ligand: 'L',
        receptor: 'R',
        aggregate_rank: 2,
        p_value: 0.01,
      },
    ]);
    expect(rows[0]?.score_semantics).toBe('rank');
  });

  it('drops incomplete rows', () => {
    expect(
      normalizeLigandReceptorRows([
        { source: 'A', target: 'B', ligand: 'L', receptor: 'R' }, // no score
      ])
    ).toHaveLength(0);
  });
});

describe('getDatasetScoreSemantics', () => {
  it('returns unknown for empty', () => {
    expect(getDatasetScoreSemantics([])).toBe('unknown');
  });

  it('returns unknown when rows disagree', () => {
    const mixed: NormalizedLRRow[] = [
      {
        sender: 'a',
        receiver: 'b',
        ligand: 'l',
        receptor: 'r',
        score: 1,
        score_source: 'x',
        score_semantics: 'strength',
        p_value: '0.1',
        p_value_numeric: 0.1,
        interaction_name: 'l–r',
        raw: {},
      },
      {
        sender: 'a',
        receiver: 'b',
        ligand: 'l',
        receptor: 'r',
        score: 2,
        score_source: 'y',
        score_semantics: 'rank',
        p_value: '0.1',
        p_value_numeric: 0.1,
        interaction_name: 'l–r',
        raw: {},
      },
    ];
    expect(getDatasetScoreSemantics(mixed)).toBe('unknown');
  });
});
