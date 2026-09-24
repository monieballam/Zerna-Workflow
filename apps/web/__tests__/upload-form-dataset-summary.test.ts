import { describe, expect, it } from 'vitest';
import {
  deriveLogicalDatasetSummary,
  formatLogicalDatasetSummaryLines,
  formatSubmitConfirmationLine,
} from '@/lib/upload-form-dataset-summary';
import { filesToStagedUnits } from '@/lib/upload-dataset-staged-files';

describe('upload-form-dataset-summary', () => {
  it('counts bundles, file units, and raw files', () => {
    const staged = filesToStagedUnits([
      new File([], 'a_matrix.mtx'),
      new File([], 'a_barcodes.tsv'),
      new File([], 'a_features.tsv'),
      new File([], 'b.csv'),
    ]);
    expect(staged).toHaveLength(2);
    const s = deriveLogicalDatasetSummary(staged);
    expect(s.totalUnits).toBe(2);
    expect(s.bundleUnits).toBe(1);
    expect(s.fileUnits).toBe(1);
    expect(s.rawFileCount).toBe(4);
  });

  it('formats lines for mixed upload', () => {
    const lines = formatLogicalDatasetSummaryLines({
      totalUnits: 3,
      bundleUnits: 2,
      fileUnits: 1,
      rawFileCount: 7,
    });
    expect(lines[0]).toMatch(/3 logical datasets ready/);
    expect(lines.some((l) => /2 detected as 10x bundles/i.test(l))).toBe(true);
    expect(lines.some((l) => /1 detected as file-based upload/i.test(l))).toBe(true);
    expect(lines.some((l) => /7 raw files uploaded/i.test(l))).toBe(true);
  });

  it('simplifies when only bundles', () => {
    const lines = formatLogicalDatasetSummaryLines({
      totalUnits: 2,
      bundleUnits: 2,
      fileUnits: 0,
      rawFileCount: 6,
    });
    expect(lines).toHaveLength(3);
    expect(lines[1]).toMatch(/2 detected as 10x bundles/);
    expect(lines.some((l) => /file-based/i.test(l))).toBe(false);
  });

  it('simplifies when only file-based', () => {
    const lines = formatLogicalDatasetSummaryLines({
      totalUnits: 3,
      bundleUnits: 0,
      fileUnits: 3,
      rawFileCount: 3,
    });
    expect(lines[1]).toMatch(/3 detected as file-based uploads/);
  });

  it('formats submit confirmation for mixed case', () => {
    const t = formatSubmitConfirmationLine({
      totalUnits: 3,
      bundleUnits: 2,
      fileUnits: 1,
      rawFileCount: 7,
    });
    expect(t).toMatch(/3 logical datasets/);
    expect(t).toMatch(/2 10x bundles/);
    expect(t).toMatch(/1 file-based/);
  });
});
