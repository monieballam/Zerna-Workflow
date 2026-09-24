'use client';

import { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import RunStatusBadge from './RunStatusBadge';
import type { RunStatus } from '@zerna/sdk';
import { formatDateTime } from '@/lib/dates';

// ── Types ─────────────────────────────────────────────────────────────────────

interface HistoricRun {
  id: string;
  status: RunStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  dataset_name: string | null;
  template_name: string | null;
}

interface HistoricRunListResponse {
  items?: HistoricRun[];
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function RunHistory() {
  const [runs, setRuns] = useState<HistoricRun[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<RunStatus | 'all'>('all');

  // Fetch run history
  useEffect(() => {
    let cancelled = false;

    async function fetchHistory() {
      try {
        const res = await fetch('/api/proxy/runs?page_size=100');
        if (!res.ok) throw new Error(`Failed to load run history: ${res.status}`);
        const json = (await res.json()) as HistoricRunListResponse;
        if (!cancelled) setRuns(json.items ?? []);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void fetchHistory();
    return () => {
      cancelled = true;
    };
  }, []);

  // Filter runs by search term and status
  const filteredRuns = useMemo(() => {
    return runs.filter((run) => {
      const matchesStatus = statusFilter === 'all' || run.status === statusFilter;
      if (!matchesStatus) return false;
      if (!search.trim()) return true;
      const q = search.toLowerCase();
      return (
        run.id.toLowerCase().includes(q) ||
        (run.dataset_name?.toLowerCase().includes(q) ?? false) ||
        (run.template_name?.toLowerCase().includes(q) ?? false)
      );
    });
  }, [runs, search, statusFilter]);

  // ── Loading / Error states ────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-64" data-testid="run-history-loading">
        <div className="flex flex-col items-center gap-3 text-gray-500">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600" />
          <span className="text-sm">Loading run history…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-64" data-testid="run-history-error">
        <p className="text-sm text-red-600">{error}</p>
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4" data-testid="run-history">
      {/* Search & filter bar */}
      <div className="flex flex-col sm:flex-row gap-3">
        <input
          type="text"
          placeholder="Search by run ID, dataset, or template…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          aria-label="Search runs"
          data-testid="run-history-search"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as RunStatus | 'all')}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          aria-label="Filter by status"
          data-testid="run-history-status-filter"
        >
          <option value="all">All statuses</option>
          <option value="completed">Completed</option>
          <option value="running">Running</option>
          <option value="failed">Failed</option>
          <option value="queued">Queued</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {/* Results count */}
      <p className="text-xs text-gray-500">
        {filteredRuns.length} {filteredRuns.length === 1 ? 'run' : 'runs'} found
      </p>

      {/* Run list */}
      {filteredRuns.length === 0 ? (
        <div className="card p-12 text-center">
          <p className="text-gray-500">No matching runs found.</p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Run ID
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Dataset
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Template
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Date
                </th>
                <th className="relative px-6 py-3">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-100">
              {filteredRuns.map((run) => (
                <tr key={run.id} className="hover:bg-gray-50 transition-colors">
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
                  <td className="px-6 py-4 text-sm text-gray-500">{run.dataset_name ?? '—'}</td>
                  <td className="px-6 py-4 text-sm text-gray-500">{run.template_name ?? '—'}</td>
                  <td className="px-6 py-4 text-sm text-gray-500">
                    {formatDateTime(run.started_at ?? run.created_at)}
                  </td>
                  <td className="px-6 py-4 text-right text-sm space-x-3">
                    <Link
                      href={`/runs/${run.id}`}
                      className="text-blue-600 hover:text-blue-800 font-medium"
                    >
                      Load
                    </Link>
                    {run.status === 'completed' && (
                      <Link
                        href={`/runs/${run.id}/explore`}
                        className="text-indigo-600 hover:text-indigo-800 font-medium"
                      >
                        Explore
                      </Link>
                    )}
                    <Link
                      href={`/runs/new?replay=${run.id}`}
                      className="text-indigo-600 hover:text-indigo-800 font-medium"
                    >
                      Replay
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
