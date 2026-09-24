'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import type { Dataset } from '@zerna/sdk';
import { formatDate } from '@/lib/dates';
import DatasetDeleteButton from './DatasetDeleteButton';

interface Props {
  datasets: Dataset[];
  sortBy: string;
  sortOrder: 'asc' | 'desc';
}

const COLUMNS = [
  { key: 'name', label: 'Name' },
  { key: 'cell_count', label: 'Cells' },
  { key: 'gene_count', label: 'Genes' },
  { key: 'created_at', label: 'Created' },
] as const;

type BulkDeleteScope = 'selected' | 'all';
type BulkRunDeleteMode = 'preserve' | 'all';

function formatNumber(n: number | null | undefined): string {
  if (n == null) return '—';
  return n.toLocaleString();
}

export default function DatasetTable({ datasets, sortBy, sortOrder }: Props) {
  const router = useRouter();
  const [hiddenDatasetIds, setHiddenDatasetIds] = useState<string[]>([]);
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>([]);
  const [bulkDeleteScope, setBulkDeleteScope] = useState<BulkDeleteScope | null>(null);
  const [bulkRunDeleteMode, setBulkRunDeleteMode] = useState<BulkRunDeleteMode>('preserve');
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const visibleDatasets = useMemo(
    () => datasets.filter((dataset) => !hiddenDatasetIds.includes(dataset.id)),
    [datasets, hiddenDatasetIds]
  );
  const selectedVisibleDatasetIds = useMemo(
    () =>
      selectedDatasetIds.filter((datasetId) =>
        visibleDatasets.some((dataset) => dataset.id === datasetId)
      ),
    [selectedDatasetIds, visibleDatasets]
  );
  const allVisibleSelected =
    visibleDatasets.length > 0 &&
    visibleDatasets.every((dataset) => selectedDatasetIds.includes(dataset.id));

  function sortHref(col: string): string {
    const nextOrder = sortBy === col && sortOrder === 'asc' ? 'desc' : 'asc';
    const params = new URLSearchParams({
      sort_by: col,
      sort_order: nextOrder,
    });
    return `?${params.toString()}`;
  }

  function sortIcon(col: string): string {
    if (sortBy !== col) return ' ↕';
    return sortOrder === 'asc' ? ' ↑' : ' ↓';
  }

  function toggleDataset(datasetId: string) {
    setSelectedDatasetIds((current) =>
      current.includes(datasetId)
        ? current.filter((id) => id !== datasetId)
        : [...current, datasetId]
    );
  }

  function toggleAllVisibleDatasets() {
    const visibleIds = visibleDatasets.map((dataset) => dataset.id);
    setSelectedDatasetIds((current) => {
      if (allVisibleSelected) {
        return current.filter((id) => !visibleIds.includes(id));
      }
      const merged = new Set(current);
      for (const id of visibleIds) merged.add(id);
      return [...merged];
    });
  }

  function closeBulkDialog() {
    if (isBulkDeleting) return;
    setBulkDeleteScope(null);
    setError(null);
  }

  async function handleBulkDelete() {
    if (bulkDeleteScope === 'selected' && selectedVisibleDatasetIds.length === 0) {
      setError('Select at least one dataset to delete.');
      return;
    }

    setError(null);
    setIsBulkDeleting(true);
    try {
      const response = await fetch('/api/proxy/v1/datasets/bulk-delete', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
        },
        body: JSON.stringify({
          scope: bulkDeleteScope,
          dataset_ids: bulkDeleteScope === 'selected' ? selectedVisibleDatasetIds : [],
          run_delete_mode: bulkRunDeleteMode,
        }),
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail ?? `Failed to delete datasets (${response.status})`);
      }
      const payload = (await response.json()) as { deleted_dataset_ids?: string[] };
      const deletedDatasetIds = payload.deleted_dataset_ids ?? [];
      if (deletedDatasetIds.length > 0) {
        setHiddenDatasetIds((current) => [...current, ...deletedDatasetIds]);
        setSelectedDatasetIds((current) => current.filter((id) => !deletedDatasetIds.includes(id)));
      }
      setBulkDeleteScope(null);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete datasets.');
    } finally {
      setIsBulkDeleting(false);
    }
  }

  if (visibleDatasets.length === 0) {
    return (
      <div className="card p-12 text-center">
        <p className="text-gray-500">No datasets found.</p>
        <p className="text-sm text-gray-400 mt-1">
          Try adjusting your filters or upload a new dataset.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {error && (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      <div className="flex flex-col gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium text-red-900">Dataset cleanup</p>
          <p className="mt-1 text-sm text-red-800">
            Delete selected datasets with checkboxes, or remove every dataset in one action.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setBulkDeleteScope('selected')}
            disabled={isBulkDeleting || selectedVisibleDatasetIds.length === 0}
            className="rounded-md border border-red-300 px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Delete Selected Datasets
          </button>
          <button
            type="button"
            onClick={() => setBulkDeleteScope('all')}
            disabled={isBulkDeleting}
            className="rounded-md border border-red-400 bg-red-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Delete All Datasets
          </button>
        </div>
      </div>

      <div className="card overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleAllVisibleDatasets}
                  aria-label="Select all datasets on this page"
                />
              </th>
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                >
                  <Link href={sortHref(col.key)} className="hover:text-gray-900 transition-colors">
                    {col.label}
                    <span className="text-gray-400">{sortIcon(col.key)}</span>
                  </Link>
                </th>
              ))}
              <th scope="col" className="relative px-6 py-3">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-100">
            {visibleDatasets.map((ds) => {
              const latestVersion = ds.versions[ds.versions.length - 1];
              return (
                <tr key={ds.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-4 text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={selectedDatasetIds.includes(ds.id)}
                      onChange={() => toggleDataset(ds.id)}
                      aria-label={`Select dataset ${ds.name}`}
                    />
                  </td>
                  <td className="px-6 py-4">
                    <Link
                      href={`/datasets/${ds.id}`}
                      className="font-medium text-gray-900 hover:text-blue-600 transition-colors"
                    >
                      {ds.name}
                    </Link>
                    {ds.description && (
                      <p className="text-sm text-gray-500 mt-0.5 truncate max-w-xs">
                        {ds.description}
                      </p>
                    )}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-700 tabular-nums">
                    {formatNumber(latestVersion?.cell_count)}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-700 tabular-nums">
                    {formatNumber(latestVersion?.gene_count)}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-500">{formatDate(ds.created_at)}</td>
                  <td className="px-6 py-4 text-right text-sm">
                    <div className="flex justify-end gap-3">
                      <Link
                        href={`/datasets/${ds.id}`}
                        className="text-blue-600 hover:text-blue-800 font-medium"
                      >
                        View
                      </Link>
                      <DatasetDeleteButton
                        datasetId={ds.id}
                        datasetName={ds.name}
                        disabled={isBulkDeleting}
                        onDeleted={() => {
                          setHiddenDatasetIds((current) => [...current, ds.id]);
                          setSelectedDatasetIds((current) => current.filter((id) => id !== ds.id));
                        }}
                      />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {bulkDeleteScope && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/50 px-4">
          <div className="w-full max-w-2xl rounded-xl bg-white shadow-2xl">
            <div className="border-b border-gray-200 px-6 py-4">
              <h2 className="text-lg font-semibold text-gray-900">
                {bulkDeleteScope === 'all' ? 'Delete all datasets' : 'Delete selected datasets'}
              </h2>
              <p className="mt-1 text-sm text-gray-600">
                {bulkDeleteScope === 'all'
                  ? 'This removes every dataset in the current organization.'
                  : `${selectedVisibleDatasetIds.length} dataset${selectedVisibleDatasetIds.length === 1 ? '' : 's'} selected on this page will be deleted.`}
              </p>
            </div>

            <div className="space-y-5 px-6 py-5">
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-4">
                <p className="text-sm font-medium text-amber-900">Associated runs</p>
                <p className="mt-1 text-sm text-amber-800">
                  Bulk dataset deletion can preserve associated runs or delete all of them first. To
                  choose individual runs for one dataset, use that dataset&apos;s row delete action.
                </p>
              </div>

              <fieldset className="space-y-3">
                <legend className="text-sm font-medium text-gray-900">Run handling</legend>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-gray-200 px-4 py-3">
                  <input
                    type="radio"
                    name="bulk-dataset-run-mode"
                    checked={bulkRunDeleteMode === 'preserve'}
                    onChange={() => setBulkRunDeleteMode('preserve')}
                    className="mt-1"
                  />
                  <div>
                    <p className="text-sm font-medium text-gray-900">Preserve associated runs</p>
                    <p className="text-sm text-gray-600">
                      Keep runs available as historical records after their source datasets are
                      removed.
                    </p>
                  </div>
                </label>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-gray-200 px-4 py-3">
                  <input
                    type="radio"
                    name="bulk-dataset-run-mode"
                    checked={bulkRunDeleteMode === 'all'}
                    onChange={() => setBulkRunDeleteMode('all')}
                    className="mt-1"
                  />
                  <div>
                    <p className="text-sm font-medium text-gray-900">Delete all associated runs</p>
                    <p className="text-sm text-gray-600">
                      Remove runs and their stored outputs before deleting the datasets.
                    </p>
                  </div>
                </label>
              </fieldset>
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-gray-200 px-6 py-4">
              <p className="text-xs text-gray-500">
                {bulkDeleteScope === 'all'
                  ? 'This action targets every dataset in the current organization.'
                  : `${selectedVisibleDatasetIds.length} dataset${selectedVisibleDatasetIds.length === 1 ? '' : 's'} selected.`}
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={closeBulkDialog}
                  disabled={isBulkDeleting}
                  className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => void handleBulkDelete()}
                  disabled={
                    isBulkDeleting ||
                    (bulkDeleteScope === 'selected' && selectedVisibleDatasetIds.length === 0)
                  }
                  className="rounded-md border border-red-400 bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isBulkDeleting ? 'Deleting…' : 'Delete datasets'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
