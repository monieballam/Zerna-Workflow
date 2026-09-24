/** Client-side staged dataset units for upload: single files or 10x MTX bundles. */

import {
  displaySampleFolderLabel,
  partitionFilesForUploadPlanning,
  sortBundleFilesForUpload,
  uploadFolderKeyFromFile,
  validateTenxPrefixGroup,
  type TenxPrefixGroup,
} from '@/lib/upload-10x-bundle-detect';
import { uploadFileStableKey } from '@/lib/upload-file-stable-key';

export function fileStableKey(f: File): string {
  return uploadFileStableKey(f);
}

export function defaultDatasetNameFromFilename(fileName: string): string {
  let name = fileName;
  while (/\.(gz|bz2)$/i.test(name)) {
    name = name.replace(/\.(gz|bz2)$/i, '');
  }
  const dot = name.lastIndexOf('.');
  if (dot > 0) name = name.slice(0, dot);
  return name.trim() || 'sample';
}

function newClientId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `id-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export type StagedUploadFileUnit = {
  id: string;
  kind: 'file';
  file: File;
  datasetName: string;
  condition: string;
  sampleId: string;
  tissue: string;
  platform: string;
};

export type StagedUploadBundleUnit = {
  id: string;
  kind: 'bundle';
  /** Prefix from filenames (empty string if unprefixed single bundle). */
  bundlePrefix: string;
  /** When set, bundle was split by folder (e.g. GSM accession). Shown in the review card. */
  sampleFolderLabel?: string;
  files: File[];
  datasetName: string;
  condition: string;
  sampleId: string;
  tissue: string;
  platform: string;
};

export type StagedUploadUnit = StagedUploadFileUnit | StagedUploadBundleUnit;

function bundleStableKey(files: File[]): string {
  return [...files].map(fileStableKey).sort().join('|');
}

function defaultNameForBundle(prefix: string): string {
  return (prefix || 'sample').trim() || 'sample';
}

function defaultLabelForTenxGroup(g: TenxPrefixGroup): string {
  if (g.prefix.trim()) {
    return defaultNameForBundle(g.prefix);
  }
  if (g.folderKey.trim()) {
    return displaySampleFolderLabel(g.folderKey);
  }
  return defaultNameForBundle('');
}

function defaultStandaloneDatasetName(file: File): string {
  const fk = uploadFolderKeyFromFile(file);
  if (fk) {
    return displaySampleFolderLabel(fk);
  }
  return defaultDatasetNameFromFilename(file.name);
}

/**
 * Build staged units from a flat file list: valid 10x prefix groups → bundle units;
 * everything else → file units.
 */
export function filesToStagedUnits(files: File[]): StagedUploadUnit[] {
  const { tenxGroups, standaloneFiles } = partitionFilesForUploadPlanning(files);
  const units: StagedUploadUnit[] = [];

  for (const g of tenxGroups) {
    const v = validateTenxPrefixGroup(g);
    if (v.valid) {
      const sorted = sortBundleFilesForUpload(g.files);
      const folderLabel = g.folderKey.trim() ? displaySampleFolderLabel(g.folderKey) : undefined;
      units.push({
        id: newClientId(),
        kind: 'bundle',
        bundlePrefix: g.prefix,
        ...(folderLabel ? { sampleFolderLabel: folderLabel } : {}),
        files: sorted,
        datasetName: defaultLabelForTenxGroup(g),
        condition: '',
        sampleId: '',
        tissue: '',
        platform: '',
      });
    } else {
      for (const f of g.files) {
        units.push({
          id: newClientId(),
          kind: 'file',
          file: f,
          datasetName: defaultStandaloneDatasetName(f),
          condition: '',
          sampleId: '',
          tissue: '',
          platform: '',
        });
      }
    }
  }

  for (const f of standaloneFiles) {
    units.push({
      id: newClientId(),
      kind: 'file',
      file: f,
      datasetName: defaultStandaloneDatasetName(f),
      condition: '',
      sampleId: '',
      tissue: '',
      platform: '',
    });
  }

  return units;
}

/**
 * Reconcile next file list with previous units: preserve metadata when the same
 * files/bundles are still present.
 */
export function reconcileStagedUnits(
  prev: StagedUploadUnit[],
  nextFiles: File[]
): StagedUploadUnit[] {
  const nextPlanned = filesToStagedUnits(nextFiles);

  const prevFileByKey = new Map<string, StagedUploadFileUnit>();
  const prevBundleByKey = new Map<string, StagedUploadBundleUnit>();
  for (const u of prev) {
    if (u.kind === 'file') {
      prevFileByKey.set(fileStableKey(u.file), u);
    } else {
      prevBundleByKey.set(bundleStableKey(u.files), u);
    }
  }

  return nextPlanned.map((unit) => {
    if (unit.kind === 'file') {
      const key = fileStableKey(unit.file);
      const old = prevFileByKey.get(key);
      if (old) {
        return { ...old, file: unit.file };
      }
      return unit;
    }
    const key = bundleStableKey(unit.files);
    const old = prevBundleByKey.get(key);
    if (old && old.kind === 'bundle' && unit.kind === 'bundle') {
      return {
        ...old,
        files: sortBundleFilesForUpload(unit.files),
        bundlePrefix: unit.bundlePrefix,
        sampleFolderLabel: unit.sampleFolderLabel,
      };
    }
    return unit;
  });
}

/** Payload for `file_upload_manifest` (JSON). */
export type FileUploadManifestEntry = {
  kind: 'file' | 'bundle';
  dataset_name: string;
  condition: string;
  sample_id?: string;
  tissue?: string;
  platform?: string;
  /** Present for bundles; order matches worker grouping expectations. */
  bundle_prefix?: string;
  file_names?: string[];
};

export function stagedUnitsToManifest(units: StagedUploadUnit[]): FileUploadManifestEntry[] {
  return units.map((u) => {
    if (u.kind === 'bundle') {
      return {
        kind: 'bundle',
        bundle_prefix: u.bundlePrefix,
        file_names: u.files.map((f) => f.name),
        dataset_name: u.datasetName.trim(),
        condition: u.condition.trim(),
        ...(u.sampleId.trim() ? { sample_id: u.sampleId.trim() } : {}),
        ...(u.tissue.trim() ? { tissue: u.tissue.trim() } : {}),
        ...(u.platform.trim() ? { platform: u.platform.trim() } : {}),
      };
    }
    return {
      kind: 'file',
      file_names: [u.file.name],
      dataset_name: u.datasetName.trim(),
      condition: u.condition.trim(),
      ...(u.sampleId.trim() ? { sample_id: u.sampleId.trim() } : {}),
      ...(u.tissue.trim() ? { tissue: u.tissue.trim() } : {}),
      ...(u.platform.trim() ? { platform: u.platform.trim() } : {}),
    };
  });
}

/** Flatten files in manifest row order for FormData.append. */
export function flattenFilesForUploadOrder(units: StagedUploadUnit[]): File[] {
  const out: File[] = [];
  for (const u of units) {
    if (u.kind === 'bundle') {
      out.push(...sortBundleFilesForUpload(u.files));
    } else {
      out.push(u.file);
    }
  }
  return out;
}

function uploadLogicalPathForFile(f: File): string {
  const wr = (f as File & { webkitRelativePath?: string }).webkitRelativePath;
  if (wr && typeof wr === 'string' && wr.trim()) {
    return wr.trim().replace(/\\/g, '/');
  }
  return f.name;
}

/**
 * Logical paths aligned with {@link flattenFilesForUploadOrder} (folder picks → webkitRelativePath).
 * Sent as `file_relative_paths` so API/worker preserve GEO-style sample directories.
 */
export function flattenRelativePathsForUploadOrder(units: StagedUploadUnit[]): string[] {
  const out: string[] = [];
  for (const u of units) {
    if (u.kind === 'bundle') {
      for (const f of sortBundleFilesForUpload(u.files)) {
        out.push(uploadLogicalPathForFile(f));
      }
    } else {
      out.push(uploadLogicalPathForFile(u.file));
    }
  }
  return out;
}

/** @deprecated Use reconcileStagedUnits + StagedUploadUnit */
export type StagedUploadFile = {
  id: string;
  file: File;
  datasetName: string;
  condition: string;
  sampleId: string;
  tissue: string;
  platform: string;
};

/** @deprecated Legacy reconcile; prefer reconcileStagedUnits */
export function reconcileStagedFiles(
  prev: StagedUploadFile[],
  nextFiles: File[]
): StagedUploadFile[] {
  const prevUnits: StagedUploadUnit[] = prev.map((r) => ({
    id: r.id,
    kind: 'file' as const,
    file: r.file,
    datasetName: r.datasetName,
    condition: r.condition,
    sampleId: r.sampleId,
    tissue: r.tissue,
    platform: r.platform,
  }));
  const next = reconcileStagedUnits(prevUnits, nextFiles);
  return next
    .filter((u): u is StagedUploadFileUnit => u.kind === 'file')
    .map((u) => ({
      id: u.id,
      file: u.file,
      datasetName: u.datasetName,
      condition: u.condition,
      sampleId: u.sampleId,
      tissue: u.tissue,
      platform: u.platform,
    }));
}

/** @deprecated */
export function stagedFilesToManifest(rows: StagedUploadFile[]): FileUploadManifestEntry[] {
  return stagedUnitsToManifest(
    rows.map((r) => ({
      id: r.id,
      kind: 'file' as const,
      file: r.file,
      datasetName: r.datasetName,
      condition: r.condition,
      sampleId: r.sampleId,
      tissue: r.tissue,
      platform: r.platform,
    }))
  );
}
