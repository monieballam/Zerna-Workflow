'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { formatDateTime } from '@/lib/dates';

type AssociatedRun = {
  id: string;
  status: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

type RunsResponse = {
  items?: AssociatedRun[];
  total?: number;
};

type DeleteMode = 'preserve' | 'all' | 'selected';

interface Props {
  datasetId: string;
  datasetName: string;
  disabled?: boolean;
  onDeleted?: () => void;
}

const STATUS_STYLES: Record<string, string> = {
  queued: 'bg-yellow-100 text-yellow-800',
  running: 'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-100 text-gray-800',
};

export default function DatasetDeleteButton({
  datasetId,
  datasetName,
  disabled = false,
  onDeleted,
}: Props) {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const [isLoadingRuns, setIsLoadingRuns] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [runsLoaded, setRunsLoaded] = useState(false);
  const [mode, setMode] = useState<DeleteMode>('preserve');
  const [runs, setRuns] = useState<AssociatedRun[]>([]);
  const [totalRuns, setTotalRuns] = useState(0);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    let cancelled = false;

    async function loadRuns() {
      setIsLoadingRuns(true);
      setRunsLoaded(false);
      setError(null);
      try {
        const response = await fetch(
          `/api/proxy/v1/datasets/${encodeURIComponent(datasetId)}/runs?page=1&page_size=1000`
        );
        if (!response.ok) {
          const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
          throw new Error(payload?.detail ?? `Failed to load associated runs (${response.status})`);
        }
        const payload = (await response.json()) as RunsResponse;
        if (cancelled) return;
        const nextRuns = payload.items ?? [];
        setRuns(nextRuns);
        setTotalRuns(payload.total ?? nextRuns.length);
        setSelectedRunIds(nextRuns.map((run) => run.id));
        setMode(nextRuns.length > 0 ? 'preserve' : 'all');
        setRunsLoaded(true);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : 'Failed to load runs associated with this dataset.'
          );
        }
      } finally {
        if (!cancelled) setIsLoadingRuns(false);
      }
    }

    void loadRuns();
    return () => {
      cancelled = true;
    };
  }, [datasetId, isOpen]);

  const selectedRunCount = useMemo(
    () => selectedRunIds.filter((runId) => runs.some((run) => run.id === runId)).length,
    [runs, selectedRunIds]
  );

  function toggleRun(runId: string) {
    setSelectedRunIds((current) =>
      current.includes(runId) ? current.filter((id) => id !== runId) : [...current, runId]
    );
  }

  function closeDialog() {
    if (isDeleting) return;
    setIsOpen(false);
    setError(null);
  }

  async function handleDelete() {
    if (mode === 'selected' && selectedRunCount === 0) {
      setError('Select at least one associated run or preserve all runs.');
      return;
    }

    setIsDeleting(true);
    setError(null);
    try {
      const response = await fetch(`/api/proxy/v1/datasets/${datasetId}`, {
        method: 'DELETE',
        headers: {
          'content-type': 'application/json',
        },
        body: JSON.stringify({
          run_delete_mode: mode,
          run_ids: mode === 'selected' ? selectedRunIds : [],
        }),
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail ?? `Failed to delete dataset (${response.status})`);
      }
      setIsOpen(false);
      onDeleted?.();
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete dataset.');
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        disabled={disabled}
        className="font-medium text-red-600 hover:text-red-800 disabled:cursor-not-allowed disabled:opacity-50"
      >
        Delete
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/50 px-4">
          <div className="max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-xl bg-white shadow-2xl">
            <div className="border-b border-gray-200 px-6 py-4">
              <h2 className="text-lg font-semibold text-gray-900">Delete dataset</h2>
              <p className="mt-1 text-sm text-gray-600">
                <span className="font-medium text-gray-900">{datasetName}</span> will be removed
                from datasets. Preserved runs remain accessible as historical records.
              </p>
            </div>

            <div className="space-y-5 overflow-y-auto px-6 py-5">
              {error && (
                <div
                  role="alert"
                  className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
                >
                  {error}
                </div>
              )}

              {isLoadingRuns ? (
                <p className="text-sm text-gray-500">Loading associated runs…</p>
              ) : (
                <>
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-4">
                    <p className="text-sm font-medium text-amber-900">
                      {totalRuns} associated run{totalRuns === 1 ? '' : 's'}
                    </p>
                    <p className="mt-1 text-sm text-amber-800">
                      Choose whether to preserve those runs, delete all of them, or delete only a
                      selected subset before the dataset is removed.
                    </p>
                  </div>

                  {runs.length > 0 && (
                    <fieldset className="space-y-3">
                      <legend className="text-sm font-medium text-gray-900">
                        Associated run handling
                      </legend>
                      <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-gray-200 px-4 py-3">
                        <input
                          type="radio"
                          name={`delete-mode-${datasetId}`}
                          checked={mode === 'preserve'}
                          onChange={() => setMode('preserve')}
                          className="mt-1"
                        />
                        <div>
                          <p className="text-sm font-medium text-gray-900">Preserve all runs</p>
                          <p className="text-sm text-gray-600">
                            Keep run details and outputs available after the dataset is deleted.
                          </p>
                        </div>
                      </label>
                      <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-gray-200 px-4 py-3">
                        <input
                          type="radio"
                          name={`delete-mode-${datasetId}`}
                          checked={mode === 'all'}
                          onChange={() => setMode('all')}
                          className="mt-1"
                        />
                        <div>
                          <p className="text-sm font-medium text-gray-900">Delete all runs</p>
                          <p className="text-sm text-gray-600">
                            Remove every run tied to this dataset before deleting the dataset.
                          </p>
                        </div>
                      </label>
                      <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-gray-200 px-4 py-3">
                        <input
                          type="radio"
                          name={`delete-mode-${datasetId}`}
                          checked={mode === 'selected'}
                          onChange={() => setMode('selected')}
                          className="mt-1"
                        />
                        <div>
                          <p className="text-sm font-medium text-gray-900">Delete selected runs</p>
                          <p className="text-sm text-gray-600">
                            Remove only the runs you check below and preserve the rest.
                          </p>
                        </div>
                      </label>
                    </fieldset>
                  )}

                  {runs.length > 0 ? (
                    <div className="rounded-lg border border-gray-200">
                      <div className="border-b border-gray-200 px-4 py-3">
                        <p className="text-sm font-medium text-gray-900">Associated runs</p>
                        <p className="mt-1 text-xs text-gray-500">
                          Links open in a new tab so you can inspect a run before deleting it.
                        </p>
                      </div>
                      <div className="max-h-80 overflow-y-auto">
                        <table className="min-w-full divide-y divide-gray-200">
                          <thead className="bg-gray-50">
                            <tr>
                              <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                                {mode === 'selected' ? 'Select' : ''}
                              </th>
                              <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                                Run
                              </th>
                              <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                                Status
                              </th>
                              <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                                Started
                              </th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-100 bg-white">
                            {runs.map((run) => (
                              <tr key={run.id} className="hover:bg-gray-50">
                                <td className="px-4 py-3 text-sm text-gray-700">
                                  {mode === 'selected' ? (
                                    <input
                                      type="checkbox"
                                      checked={selectedRunIds.includes(run.id)}
                                      onChange={() => toggleRun(run.id)}
                                      aria-label={`Select run ${run.id}`}
                                    />
                                  ) : null}
                                </td>
                                <td className="px-4 py-3 text-sm">
                                  <a
                                    href={`/runs/${run.id}`}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="font-mono text-blue-600 hover:text-blue-800"
                                  >
                                    {run.id.slice(0, 8)}…
                                  </a>
                                </td>
                                <td className="px-4 py-3 text-sm">
                                  <span
                                    className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${
                                      STATUS_STYLES[run.status] ?? 'bg-gray-100 text-gray-800'
                                    }`}
                                  >
                                    {run.status}
                                  </span>
                                </td>
                                <td className="px-4 py-3 text-sm text-gray-500">
                                  {formatDateTime(run.started_at ?? run.created_at)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ) : (
                    <p className="text-sm text-gray-500">
                      No runs are associated with this dataset. Deleting it only removes the dataset
                      and its stored source files.
                    </p>
                  )}
                </>
              )}
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-gray-200 px-6 py-4">
              <p className="text-xs text-gray-500">
                {mode === 'selected'
                  ? `${selectedRunCount} run${selectedRunCount === 1 ? '' : 's'} selected for deletion`
                  : 'Preserved runs remain available in the Runs area after dataset deletion.'}
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={closeDialog}
                  disabled={isDeleting}
                  className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => void handleDelete()}
                  disabled={
                    isDeleting ||
                    isLoadingRuns ||
                    !runsLoaded ||
                    (mode === 'selected' && selectedRunCount === 0)
                  }
                  className="rounded-md border border-red-400 bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isDeleting ? 'Deleting…' : 'Delete dataset'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
