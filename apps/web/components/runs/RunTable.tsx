'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import type { Dataset, Run } from '@zerna/sdk';
import RunStatusBadge from './RunStatusBadge';
import { useRunUpdates } from '@/lib/useRunUpdates';
import { formatDateTime, formatDuration } from '@/lib/dates';

interface Props {
  initialRuns: Run[];
  datasets: Dataset[];
}

export default function RunTable({ initialRuns, datasets }: Props) {
  const router = useRouter();
  const liveRuns = useRunUpdates(initialRuns);
  const [hiddenRunIds, setHiddenRunIds] = useState<string[]>([]);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [deletingRunIds, setDeletingRunIds] = useState<string[]>([]);
  const [pendingCleanupScope, setPendingCleanupScope] = useState<
    'failed' | 'all' | 'selected' | null
  >(null);
  const [selectedDatasetId, setSelectedDatasetId] = useState('');
  const [error, setError] = useState<string | null>(null);

  const runs = useMemo(
    () => liveRuns.filter((run) => !hiddenRunIds.includes(run.id)),
    [hiddenRunIds, liveRuns]
  );
  const allRunsSelected = runs.length > 0 && runs.every((run) => selectedRunIds.includes(run.id));
  const selectedVisibleRunIds = useMemo(
    () => selectedRunIds.filter((runId) => runs.some((run) => run.id === runId)),
    [runs, selectedRunIds]
  );

  function toggleRunSelection(runId: string) {
    setSelectedRunIds((current) =>
      current.includes(runId) ? current.filter((id) => id !== runId) : [...current, runId]
    );
  }

  function toggleAllRunSelections() {
    const visibleIds = runs.map((run) => run.id);
    setSelectedRunIds((current) => {
      if (allRunsSelected) {
        return current.filter((id) => !visibleIds.includes(id));
      }
      const merged = new Set(current);
      for (const id of visibleIds) merged.add(id);
      return [...merged];
    });
  }

  async function deleteRun(run: Run) {
    const confirmed = window.confirm(
      `Delete run ${run.id.slice(0, 8)} and all stored outputs? This also removes artifacts and cached explorer data.`
    );
    if (!confirmed) return;

    setError(null);
    setDeletingRunIds((current) => [...current, run.id]);
    try {
      const response = await fetch(`/api/proxy/v1/runs/${run.id}`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail ?? `Failed to delete run (${response.status})`);
      }
      setHiddenRunIds((current) => [...current, run.id]);
      setSelectedRunIds((current) => current.filter((id) => id !== run.id));
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete run.');
    } finally {
      setDeletingRunIds((current) => current.filter((id) => id !== run.id));
    }
  }

  async function bulkDeleteRuns(
    scope: 'failed' | 'all' | 'selected',
    datasetId?: string,
    runIds?: string[]
  ) {
    const datasetLabel = datasetId
      ? ` for dataset ${datasets.find((dataset) => dataset.id === datasetId)?.name ?? datasetId}`
      : '';
    const label =
      scope === 'failed'
        ? `all failed runs${datasetLabel}`
        : scope === 'selected'
          ? `${runIds?.length ?? 0} selected run${(runIds?.length ?? 0) === 1 ? '' : 's'}`
          : `all runs${datasetLabel}`;
    const confirmed = window.confirm(
      `Delete ${label} and their stored outputs? This also removes artifacts, durable snapshots, and cached explorer files.`
    );
    if (!confirmed) return;

    setError(null);
    setPendingCleanupScope(scope);
    try {
      const response = await fetch('/api/proxy/v1/runs/cleanup', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
        },
        body: JSON.stringify({
          scope,
          dataset_id: datasetId || undefined,
          run_ids: scope === 'selected' ? (runIds ?? []) : [],
        }),
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail ?? `Failed to clean runs (${response.status})`);
      }
      const payload = (await response.json()) as { deleted_run_ids?: string[] };
      const deletedRunIds = payload.deleted_run_ids ?? [];
      if (deletedRunIds.length > 0) {
        setHiddenRunIds((current) => [...current, ...deletedRunIds]);
        setSelectedRunIds((current) => current.filter((id) => !deletedRunIds.includes(id)));
      }
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clean runs.');
    } finally {
      setPendingCleanupScope(null);
    }
  }

  if (runs.length === 0) {
    return (
      <div className="card p-12 text-center">
        <p className="text-gray-500">No runs found.</p>
        <p className="text-sm text-gray-400 mt-1">
          Try adjusting your filters or{' '}
          <Link href="/runs/new" className="text-blue-600 hover:underline">
            start a new run
          </Link>
          .
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

      <div className="flex flex-col gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium text-amber-900">Run cleanup</p>
          <p className="mt-1 text-sm text-amber-800">
            Delete selected runs with checkboxes, or clean up failed and all-run scopes with one
            action.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void bulkDeleteRuns('selected', undefined, selectedVisibleRunIds)}
            disabled={pendingCleanupScope !== null || selectedVisibleRunIds.length === 0}
            className="rounded-md border border-red-300 px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {pendingCleanupScope === 'selected'
              ? 'Deleting selected runs…'
              : 'Delete Selected Runs'}
          </button>
          <label className="flex min-w-[15rem] flex-col gap-1">
            <span className="text-xs font-medium uppercase tracking-wide text-amber-900">
              Optional dataset scope
            </span>
            <select
              value={selectedDatasetId}
              onChange={(event) => setSelectedDatasetId(event.target.value)}
              className="rounded-md border border-amber-300 bg-white px-3 py-2 text-sm text-gray-700"
            >
              <option value="">All datasets</option>
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={() => void bulkDeleteRuns('failed', selectedDatasetId || undefined)}
            disabled={pendingCleanupScope !== null || !runs.some((run) => run.status === 'failed')}
            className="rounded-md border border-red-300 px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {pendingCleanupScope === 'failed'
              ? 'Deleting failed runs…'
              : selectedDatasetId
                ? 'Delete Failed Runs For Dataset'
                : 'Delete Failed Runs'}
          </button>
          <button
            type="button"
            onClick={() => void bulkDeleteRuns('all', selectedDatasetId || undefined)}
            disabled={pendingCleanupScope !== null}
            className="rounded-md border border-red-400 bg-red-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {pendingCleanupScope === 'all'
              ? 'Deleting all runs…'
              : selectedDatasetId
                ? 'Delete Runs For Dataset'
                : 'Delete All Runs'}
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
                  checked={allRunsSelected}
                  onChange={toggleAllRunSelections}
                  aria-label="Select all runs on this page"
                />
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Status
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Run ID
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Started
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Duration
              </th>
              <th className="relative px-6 py-3">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-100">
            {runs.map((run) => (
              <tr key={run.id} className="hover:bg-gray-50 transition-colors">
                <td className="px-4 py-4 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={selectedRunIds.includes(run.id)}
                    onChange={() => toggleRunSelection(run.id)}
                    aria-label={`Select run ${run.id}`}
                  />
                </td>
                <td className="px-6 py-4">
                  <RunStatusBadge status={run.status} />
                </td>
                <td className="px-6 py-4">
                  <Link
                    href={`/runs/${run.id}`}
                    className="font-mono text-sm text-gray-700 hover:text-blue-600 transition-colors"
                  >
                    {run.id.slice(0, 8)}…
                  </Link>
                </td>
                <td className="px-6 py-4 text-sm text-gray-500">
                  {formatDateTime(run.started_at ?? run.created_at)}
                </td>
                <td className="px-6 py-4 text-sm text-gray-500 tabular-nums">
                  {formatDuration(run.started_at, run.completed_at)}
                </td>
                <td className="px-6 py-4 text-right text-sm">
                  <div className="flex justify-end gap-3">
                    <Link
                      href={`/runs/${run.id}`}
                      className="text-blue-600 hover:text-blue-800 font-medium"
                    >
                      View
                    </Link>
                    {run.status === 'completed' && (
                      <Link
                        href={`/runs/${run.id}/explore`}
                        className="text-indigo-600 hover:text-indigo-800 font-medium"
                      >
                        Explore
                      </Link>
                    )}
                    <button
                      type="button"
                      onClick={() => void deleteRun(run)}
                      disabled={deletingRunIds.includes(run.id)}
                      className="font-medium text-red-600 hover:text-red-800 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {deletingRunIds.includes(run.id) ? 'Deleting…' : 'Delete'}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
