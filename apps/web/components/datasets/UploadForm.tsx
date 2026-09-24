'use client';

import { useCallback, useMemo, useState, useTransition } from 'react';
import { useFormState } from 'react-dom';
import { uploadDatasetAction, type UploadDatasetState } from '@/lib/dataset-actions';
import { evaluateUploadPreflight } from '@/lib/upload-dataset-preflight';
import {
  type StagedUploadUnit,
  flattenFilesForUploadOrder,
  flattenRelativePathsForUploadOrder,
  reconcileStagedUnits,
  stagedUnitsToManifest,
} from '@/lib/upload-dataset-staged-files';
import {
  deriveLogicalDatasetSummary,
  formatLogicalDatasetSummaryLines,
  formatSubmitConfirmationLine,
} from '@/lib/upload-form-dataset-summary';
import { classifyTenxRole, type TenxFileRole } from '@/lib/upload-10x-bundle-detect';
import FileDropZone from './FileDropZone';

const initialState: UploadDatasetState = {};

type UnitMetaPatch = Partial<
  Pick<StagedUploadUnit, 'datasetName' | 'condition' | 'sampleId' | 'tissue' | 'platform'>
>;

export default function UploadForm() {
  // Next 14's production build still requires the react-dom form action hook.
  const [state, formAction] = useFormState(uploadDatasetAction, initialState);
  const [isPending, startTransition] = useTransition();
  const [staged, setStaged] = useState<StagedUploadUnit[]>([]);

  const files = useMemo(() => flattenFilesForUploadOrder(staged), [staged]);
  const hasBundles = useMemo(() => staged.some((u) => u.kind === 'bundle'), [staged]);

  const preflight = useMemo(() => evaluateUploadPreflight(staged), [staged]);

  const logicalSummary = useMemo(() => deriveLogicalDatasetSummary(staged), [staged]);
  const summaryLines = useMemo(
    () => formatLogicalDatasetSummaryLines(logicalSummary),
    [logicalSummary]
  );
  const submitConfirmationLine = useMemo(
    () => formatSubmitConfirmationLine(logicalSummary),
    [logicalSummary]
  );

  const onFilesChange = useCallback((nextFiles: File[]) => {
    setStaged((prev) => reconcileStagedUnits(prev, nextFiles));
  }, []);

  const updateUnit = useCallback((id: string, patch: UnitMetaPatch) => {
    setStaged((prev) => prev.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  }, []);

  const removeUnit = useCallback((id: string) => {
    setStaged((prev) => prev.filter((row) => row.id !== id));
  }, []);

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const fd = new FormData(form);
    fd.delete('files');
    for (const f of flattenFilesForUploadOrder(staged)) {
      fd.append('files', f);
    }
    fd.set('file_upload_manifest', JSON.stringify(stagedUnitsToManifest(staged)));
    fd.set('file_relative_paths', JSON.stringify(flattenRelativePathsForUploadOrder(staged)));
    startTransition(() => {
      void formAction(fd);
    });
  }

  function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {state.error && (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {state.error}
        </div>
      )}

      <p className="rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-sm text-gray-600">
        Upload <strong>all samples you want in one analysis</strong> as a single dataset. Files are
        merged into one object for <strong>one pipeline run</strong>.
        <span className="mt-2 block text-xs text-gray-600">
          <strong>10x MTX:</strong> use <strong>Add folder</strong> when each sample lives in its
          own subfolder (GEO-style: <code className="text-xs">GSM…/matrix.mtx</code> + barcodes +
          features with no filename prefix). The dashboard groups by folder so each sample stays
          separate. Alternatively, use a shared filename prefix per sample (e.g.{' '}
          <code className="text-xs">donor1_matrix.mtx</code>,{' '}
          <code className="text-xs">donor1_barcodes.tsv</code>). <strong>Other formats</strong>{' '}
          (H5AD, etc.) stay one row per file; folder picks default the sample name from the parent
          folder. <strong>Multiple 10x .h5</strong> files still have limited per-file metadata
          alignment in the worker.
        </span>
      </p>

      {preflight.blockingErrors.length > 0 && (
        <div
          role="alert"
          data-testid="upload-preflight-blocking"
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
        >
          <p className="font-medium">Fix before upload:</p>
          <ul className="mt-2 list-inside list-disc space-y-1">
            {preflight.blockingErrors.map((msg) => (
              <li key={msg}>{msg}</li>
            ))}
          </ul>
        </div>
      )}

      {preflight.warnings.length > 0 && (
        <div
          role="status"
          data-testid="upload-preflight-warnings"
          className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
        >
          <p className="font-medium">Heads-up</p>
          <ul className="mt-2 list-inside list-disc space-y-1">
            {preflight.warnings.map((msg) => (
              <li key={msg}>{msg}</li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <label htmlFor="name" className="mb-1 block text-sm font-medium text-gray-700">
          Combined dataset name{' '}
          <span aria-hidden="true" className="text-red-500">
            *
          </span>
        </label>
        <input
          id="name"
          name="name"
          type="text"
          required
          placeholder="e.g. BMET tumor + distal (combined)"
          className={`input w-full ${state.fieldErrors?.name ? 'border-red-400' : ''}`}
        />
        {state.fieldErrors?.name && (
          <p className="mt-1 text-sm text-red-600">{state.fieldErrors.name}</p>
        )}
        <p className="mt-1 text-xs text-gray-400">
          This is the name of the dataset record in Zerna (all files together).
        </p>
      </div>

      <div>
        <label htmlFor="description" className="mb-1 block text-sm font-medium text-gray-700">
          Description
        </label>
        <textarea
          id="description"
          name="description"
          rows={2}
          placeholder="Optional"
          className="input w-full resize-none"
        />
      </div>

      <div>
        <p className="mb-1 block text-sm font-medium text-gray-700">
          Files{' '}
          <span aria-hidden="true" className="text-red-500">
            *
          </span>
        </p>
        <FileDropZone
          error={state.fieldErrors?.files}
          value={files}
          onChange={onFilesChange}
          hideFileList
        />
      </div>

      {staged.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-900">
            {hasBundles ? 'Per-sample metadata' : 'Per-file metadata'}
          </h2>
          <p className="text-xs text-gray-600">
            <strong>Metadata is assigned per logical dataset.</strong> For 10x uploads, one bundle
            is treated as one dataset—one dataset name and condition apply to all cells from that
            bundle.
          </p>
          <p className="text-xs text-gray-500">
            {hasBundles ? (
              <>
                Values map to <code className="text-xs">obs[&apos;dataset_name&apos;]</code>,{' '}
                <code className="text-xs">obs[&apos;condition&apos;]</code>, and{' '}
                <code className="text-xs">obs[&apos;sample&apos;]</code> for every cell in that
                logical dataset.
              </>
            ) : (
              <>
                Each file is one logical dataset. Labels are written to{' '}
                <code className="text-xs">obs[&apos;dataset_name&apos;]</code>,{' '}
                <code className="text-xs">obs[&apos;condition&apos;]</code>, and{' '}
                <code className="text-xs">obs[&apos;sample&apos;]</code> (sample defaults to dataset
                name unless you set sample ID).
              </>
            )}
          </p>
          <ul className="space-y-4">
            {staged.map((row) => (
              <li
                key={row.id}
                className="rounded-xl border border-gray-200 bg-gray-50 p-4 shadow-sm"
                data-testid={`upload-unit-${row.id}`}
                data-unit-kind={row.kind}
              >
                <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    {row.kind === 'bundle' ? (
                      <>
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            data-testid={`unit-type-badge-${row.id}`}
                            className="inline-flex rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-semibold text-violet-900"
                          >
                            10x bundle
                          </span>
                          <span className="text-xs text-gray-600">
                            Prefix:{' '}
                            <span className="font-mono font-medium text-gray-800">
                              {row.bundlePrefix ? row.bundlePrefix : '(unprefixed)'}
                            </span>
                            {row.sampleFolderLabel ? (
                              <>
                                {' '}
                                · folder:{' '}
                                <span className="font-mono font-medium text-gray-800">
                                  {row.sampleFolderLabel}
                                </span>
                              </>
                            ) : null}
                          </span>
                        </div>
                        <p className="mt-2 text-xs font-medium text-gray-700">Included files</p>
                        <dl
                          data-testid={`bundle-included-files-${row.id}`}
                          className="mt-1 space-y-1 font-mono text-xs text-gray-700"
                        >
                          {bundleRoleOrder.map((role) => {
                            const f = row.files.find((x) => classifyTenxRole(x.name) === role);
                            if (!f) return null;
                            return (
                              <div key={role} className="flex gap-2 sm:gap-3">
                                <dt className="w-24 shrink-0 font-sans font-medium text-gray-600">
                                  {bundleRoleLabel(role)}
                                </dt>
                                <dd className="min-w-0 truncate">
                                  {f.name}{' '}
                                  <span className="text-gray-400">({formatSize(f.size)})</span>
                                </dd>
                              </div>
                            );
                          })}
                        </dl>
                      </>
                    ) : (
                      <>
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            data-testid={`unit-type-badge-${row.id}`}
                            className="inline-flex rounded-full bg-slate-200 px-2.5 py-0.5 text-xs font-semibold text-slate-800"
                          >
                            File upload
                          </span>
                        </div>
                        <p className="mt-2 truncate font-mono text-sm font-medium text-gray-800">
                          {row.file.name}
                        </p>
                        <p className="text-xs text-gray-400">{formatSize(row.file.size)}</p>
                      </>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => removeUnit(row.id)}
                    className="shrink-0 rounded-md border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-gray-700 hover:bg-red-50 hover:text-red-700"
                  >
                    {row.kind === 'bundle' ? 'Remove bundle' : 'Remove file'}
                  </button>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <label
                      className="mb-1 block text-xs font-medium text-gray-600"
                      htmlFor={`dataset-name-${row.id}`}
                    >
                      Dataset name{row.kind === 'bundle' ? ' (sample)' : ' (per file)'}{' '}
                      <span className="text-red-500" aria-hidden>
                        *
                      </span>
                    </label>
                    <input
                      id={`dataset-name-${row.id}`}
                      type="text"
                      required
                      value={row.datasetName}
                      onChange={(e) => updateUnit(row.id, { datasetName: e.target.value })}
                      className="input w-full text-sm"
                      placeholder="Label in merged object"
                      aria-label={
                        row.kind === 'bundle'
                          ? `Dataset name for 10x bundle ${row.bundlePrefix || 'sample'}`
                          : `Dataset name for ${row.file.name}`
                      }
                    />
                  </div>
                  <div>
                    <label
                      className="mb-1 block text-xs font-medium text-gray-600"
                      htmlFor={`condition-${row.id}`}
                    >
                      Condition
                    </label>
                    <input
                      id={`condition-${row.id}`}
                      type="text"
                      value={row.condition}
                      onChange={(e) => updateUnit(row.id, { condition: e.target.value })}
                      className="input w-full text-sm"
                      placeholder="e.g. tumor, control (optional)"
                      aria-label={`Condition for ${row.kind === 'bundle' ? row.bundlePrefix : row.file.name}`}
                    />
                  </div>
                  <div>
                    <label
                      className="mb-1 block text-xs font-medium text-gray-600"
                      htmlFor={`sample-id-${row.id}`}
                    >
                      Sample ID <span className="font-normal text-gray-400">(optional)</span>
                    </label>
                    <input
                      id={`sample-id-${row.id}`}
                      type="text"
                      value={row.sampleId}
                      onChange={(e) => updateUnit(row.id, { sampleId: e.target.value })}
                      className="input w-full text-sm"
                      placeholder="obs['sample']; defaults to dataset name"
                      aria-label={`Sample ID for ${row.kind === 'bundle' ? row.bundlePrefix : row.file.name}`}
                    />
                  </div>
                  <div>
                    <label
                      className="mb-1 block text-xs font-medium text-gray-600"
                      htmlFor={`tissue-${row.id}`}
                    >
                      Tissue <span className="font-normal text-gray-400">(optional)</span>
                    </label>
                    <input
                      id={`tissue-${row.id}`}
                      type="text"
                      value={row.tissue}
                      onChange={(e) => updateUnit(row.id, { tissue: e.target.value })}
                      className="input w-full text-sm"
                      placeholder="Reserved for pipeline"
                      aria-label={`Tissue for ${row.kind === 'bundle' ? row.bundlePrefix : row.file.name}`}
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label
                      className="mb-1 block text-xs font-medium text-gray-600"
                      htmlFor={`platform-${row.id}`}
                    >
                      Source / platform{' '}
                      <span className="font-normal text-gray-400">(optional)</span>
                    </label>
                    <input
                      id={`platform-${row.id}`}
                      type="text"
                      value={row.platform}
                      onChange={(e) => updateUnit(row.id, { platform: e.target.value })}
                      className="input w-full text-sm"
                      placeholder="e.g. 10x 3' v3"
                      aria-label={`Platform for ${row.kind === 'bundle' ? row.bundlePrefix : row.file.name}`}
                    />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {staged.length > 0 && summaryLines.length > 0 && (
        <div
          data-testid="logical-dataset-summary"
          className="rounded-lg border border-indigo-100 bg-indigo-50/80 p-4"
        >
          <h3 className="text-sm font-semibold text-indigo-950">Logical datasets detected</h3>
          <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-indigo-950/90">
            {summaryLines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      {staged.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-gray-900">Summary before upload</h3>
          <table className="mt-2 w-full text-left text-sm">
            <thead>
              <tr className="border-b text-xs uppercase tracking-wide text-gray-500">
                <th className="py-2 pr-2">Unit</th>
                <th className="py-2 pr-2">Files</th>
                <th className="py-2 pr-2">Dataset name</th>
                <th className="py-2">Condition</th>
              </tr>
            </thead>
            <tbody>
              {staged.map((row) => (
                <tr key={row.id} className="border-b border-gray-100 last:border-0">
                  <td className="py-2 pr-2 text-gray-800">
                    {row.kind === 'bundle' ? (
                      <span className="font-medium">
                        10x bundle ({row.bundlePrefix || 'unprefixed'})
                      </span>
                    ) : (
                      <span className="font-mono text-xs">File-based</span>
                    )}
                  </td>
                  <td className="py-2 pr-2 font-mono text-xs text-gray-700">
                    {row.kind === 'bundle'
                      ? row.files.map((f) => f.name).join(', ')
                      : row.file.name}
                  </td>
                  <td className="py-2 pr-2 text-gray-800">{row.datasetName || '—'}</td>
                  <td className="py-2 text-gray-600">{row.condition || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div>
        <label htmlFor="metadata" className="mb-1 block text-sm font-medium text-gray-700">
          Extra metadata
        </label>
        <input
          id="metadata"
          name="metadata"
          type="text"
          placeholder="key1=value1, key2=value2"
          className="input w-full"
        />
        <p className="mt-1 text-xs text-gray-400">
          Comma-separated key=value pairs (dataset-level)
        </p>
      </div>

      <div className="space-y-2 pt-2">
        {staged.length > 0 && submitConfirmationLine && (
          <p data-testid="submit-logical-dataset-hint" className="text-sm text-gray-700">
            {submitConfirmationLine} They are merged into one Zerna dataset for a single pipeline
            run.
          </p>
        )}
        <div className="flex gap-3">
          <button
            type="submit"
            disabled={isPending || staged.length === 0 || preflight.blockingErrors.length > 0}
            className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isPending ? 'Uploading…' : 'Upload dataset'}
          </button>
          <a href="/datasets" className="btn-secondary">
            Cancel
          </a>
        </div>
      </div>
    </form>
  );
}

const bundleRoleOrder: TenxFileRole[] = ['matrix', 'barcodes', 'features', 'genes'];

function bundleRoleLabel(role: TenxFileRole): string {
  switch (role) {
    case 'matrix':
      return 'Matrix';
    case 'barcodes':
      return 'Barcodes';
    case 'features':
      return 'Features';
    case 'genes':
      return 'Genes';
    default:
      return role;
  }
}
