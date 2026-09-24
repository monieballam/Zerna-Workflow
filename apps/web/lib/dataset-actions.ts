'use server';

import { redirect } from 'next/navigation';
import { getAuthToken } from './auth';
import { getAuthenticatedApiClientForServerAction } from './server-auth-session';

/** Map FastAPI ``detail`` (string or validation list) to a single message. */
function detailFromApiBody(body: unknown): string | null {
  if (body && typeof body === 'object' && body !== null && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      const parts = detail.map((item) => {
        if (item && typeof item === 'object' && item !== null && 'msg' in item) {
          return String((item as { msg: unknown }).msg);
        }
        return JSON.stringify(item);
      });
      if (parts.length > 0) return parts.join(' ');
    }
  }
  if (typeof body === 'string' && body.trim()) {
    try {
      const parsed = JSON.parse(body) as unknown;
      return detailFromApiBody(parsed);
    } catch {
      return body;
    }
  }
  return null;
}

/**
 * Prefer FastAPI ``detail`` over generic ``Zerna API error 400``.
 * Uses duck-typing (status + body) so bundled server code does not miss ``instanceof ApiResponseError``.
 */
function formatZernaApiError(err: unknown): string {
  if (
    typeof err === 'object' &&
    err !== null &&
    'status' in err &&
    typeof (err as { status: unknown }).status === 'number' &&
    'body' in err
  ) {
    const status = (err as { status: number }).status;
    const fromBody = detailFromApiBody((err as { body: unknown }).body);
    if (fromBody) {
      if (status === 401 && /invalid or expired token/i.test(fromBody)) {
        return (
          'Your session expired (common if this page was open a long time before upload). ' +
          'Log in again, then retry. If it keeps happening, check that the API and web app share the same JWT settings.'
        );
      }
      return fromBody;
    }
  }
  if (err instanceof Error) return err.message;
  return 'Upload failed. Please try again.';
}

export interface UploadDatasetState {
  error?: string;
  fieldErrors?: Record<string, string>;
}

const SERVER_API_BASE_URL =
  process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const ACCEPTED_FORMATS = new Set(['.h5ad', '.h5', '.mtx', '.csv', '.tsv', '.gz', '.txt']);

function validateExtension(filename: string): boolean {
  if (!filename) return false;
  const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase();
  return ACCEPTED_FORMATS.has(ext);
}

function parseList(raw: string | undefined): string[] | undefined {
  if (!raw?.trim()) return undefined;
  const parts = raw
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  return parts.length ? parts : undefined;
}

function stemFileName(filename: string): string {
  let name = filename;
  while (/\.(gz|bz2)$/i.test(name)) {
    name = name.replace(/\.(gz|bz2)$/i, '');
  }
  const dot = name.lastIndexOf('.');
  if (dot > 0) name = name.slice(0, dot);
  return name.trim() || 'sample';
}

type ManifestEntry = {
  kind?: string;
  dataset_name?: string;
  condition?: string;
  sample_id?: string;
  tissue?: string;
  platform?: string;
  bundle_prefix?: string;
  /** When set, upload order must match: row1 files, then row2 files, etc. */
  file_names?: string[];
};

function parseManifestJson(raw: string | null): ManifestEntry[] | null {
  if (!raw?.trim()) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return null;
    return parsed.filter((x) => x && typeof x === 'object') as ManifestEntry[];
  } catch {
    return null;
  }
}

type NormalizedPerFile = {
  dataset_name: string;
  condition: string;
  sample_id: string;
  tissue: string;
  platform: string;
};

function manifestHasFileNameLists(manifest: ManifestEntry[]): boolean {
  return manifest.some((row) => Array.isArray(row.file_names) && row.file_names.length > 0);
}

/**
 * New uploads: each manifest row lists `file_names` in the same order files appear in the form.
 * One row can list multiple files (10x bundle). Legacy: one row per file, no `file_names`.
 */
