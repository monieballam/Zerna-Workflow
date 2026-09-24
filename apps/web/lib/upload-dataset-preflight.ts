/**
 * Client-side checks before dataset upload (aligned with worker expectations).
 */

import {
  classifyTenxRole,
  displaySampleFolderLabel,
  infer10xSamplePrefix,
  partitionFilesForUploadPlanning,
  validateTenxPrefixGroup,
  type TenxFileRole,
} from '@/lib/upload-10x-bundle-detect';
import {
  flattenFilesForUploadOrder,
  type StagedUploadUnit,
} from '@/lib/upload-dataset-staged-files';
import { uploadFileStableKey } from '@/lib/upload-file-stable-key';

export type UploadPreflightResult = {
  blockingErrors: string[];
  warnings: string[];
};

function lower(name: string): string {
  return name.toLowerCase();
}

function countH5(fileNames: string[]): number {
  return fileNames.filter((n) => lower(n).endsWith('.h5')).length;
}

function countH5ad(fileNames: string[]): number {
  return fileNames.filter((n) => lower(n).endsWith('.h5ad')).length;
}

/** Path sent as `file_relative_paths` / used for storage keys (folder pick → webkitRelativePath). */
function logicalClientPath(f: File): string {
  const wr = (f as File & { webkitRelativePath?: string }).webkitRelativePath;
  if (wr && typeof wr === 'string' && wr.trim()) {
    return wr.trim().replace(/\\/g, '/');
  }
  return f.name;
}

/**
 * Multi-sample GEO-style 10x (several `matrix.mtx` + barcodes + features) requires either
 * `webkitRelativePath` with directories (Add folder…) or distinct filename prefixes. Click-to-browse,
 * multi-select, and drag-and-drop do not populate `webkitRelativePath`, so we would send duplicate
 * basenames as `file_relative_paths` and the API would overwrite objects — the worker then sees bare
 * names and cannot group samples.
 */
function blockingErrorWhenStandardTenxLosesFolderContext(flat: File[]): string | null {
  const matrices = flat.filter((f) => classifyTenxRole(f.name) === 'matrix');
  if (matrices.length <= 1) return null;

  const folderBacked = matrices.every((f) => logicalClientPath(f).includes('/'));
  const prefixBacked = matrices.every((f) => infer10xSamplePrefix(f.name) !== '');
  if (folderBacked || prefixBacked) return null;

  return (
    'Multiple 10x matrix files use the same standard names (e.g. matrix.mtx.gz) but no folder ' +
    'paths were captured. Your browser only adds those paths when you use **Add folder…** ' +
    '(pick a parent directory that contains one subfolder per sample). ' +
    'Plain **Click to browse**, multi-file selection, and **drag-and-drop** do not preserve sample ' +
    'folders. Either use Add folder…, or rename files with a per-sample prefix ' +
    '(e.g. GSM123_matrix.mtx.gz and GSM123_barcodes.tsv.gz).'
  );
}

/** Duplicate logical paths would collide on object storage when used as keys. */
function blockingErrorOnDuplicateLogicalPaths(flat: File[]): string | null {
  const paths = flat.map(logicalClientPath);
  const seen = new Set<string>();
  for (const p of paths) {
    if (seen.has(p)) {
      const base = p.split('/').pop() ?? p;
      if (classifyTenxRole(base) !== null) {
        return (
          `Duplicate upload path "${p}" would overwrite another file in storage. ` +
          'Use **Add folder…** so each file has a unique path, or rename so names differ.'
        );
      }
      return (
        `Duplicate upload path "${p}" would overwrite another file in storage. ` +
        'Rename files or upload via a folder selection so paths are unique.'
      );
    }
    seen.add(p);
  }
  return null;
}

export function evaluateUploadPreflight(units: StagedUploadUnit[]): UploadPreflightResult {
  const blockingErrors: string[] = [];
  const warnings: string[] = [];

  if (units.length === 0) {
    return { blockingErrors, warnings };
  }

  const flat = flattenFilesForUploadOrder(units);
  const names = flat.map((f) => f.name);

  const tenxPathBlock = blockingErrorWhenStandardTenxLosesFolderContext(flat);
  if (tenxPathBlock) blockingErrors.push(tenxPathBlock);
  const dupPathBlock = blockingErrorOnDuplicateLogicalPaths(flat);
  if (dupPathBlock) blockingErrors.push(dupPathBlock);

  const byName = new Map<string, File[]>();
  for (const f of flat) {
    const list = byName.get(f.name) ?? [];
    list.push(f);
    byName.set(f.name, list);
  }
  const duplicateList = [...byName.entries()]
    .filter(([, arr]) => {
      if (arr.length <= 1) return false;
      const keys = new Set(arr.map((f) => uploadFileStableKey(f)));
      return keys.size < arr.length;
    })
    .map(([n]) => n);
  if (duplicateList.length > 0) {
    warnings.push(
      `Duplicate file name(s): ${duplicateList.join(', ')}. If these are different files, use Add folder so each path is unique, or rename before upload.`
    );
  }

  const { tenxGroups } = partitionFilesForUploadPlanning(flat);
  const pickTenx = (g: (typeof tenxGroups)[0], role: TenxFileRole) =>
    g.files.find((f) => classifyTenxRole(f.name) === role);
  const relFor = (f: File) =>
    (f as File & { webkitRelativePath?: string }).webkitRelativePath?.trim() || f.name;

  for (const g of tenxGroups) {
    const v = validateTenxPrefixGroup(g);
    if (!v.valid) {
      blockingErrors.push(v.reason);
      continue;
    }
    const sampleId =
      g.folderKey.trim() !== ''
        ? displaySampleFolderLabel(g.folderKey)
        : g.prefix.trim() || '(single bundle)';
    const matrix = pickTenx(g, 'matrix');
    const barcodes = pickTenx(g, 'barcodes');
    const feat = pickTenx(g, 'features') ?? pickTenx(g, 'genes');
    if (matrix && barcodes && feat) {
      warnings.push(
        `10x MTX (preflight): sample_id=${sampleId}; matrix=${relFor(matrix)}; barcodes=${relFor(barcodes)}; features/genes=${relFor(feat)}; bundle_complete=yes`
      );
    }
  }

  if (countH5(names) > 1) {
    warnings.push(
      'Multi-file 10x .h5 uploads do not yet support full per-file metadata alignment. Use grouped MTX bundles with prefixes, separate runs, or another supported multi-dataset format.'
    );
  }

  const nH5ad = countH5ad(names);
  if (nH5ad > 1 && flat.length !== nH5ad) {
    blockingErrors.push(
      `Multiple H5AD files detected (${nH5ad}) but total staged files (${flat.length}) differs — each H5AD should be the only files in the upload, or add only H5ADs with one metadata row per file.`
    );
  }

  if (units.some((u) => !u.datasetName.trim())) {
    blockingErrors.push(
      'Each dataset sample (file or 10x bundle) needs a non-empty dataset name before upload.'
    );
  }

  return { blockingErrors, warnings };
}
