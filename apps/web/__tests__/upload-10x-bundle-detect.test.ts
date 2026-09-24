import { describe, expect, it } from 'vitest';
import {
  classifyTenxRole,
  displaySampleFolderLabel,
  infer10xSamplePrefix,
  validateTenxPrefixGroup,
  partitionFilesForUploadPlanning,
  uploadFolderKeyFromFile,
} from '@/lib/upload-10x-bundle-detect';

function fileAtRel(name: string, webkitRelativePath: string): File {
  const f = new File([], name);
  Object.defineProperty(f, 'webkitRelativePath', {
    value: webkitRelativePath,
    enumerable: true,
    configurable: true,
  });
  return f;
}

describe('upload-10x-bundle-detect', () => {
  it('infers prefix from standard names', () => {
    expect(infer10xSamplePrefix('donor1_matrix.mtx')).toBe('donor1');
    expect(infer10xSamplePrefix('tumorA_barcodes.tsv.gz')).toBe('tumorA');
  });

  it('classifies roles', () => {
    expect(classifyTenxRole('x_matrix.mtx.gz')).toBe('matrix');
    expect(classifyTenxRole('x_barcodes.tsv')).toBe('barcodes');
    expect(classifyTenxRole('x_features.tsv.gz')).toBe('features');
    expect(classifyTenxRole('x_genes.tsv')).toBe('genes');
    expect(classifyTenxRole('readme.txt')).toBe(null);
  });

  it('validates a complete prefix group', () => {
    const files = [
      new File([], 'p_matrix.mtx'),
      new File([], 'p_barcodes.tsv'),
      new File([], 'p_genes.tsv'),
    ];
    const { tenxGroups } = partitionFilesForUploadPlanning(files);
    expect(tenxGroups).toHaveLength(1);
    expect(validateTenxPrefixGroup(tenxGroups[0]).valid).toBe(true);
  });

  it('rejects two matrices in one prefix group', () => {
    const files = [
      new File([], 'm1.mtx'),
      new File([], 'm2.mtx'),
      new File([], 'barcodes.tsv'),
      new File([], 'genes.tsv'),
    ];
    const { tenxGroups } = partitionFilesForUploadPlanning(files);
    expect(tenxGroups).toHaveLength(1);
    expect(validateTenxPrefixGroup(tenxGroups[0]).valid).toBe(false);
  });

  it('splits unprefixed 10x triplets by folder when webkitRelativePath is set', () => {
    const files = [
      fileAtRel('matrix.mtx', 'GSM5793824/matrix.mtx'),
      fileAtRel('barcodes.tsv', 'GSM5793824/barcodes.tsv'),
      fileAtRel('features.tsv', 'GSM5793824/features.tsv'),
      fileAtRel('matrix.mtx', 'GSM5793825/matrix.mtx'),
      fileAtRel('barcodes.tsv', 'GSM5793825/barcodes.tsv'),
      fileAtRel('features.tsv', 'GSM5793825/features.tsv'),
    ];
    const { tenxGroups } = partitionFilesForUploadPlanning(files);
    expect(tenxGroups).toHaveLength(2);
    expect(tenxGroups.every((g) => validateTenxPrefixGroup(g).valid)).toBe(true);
    const labels = tenxGroups.map((g) => displaySampleFolderLabel(g.folderKey)).sort();
    expect(labels).toEqual(['GSM5793824', 'GSM5793825']);
  });

  it('uploadFolderKeyFromFile reads parent directory from relative path', () => {
    const f = fileAtRel('x.mtx', 'Input/Benign/GSM1/matrix.mtx');
    expect(uploadFolderKeyFromFile(f)).toBe('Input/Benign/GSM1');
    expect(displaySampleFolderLabel('Input/Benign/GSM1')).toBe('GSM1');
  });
});
