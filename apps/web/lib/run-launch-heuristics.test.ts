import { describe, expect, it } from 'vitest';
import type { Dataset } from '@zerna/sdk';
import {
  applyLaunchPresetToParams,
  buildLargeRunAdvisory,
  estimateRunComplexity,
  getDatasetScaleSnapshot,
} from './run-launch-heuristics';

describe('run-launch-heuristics', () => {
  const datasets: Dataset[] = [
    {
      id: 'ds-1',
      organization_id: 'o1',
      name: 'Merged PBMC',
      description: null,
      metadata: { n_sources: 4 },
      created_at: '',
      versions: [
        {
          id: 'dv-big',
          version: '2',
          s3_path: 'x',
          cell_count: 300_000,
          gene_count: 36_000,
          file_format: 'h5ad',
          metadata: {},
          created_at: '',
        },
      ],
    },
  ];

  it('getDatasetScaleSnapshot reads cells, genes, merge hint, batch columns', () => {
    const snap = getDatasetScaleSnapshot(datasets, 'dv-big', 5);
    expect(snap?.cellCount).toBe(300_000);
    expect(snap?.geneCount).toBe(36_000);
    expect(snap?.mergeOrSourceHint).toMatch(/4 input sources/);
    expect(snap?.batchLikeColumnCount).toBe(5);
  });

  it('estimateRunComplexity escalates for large cells and heavy options', () => {
    expect(
      estimateRunComplexity(
        300_000,
        20_000,
        { ambient_correction: false },
        {
          batchCorrectionEnabled: false,
          scvi: false,
          heavyOptionalCount: 0,
        }
      )
    ).toBe('very_heavy');

    expect(
      estimateRunComplexity(
        50_000,
        20_000,
        {},
        {
          batchCorrectionEnabled: true,
          scvi: false,
          heavyOptionalCount: 1,
        }
      )
    ).toBe('heavy');
  });

  it('buildLargeRunAdvisory returns null when no risk signals and standard complexity', () => {
    const small: Dataset[] = [
      {
        id: 'ds-small',
        organization_id: 'o1',
        name: 'Small',
        description: null,
        metadata: {},
        created_at: '',
        versions: [
          {
            id: 'dv-sm',
            version: '1',
            s3_path: 'x',
            cell_count: 5000,
            gene_count: 20000,
            file_format: 'h5ad',
            metadata: {},
            created_at: '',
          },
        ],
      },
    ];
    const snap = getDatasetScaleSnapshot(small, 'dv-sm', 1);
    const adv = buildLargeRunAdvisory(snap, { batch_correction: false }, 1);
    expect(adv).toBeNull();
  });

  it('buildLargeRunAdvisory includes suggestions for large runs', () => {
    const snap = getDatasetScaleSnapshot(datasets, 'dv-big', 8);
    const adv = buildLargeRunAdvisory(
      snap,
      { batch_correction: true, integration_mode: 'scvi' },
      8
    );
    expect(adv).not.toBeNull();
    expect(adv!.riskSignals.length).toBeGreaterThan(0);
    expect(adv!.suggestions.some((s) => /Lightweight preset/i.test(s))).toBe(true);
  });

  it('applyLaunchPresetToParams lightweight disables optional analyses', () => {
    const schema = {
      pathway_scoring: { type: 'boolean' },
      ligand_receptor: { type: 'boolean' },
      batch_correction: { type: 'boolean' },
      de_mode: { type: 'string' },
      n_top_genes: { type: 'integer' },
      ambient_correction: { type: 'boolean' },
      ambient_method: { type: 'string' },
      integration_mode: { type: 'string' },
    };
    const defaults = {
      pathway_scoring: true,
      ligand_receptor: true,
      batch_correction: true,
      de_mode: 'pseudobulk_sample_level_contrast',
      n_top_genes: 3000,
      ambient_correction: true,
      ambient_method: 'identity',
      integration_mode: 'scvi',
    };
    const next = applyLaunchPresetToParams(
      'lightweight',
      { ...defaults, annotation_species: 'human' },
      defaults,
      schema
    );
    expect(next.pathway_scoring).toBe(false);
    expect(next.ligand_receptor).toBe(false);
    expect(next.batch_correction).toBe(false);
    expect(next.de_mode).toBe('marker_ranking');
    expect(next.n_top_genes).toBe(1500);
    expect(next.annotation_species).toBe('human');
  });

  it('applyLaunchPresetToParams deep enables pathway and LR', () => {
    const schema = { pathway_scoring: { type: 'boolean' }, ligand_receptor: { type: 'boolean' } };
    const defaults = { pathway_scoring: false, ligand_receptor: false };
    const next = applyLaunchPresetToParams('deep', defaults, defaults, schema);
    expect(next.pathway_scoring).toBe(true);
    expect(next.ligand_receptor).toBe(true);
  });
});
