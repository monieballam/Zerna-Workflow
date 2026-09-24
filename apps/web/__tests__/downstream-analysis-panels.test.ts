import { describe, expect, it } from 'vitest';
import type { Artifact } from '@zerna/sdk';
import { deModeLabel, pickDeResultsArtifact } from '@/components/runs/DownstreamAnalysisPanels';

const base = {
  run_id: 'run-1',
  size_bytes: 1,
  metadata: {} as Record<string, unknown>,
  download_url: null as string | null,
  created_at: '',
};

describe('DownstreamAnalysisPanels helpers', () => {
  it('pickDeResultsArtifact prefers pseudobulk file when mode is pseudobulk', () => {
    const artifacts: Artifact[] = [
      {
        ...base,
        id: 'marker',
        artifact_type: 'de_results',
        s3_path: 's3://b/de_results/de_results.csv',
      },
      {
        ...base,
        id: 'pb',
        artifact_type: 'de_results',
        s3_path: 's3://b/de_results/de_results_pseudobulk.csv',
      },
    ];
    expect(pickDeResultsArtifact(artifacts, 'pseudobulk_sample_level_contrast')?.id).toBe('pb');
  });

  it('pickDeResultsArtifact prefers marker file when mode is marker_ranking', () => {
    const artifacts: Artifact[] = [
      {
        ...base,
        id: 'marker',
        artifact_type: 'de_results',
        s3_path: 's3://b/de_results/de_results.csv',
      },
      {
        ...base,
        id: 'pb',
        artifact_type: 'de_results',
        s3_path: 's3://b/de_results/de_results_pseudobulk.csv',
      },
    ];
    expect(pickDeResultsArtifact(artifacts, 'marker_ranking')?.id).toBe('marker');
  });

  it('deModeLabel maps backend modes to display strings', () => {
    expect(deModeLabel('marker_ranking')).toBe('Marker ranking');
    expect(deModeLabel('condition_de_within_celltype')).toBe('Condition DE within cell type');
    expect(deModeLabel('pseudobulk_sample_level_contrast')).toBe(
      'Pseudobulk sample-level contrast'
    );
  });
});