function normalizePerFileMeta(
  files: File[],
  manifest: ManifestEntry[] | null,
  options: {
    legacyLabels?: string[];
    legacyConds?: string[];
    legacyGlobalCondition?: string;
  }
): { rows: NormalizedPerFile[]; manifestRows?: ManifestEntry[]; error?: string } {
  const { legacyLabels, legacyConds, legacyGlobalCondition } = options;

  if (manifest && manifest.length > 0 && manifestHasFileNameLists(manifest)) {
    let cursor = 0;
    const rows: NormalizedPerFile[] = [];
    for (let r = 0; r < manifest.length; r++) {
      const entry = manifest[r];
      const names = entry.file_names;
      if (!names || names.length === 0) {
        return {
          rows: [],
          error: `Manifest row ${r + 1} is missing file_names.`,
        };
      }
      for (const expectedName of names) {
        if (cursor >= files.length) {
          return { rows: [], error: 'Manifest references more files than were uploaded.' };
        }
        if (files[cursor].name !== expectedName) {
          return {
            rows: [],
            error: `File order mismatch at position ${cursor + 1}: expected ${expectedName}, got ${files[cursor].name}.`,
          };
        }
        cursor++;
      }
      const dn = String(entry.dataset_name ?? '').trim();
      if (!dn) {
        return {
          rows: [],
          error: `Dataset name is required for manifest row ${r + 1} (${entry.kind === 'bundle' ? 'bundle' : 'file'}).`,
        };
      }
      const condition = String(entry.condition ?? '').trim();
      const sample_id = String(entry.sample_id ?? '').trim();
      const tissue = String(entry.tissue ?? '').trim();
      const platform = String(entry.platform ?? '').trim();
      rows.push({
        dataset_name: dn,
        condition,
        sample_id,
        tissue,
        platform,
      });
    }
    if (cursor !== files.length) {
      return {
        rows: [],
        error: 'Manifest does not list every uploaded file. Re-select files and refresh metadata.',
      };
    }
    return { rows, manifestRows: manifest };
  }

  let effective: ManifestEntry[] | null = manifest;
  if (!effective || effective.length !== files.length) {
    if (files.length === 1) {
      const f = files[0];
      effective = [
        {
          dataset_name:
            legacyLabels?.[0]?.trim() ||
            stemFileName(typeof f.name === 'string' ? f.name : 'sample'),
          condition: legacyConds?.[0]?.trim() || legacyGlobalCondition || '',
        },
      ];
    } else if (
      legacyLabels &&
      legacyLabels.length === files.length &&
      (!legacyConds || legacyConds.length === 0 || legacyConds.length === files.length)
    ) {
      effective = files.map((_, i) => ({
        dataset_name: legacyLabels[i],
        condition:
          legacyConds && legacyConds.length === files.length ? legacyConds[i] : legacyLabels[i],
      }));
    } else {
      return {
        rows: [],
        error:
          'Each uploaded file needs metadata. Re-select files and fill in per-file names, or use the same number of legacy sample names as files.',
      };
    }
  }

  const rows: NormalizedPerFile[] = [];
  for (let i = 0; i < files.length; i++) {
    const entry = effective[i] ?? {};
    const dn = String(entry.dataset_name ?? '').trim() || stemFileName(files[i].name);
    if (!dn) {
      return { rows: [], error: `Dataset name is required for file ${i + 1} (${files[i].name}).` };
    }
    const condition = String(entry.condition ?? '').trim();
    const sample_id = String(entry.sample_id ?? '').trim();
    const tissue = String(entry.tissue ?? '').trim();
    const platform = String(entry.platform ?? '').trim();
    rows.push({
      dataset_name: dn,
      condition,
      sample_id,
      tissue,
      platform,
    });
  }
  return { rows, manifestRows: effective };
}

/**
 * One dataset upload: multiple files are merged for a single pipeline run.
 * Per-file rows come from `file_upload_manifest` (JSON) or legacy sample_labels / sample_conditions.
 */
