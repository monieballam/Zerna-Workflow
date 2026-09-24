import { describe, expect, it } from 'vitest';
import { evaluateUploadPreflight } from '@/lib/upload-dataset-preflight';
import {
  filesToStagedUnits,
  stagedUnitsToManifest,
  type StagedUploadUnit,
} from '@/lib/upload-dataset-staged-files';

function makeFileUnit(name: string, size = 1, datasetName = 's'): StagedUploadUnit {
  return {
    id: `id-${name}-${size}`,
    kind: 'file',
    file: new File([new Uint8Array(size)], name, { type: 'application/octet-stream' }),
    datasetName,
    condition: '',
    sampleId: '',
    tissue: '',
    platform: '',
  };
}

describe('upload-dataset-preflight', () => {
  it('blocks ambiguous multi-MTX without resolvable bundle structure', () => {
    const units = filesToStagedUnits([
      new File([], 'matrix1.mtx'),
      new File([], 'matrix2.mtx'),
      new File([], 'barcodes.tsv'),
      new File([], 'genes.tsv'),
    ]);
    const named = units.map((u) => ({ ...u, datasetName: 'sample' }));
    const { blockingErrors } = evaluateUploadPreflight(named);
    expect(blockingErrors.length).toBeGreaterThan(0);
  });

  it('blocks two GEO-style standard 10x bundles picked without folder paths (different sizes)', () => {
    const units = filesToStagedUnits([
      new File([new Uint8Array(1)], 'matrix.mtx.gz'),
      new File([new Uint8Array(1)], 'barcodes.tsv.gz'),
      new File([new Uint8Array(1)], 'features.tsv.gz'),
      new File([new Uint8Array(2)], 'matrix.mtx.gz'),
      new File([new Uint8Array(2)], 'barcodes.tsv.gz'),
      new File([new Uint8Array(2)], 'features.tsv.gz'),
    ]);
    const named = units.map((u) => ({ ...u, datasetName: 'sample' }));
    const { blockingErrors } = evaluateUploadPreflight(named);
    expect(blockingErrors.some((m) => /Add folder/i.test(m))).toBe(true);
  });

  it('allows two valid 10x bundles with metadata', () => {
    const units = filesToStagedUnits([
      new File([], 'donor1_matrix.mtx'),
      new File([], 'donor1_barcodes.tsv'),
      new File([], 'donor1_genes.tsv'),
      new File([], 'donor2_matrix.mtx'),
      new File([], 'donor2_barcodes.tsv'),
      new File([], 'donor2_features.tsv.gz'),
    ]);
    expect(units).toHaveLength(2);
    expect(units[0].kind).toBe('bundle');
    expect(units[1].kind).toBe('bundle');
    const { blockingErrors } = evaluateUploadPreflight(units);
    expect(blockingErrors).toHaveLength(0);
  });

  it('incomplete 10x bundle splits to file units but preflight still blocks on group validation', () => {
    const units = filesToStagedUnits([
      new File([], 'only_matrix.mtx'),
      new File([], 'barcodes.tsv'),
    ]);
    expect(units.every((u) => u.kind === 'file')).toBe(true);
    const { blockingErrors } = evaluateUploadPreflight(
      units.map((u) => ({ ...u, datasetName: 'n' }))
    );
    expect(blockingErrors.length).toBeGreaterThan(0);
  });

  it('warns on multiple 10x .h5 files', () => {
    const staged: StagedUploadUnit[] = [makeFileUnit('a.h5', 1), makeFileUnit('b.h5', 2)];
    const { blockingErrors, warnings } = evaluateUploadPreflight(staged);
    expect(blockingErrors).toHaveLength(0);
    expect(warnings.some((w) => /\.h5/i.test(w))).toBe(true);
  });

  it('warns on duplicate file names when same name and size (true duplicates)', () => {
    const staged: StagedUploadUnit[] = [
      makeFileUnit('counts.csv', 1),
      makeFileUnit('counts.csv', 1),
    ];
    const { warnings } = evaluateUploadPreflight(staged);
    expect(warnings.some((w) => /Duplicate file name/i.test(w))).toBe(true);
  });

  it('does not warn when same basename differs by folder path', () => {
    const f1 = new File([new Uint8Array(1)], 'meta.csv');
    Object.defineProperty(f1, 'webkitRelativePath', {
      value: 'GSM1/meta.csv',
      enumerable: true,
      configurable: true,
    });
    const f2 = new File([new Uint8Array(2)], 'meta.csv');
    Object.defineProperty(f2, 'webkitRelativePath', {
      value: 'GSM2/meta.csv',
      enumerable: true,
      configurable: true,
    });
    const staged: StagedUploadUnit[] = [
      {
        id: 'u1',
        kind: 'file',
        file: f1,
        datasetName: 'GSM1',
        condition: '',
        sampleId: '',
        tissue: '',
        platform: '',
      },
      {
        id: 'u2',
        kind: 'file',
        file: f2,
        datasetName: 'GSM2',
        condition: '',
        sampleId: '',
        tissue: '',
        platform: '',
      },
    ];
    const { warnings } = evaluateUploadPreflight(staged);
    expect(warnings.some((w) => /Duplicate file name/i.test(w))).toBe(false);
  });

  it('blocks when dataset name is empty', () => {
    const staged: StagedUploadUnit[] = [makeFileUnit('a.csv', 1, '  ')];
    const { blockingErrors } = evaluateUploadPreflight(staged);
    expect(blockingErrors.some((m) => /non-empty dataset name/i.test(m))).toBe(true);
  });

  it('allows two h5ad-only file units', () => {
    const staged: StagedUploadUnit[] = [makeFileUnit('a.h5ad'), makeFileUnit('b.h5ad')];
    const { blockingErrors, warnings } = evaluateUploadPreflight(staged);
    expect(blockingErrors).toHaveLength(0);
    expect(warnings).toHaveLength(0);
  });

  it('blocks when multiple h5ad plus unrelated files', () => {
    const staged: StagedUploadUnit[] = [
      makeFileUnit('a.h5ad'),
      makeFileUnit('b.h5ad'),
      makeFileUnit('readme.txt'),
    ];
    const { blockingErrors } = evaluateUploadPreflight(staged);
    expect(blockingErrors.some((m) => /Multiple H5AD files/i.test(m))).toBe(true);
  });
});

describe('stagedUnitsToManifest for bundles', () => {
  it('emits one manifest row per bundle with file_names', () => {
    const units = filesToStagedUnits([
      new File([], 's1_matrix.mtx'),
      new File([], 's1_barcodes.tsv'),
      new File([], 's1_features.tsv'),
      new File([], 's2_matrix.mtx'),
      new File([], 's2_barcodes.tsv'),
      new File([], 's2_genes.tsv'),
    ]);
    const manifest = stagedUnitsToManifest(units);
    expect(manifest).toHaveLength(2);
    expect(manifest[0].kind).toBe('bundle');
    expect(manifest[0].file_names).toEqual(['s1_matrix.mtx', 's1_barcodes.tsv', 's1_features.tsv']);
    expect(manifest[1].file_names).toEqual(['s2_matrix.mtx', 's2_barcodes.tsv', 's2_genes.tsv']);
  });

  it('non-10x files produce file-kind manifest rows', () => {
    const units = filesToStagedUnits([new File([], 'a.csv'), new File([], 'b.csv')]);
    expect(units).toHaveLength(2);
    const manifest = stagedUnitsToManifest(units);
    expect(manifest.every((m) => m.kind === 'file')).toBe(true);
    expect(manifest[0].file_names).toEqual(['a.csv']);
  });
});
