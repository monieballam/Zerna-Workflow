import type { StagedUploadUnit } from '@/lib/upload-dataset-staged-files';

export type LogicalDatasetSummary = {
  totalUnits: number;
  bundleUnits: number;
  fileUnits: number;
  rawFileCount: number;
};

export function deriveLogicalDatasetSummary(staged: StagedUploadUnit[]): LogicalDatasetSummary {
  let rawFileCount = 0;
  let bundleUnits = 0;
  for (const u of staged) {
    if (u.kind === 'bundle') {
      bundleUnits += 1;
      rawFileCount += u.files.length;
    } else {
      rawFileCount += 1;
    }
  }
  return {
    totalUnits: staged.length,
    bundleUnits,
    fileUnits: staged.length - bundleUnits,
    rawFileCount,
  };
}

/** Bullet lines for the logical dataset summary panel (compact). */
export function formatLogicalDatasetSummaryLines(s: LogicalDatasetSummary): string[] {
  if (s.totalUnits === 0) return [];

  const lines: string[] = [];
  lines.push(`${s.totalUnits} logical dataset${s.totalUnits === 1 ? '' : 's'} ready`);

  if (s.bundleUnits > 0 && s.fileUnits > 0) {
    lines.push(
      `${s.bundleUnits} detected as 10x bundle${s.bundleUnits === 1 ? '' : 's'}`,
      `${s.fileUnits} detected as file-based upload${s.fileUnits === 1 ? '' : 's'}`
    );
  } else if (s.bundleUnits > 0) {
    lines.push(`${s.bundleUnits} detected as 10x bundle${s.bundleUnits === 1 ? '' : 's'}`);
  } else {
    lines.push(`${s.fileUnits} detected as file-based upload${s.fileUnits === 1 ? '' : 's'}`);
  }

  lines.push(`${s.rawFileCount} raw file${s.rawFileCount === 1 ? '' : 's'} uploaded`);
  return lines;
}

/** Short sentence above the submit button. */
export function formatSubmitConfirmationLine(s: LogicalDatasetSummary): string {
  if (s.totalUnits === 0) return '';

  if (s.bundleUnits > 0 && s.fileUnits > 0) {
    return `This run will analyze ${s.totalUnits} logical datasets (${s.bundleUnits} 10x bundle${s.bundleUnits === 1 ? '' : 's'} and ${s.fileUnits} file-based).`;
  }
  if (s.bundleUnits > 0) {
    return s.totalUnits === 1
      ? 'This run will analyze 1 logical dataset (one 10x bundle).'
      : `This run will analyze ${s.bundleUnits} logical datasets (10x bundles).`;
  }
  return s.totalUnits === 1
    ? 'This run will analyze 1 logical dataset (file-based upload).'
    : `This run will analyze ${s.fileUnits} logical datasets (file-based uploads).`;
}
