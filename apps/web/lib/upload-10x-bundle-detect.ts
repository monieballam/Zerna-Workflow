/**
 * Detect and validate 10x MTX-style bundles (shared filename prefix per sample).
 * When the user picks a **folder** (webkitdirectory), files are grouped by parent
 * directory first so unprefixed GEO layouts (e.g. GSM123/matrix.mtx + barcodes + features)
 * become separate bundles per folder.
 *
 * Aligns with worker `_partition_10x_bundles` / `_load_adata` expectations.
 */

export type TenxFileRole = 'matrix' | 'barcodes' | 'features' | 'genes';

/** Parent directory path from `webkitRelativePath`, or '' for flat file picks. */
export function uploadFolderKeyFromFile(file: File): string {
  const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
  if (!rel || typeof rel !== 'string') return '';
  const idx = rel.lastIndexOf('/');
  if (idx <= 0) return '';
  return rel.slice(0, idx);
}

/** Last path segment for default sample labels (e.g. GSM5793824). */
export function displaySampleFolderLabel(folderKey: string): string {
  if (!folderKey.trim()) return '';
  const parts = folderKey.split('/').filter(Boolean);
  return parts[parts.length - 1] ?? folderKey.trim();
}

export function infer10xSamplePrefix(fileName: string): string {
  const name = fileName.trim();
  const patterns = [
    /^(.+?)[._-]matrix\.mtx(\.gz)?$/i,
    /^(.+?)[._-]barcodes\.tsv(\.gz)?$/i,
    /^(.+?)[._-]genes\.tsv(\.gz)?$/i,
    /^(.+?)[._-]features\.tsv(\.gz)?$/i,
  ];
  for (const re of patterns) {
    const m = name.match(re);
    if (m?.[1]) {
      return m[1].replace(/^[._-]+|[._-]+$/g, '').trim();
    }
  }
  return '';
}

export function classifyTenxRole(fileName: string): TenxFileRole | null {
  const l = fileName.toLowerCase();
  if (l.endsWith('.mtx') || l.endsWith('.mtx.gz')) {
    return 'matrix';
  }
  if (l.includes('barcodes') && (l.includes('.tsv') || l.includes('.txt'))) {
    return 'barcodes';
  }
  if (l.includes('features') && (l.includes('.tsv') || l.includes('.txt'))) {
    return 'features';
  }
  if (l.includes('genes') && l.includes('.tsv')) {
    return 'genes';
  }
  return null;
}

export function isTenxBundleCandidate(fileName: string): boolean {
  return classifyTenxRole(fileName) !== null;
}

export type TenxPrefixGroup = {
  prefix: string;
  /**
   * Set when files came from a folder pick (`webkitRelativePath`).
   * Multiple unprefixed 10x triplets are split by this key.
   */
  folderKey: string;
  files: File[];
  roles: Map<string, TenxFileRole>;
};

export function groupFilesByTenxPrefix(files: File[]): TenxPrefixGroup[] {
  const map = new Map<string, File[]>();
  for (const f of files) {
    if (!isTenxBundleCandidate(f.name)) continue;
    const p = infer10xSamplePrefix(f.name);
    const list = map.get(p) ?? [];
    list.push(f);
    map.set(p, list);
  }

  const nonEmpty = [...map.keys()].filter((k) => k !== '');
  const orderedKeys = [...nonEmpty].sort();
  if (map.has('')) orderedKeys.push('');

  return orderedKeys.map((prefix) => {
    const groupFiles = map.get(prefix)!;
    const roles = new Map<string, TenxFileRole>();
    for (const f of groupFiles) {
      const r = classifyTenxRole(f.name);
      if (r) roles.set(f.name, r);
    }
    return { prefix, folderKey: '', files: groupFiles, roles };
  });
}

export type TenxBundleValidation = { valid: true } | { valid: false; reason: string };

/** One matrix, one barcodes, exactly one of features or genes. */
export function validateTenxPrefixGroup(group: TenxPrefixGroup): TenxBundleValidation {
  const matrices = group.files.filter((f) => classifyTenxRole(f.name) === 'matrix');
  const barcodes = group.files.filter((f) => classifyTenxRole(f.name) === 'barcodes');
  const features = group.files.filter((f) => classifyTenxRole(f.name) === 'features');
  const genes = group.files.filter((f) => classifyTenxRole(f.name) === 'genes');

  const bundleLabel =
    group.folderKey.trim() !== ''
      ? displaySampleFolderLabel(group.folderKey)
      : group.prefix || '(unprefixed)';

  if (matrices.length !== 1) {
    return {
      valid: false,
      reason: `Bundle "${bundleLabel}" needs exactly one matrix file; found ${matrices.length}.`,
    };
  }
  if (barcodes.length !== 1) {
    return {
      valid: false,
      reason: `Bundle "${bundleLabel}" needs exactly one barcodes file; found ${barcodes.length}.`,
    };
  }
  const fg = features.length + genes.length;
  if (fg !== 1) {
    return {
      valid: false,
      reason: `Bundle "${bundleLabel}" needs exactly one features or genes file; found ${fg}.`,
    };
  }
  return { valid: true };
}

/** Stable order for appending to FormData: matrix → barcodes → features/genes. */
export function sortBundleFilesForUpload(files: File[]): File[] {
  const roleOrder: TenxFileRole[] = ['matrix', 'barcodes', 'features', 'genes'];
  return [...files].sort((a, b) => {
    const ra = classifyTenxRole(a.name);
    const rb = classifyTenxRole(b.name);
    const ia = ra ? roleOrder.indexOf(ra) : 99;
    const ib = rb ? roleOrder.indexOf(rb) : 99;
    if (ia !== ib) return ia - ib;
    return a.name.localeCompare(b.name);
  });
}

const FLAT_TENX_BUCKET = '__flat_tenx__';

/**
 * Partition upload into 10x bundle groups and standalone (non-10x) files.
 * Every input file appears exactly once in either a group or standalone.
 */
export function partitionFilesForUploadPlanning(allFiles: File[]): {
  tenxGroups: TenxPrefixGroup[];
  standaloneFiles: File[];
} {
  const tenx: File[] = [];
  const standalone: File[] = [];
  for (const f of allFiles) {
    if (isTenxBundleCandidate(f.name)) {
      tenx.push(f);
    } else {
      standalone.push(f);
    }
  }

  const anyFolder = tenx.some((f) => uploadFolderKeyFromFile(f) !== '');
  if (!anyFolder) {
    return {
      tenxGroups: groupFilesByTenxPrefix(tenx),
      standaloneFiles: standalone,
    };
  }

  const buckets = new Map<string, File[]>();
  for (const f of tenx) {
    const fk = uploadFolderKeyFromFile(f);
    const bucket = fk || FLAT_TENX_BUCKET;
    const list = buckets.get(bucket) ?? [];
    list.push(f);
    buckets.set(bucket, list);
  }

  const tenxGroups: TenxPrefixGroup[] = [];
  const bucketKeys = [...buckets.keys()].sort((a, b) => a.localeCompare(b));
  for (const bucketKey of bucketKeys) {
    const bucketFiles = buckets.get(bucketKey)!;
    const folderKey = bucketKey === FLAT_TENX_BUCKET ? '' : bucketKey;
    const sub = groupFilesByTenxPrefix(bucketFiles);
    for (const g of sub) {
      tenxGroups.push({ ...g, folderKey });
    }
  }

  return { tenxGroups, standaloneFiles: standalone };
}