export async function uploadDatasetAction(
  _prevState: UploadDatasetState,
  formData: FormData
): Promise<UploadDatasetState> {
  const name = (formData.get('name') as string | null)?.trim();
  const description = (formData.get('description') as string | null)?.trim() || undefined;
  const legacyCondition = (formData.get('condition') as string | null)?.trim() || undefined;
  const sampleLabels = parseList((formData.get('sample_labels') as string | null) ?? undefined);
  const sampleConditions = parseList(
    (formData.get('sample_conditions') as string | null) ?? undefined
  );
  const files = (formData.getAll('files') as File[]).filter((f) => f instanceof File && f.size > 0);

  const fieldErrors: Record<string, string> = {};

  if (!name) fieldErrors.name = 'Dataset name is required.';
  if (files.length === 0) fieldErrors.files = 'At least one file is required.';

  const invalidFiles = files.filter((f) => !validateExtension(f.name));
  if (invalidFiles.length > 0) {
    fieldErrors.files = `Unsupported format: ${invalidFiles.map((f) => f.name).join(', ')}. Accepted: .h5ad, .h5, .mtx, .csv, .tsv, .gz, .txt`;
  }

  const manifest = parseManifestJson(formData.get('file_upload_manifest') as string | null);

  const usesFileLists = Boolean(manifest?.length && manifestHasFileNameLists(manifest));
  if (
    manifest &&
    manifest.length > 0 &&
    !usesFileLists &&
    manifest.length !== files.length &&
    !fieldErrors.files
  ) {
    fieldErrors.files = `Per-file metadata count (${manifest.length}) must match files (${files.length}).`;
  }

  const alignedManifest =
    manifest && (usesFileLists || manifest.length === files.length) ? manifest : null;

  if (
    !alignedManifest &&
    files.length > 1 &&
    sampleLabels &&
    sampleLabels.length > 0 &&
    sampleLabels.length !== files.length
  ) {
    fieldErrors.sample_labels = `Provide exactly one sample name per file (${files.length} files), or leave blank.`;
  }
  if (
    !alignedManifest &&
    files.length > 1 &&
    sampleConditions &&
    sampleConditions.length > 0 &&
    sampleConditions.length !== files.length
  ) {
    fieldErrors.sample_conditions = `Provide exactly one condition per file (${files.length} files), or leave blank.`;
  }

  const metadataRaw = formData.get('metadata') as string | null;
  const metadata: Record<string, unknown> = {};
  if (metadataRaw) {
    for (const pair of metadataRaw.split(',')) {
      const [k, v] = pair.split('=').map((s) => s.trim());
      if (k && v !== undefined) metadata[k] = v;
    }
  }

  if (Object.keys(fieldErrors).length > 0) {
    return { fieldErrors };
  }

  const relRaw = formData.get('file_relative_paths');
  let fileRelativePaths: string[] | undefined;
  if (typeof relRaw === 'string' && relRaw.trim()) {
    try {
      const parsed = JSON.parse(relRaw) as unknown;
      if (Array.isArray(parsed) && parsed.every((x) => typeof x === 'string')) {
        fileRelativePaths = parsed;
      }
    } catch {
      return { fieldErrors: { files: 'Invalid file_relative_paths payload; re-select files.' } };
    }
  }
  if (fileRelativePaths && fileRelativePaths.length !== files.length) {
    return {
      fieldErrors: {
        files: `Stored path list length (${fileRelativePaths.length}) does not match files (${files.length}). Re-select files and submit again.`,
      },
    };
  }

  const uploadPathOpts =
    fileRelativePaths && fileRelativePaths.length === files.length
      ? { fileRelativePaths }
      : undefined;

  const {
    rows: perFileRows,
    manifestRows,
    error: manifestError,
  } = normalizePerFileMeta(files, alignedManifest, {
    legacyLabels: sampleLabels,
    legacyConds: sampleConditions,
    legacyGlobalCondition: legacyCondition,
  });

  if (manifestError) {
    return { fieldErrors: { files: manifestError } };
  }

  if (perFileRows.length > 0) {
    metadata.per_file_upload_metadata = perFileRows.map((r, i) => {
      const src = manifestRows?.[i];
      return {
        dataset_name: r.dataset_name,
        condition: r.condition,
        ...(r.sample_id ? { sample_id: r.sample_id } : {}),
        ...(r.tissue ? { tissue: r.tissue } : {}),
        ...(r.platform ? { platform: r.platform } : {}),
        ...(src?.kind ? { unit_kind: src.kind } : {}),
        ...(src?.bundle_prefix !== undefined && src.bundle_prefix !== ''
          ? { bundle_prefix: src.bundle_prefix }
          : {}),
        ...(src?.file_names?.length ? { file_names: src.file_names } : {}),
      };
    });
    metadata.expression_dataset_names = perFileRows.map((r) => r.dataset_name);
    metadata.expression_sample_labels = perFileRows.map((r) => r.sample_id || r.dataset_name);
    metadata.expression_sample_conditions = perFileRows.map((r) =>
      r.condition ? r.condition : r.sample_id || r.dataset_name
    );
    const firstCond = perFileRows.find((r) => r.condition)?.condition;
    if (files.length === 1 && firstCond) {
      metadata.condition = firstCond;
    } else if (legacyCondition && files.length === 1) {
      metadata.condition = legacyCondition;
    }
  }

  try {
    const session = await getAuthenticatedApiClientForServerAction();
    if ('error' in session) {
      return { error: session.error };
    }
    const { client } = session;
    const dataset = await client.datasets.create({
      name: name!,
      description,
      metadata: Object.keys(metadata).length > 0 ? metadata : undefined,
    });

    try {
      if (files.length > 0) {
        await client.datasets.createVersion(dataset.id, files, uploadPathOpts);
      }
    } catch (err) {
      const token = getAuthToken();
      try {
        await fetch(`${SERVER_API_BASE_URL}/v1/datasets/${dataset.id}`, {
          method: 'DELETE',
          headers: {
            'content-type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            run_delete_mode: 'preserve',
            run_ids: [],
          }),
          cache: 'no-store',
        });
      } catch {
        // Best-effort cleanup; surface the original upload/version error below.
      }
      throw err;
    }
  } catch (err: unknown) {
    return { error: formatZernaApiError(err) };
  }

  redirect(`/datasets`);
}
