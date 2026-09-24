'use client';

import { useState, useMemo } from 'react';
import { parseUTC } from '../../lib/dates';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface AnnotationChange {
  id: string;
  timestamp: string;
  user: string;
  action: 'create' | 'update' | 'finalize' | 'revert';
  clusterId: string;
  previousLabel: string | null;
  newLabel: string;
  reason?: string;
}

export interface AnnotationLogProps {
  changes: AnnotationChange[];
  datasetName?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatTimestamp(iso: string): string {
  const d = parseUTC(iso);
  if (!d) return '—';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function actionBadge(action: AnnotationChange['action']) {
  const styles: Record<string, string> = {
    create: 'bg-green-100 text-green-700',
    update: 'bg-blue-100 text-blue-700',
    finalize: 'bg-purple-100 text-purple-700',
    revert: 'bg-red-100 text-red-700',
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${styles[action]}`}>
      {action}
    </span>
  );
}

// ── Diff Display ──────────────────────────────────────────────────────────────

function LabelDiff({
  previousLabel,
  newLabel,
}: {
  previousLabel: string | null;
  newLabel: string;
}) {
  if (!previousLabel) {
    return <span className="text-sm text-green-700 font-medium">{newLabel}</span>;
  }
  return (
    <span className="text-sm">
      <span className="text-red-500 line-through">{previousLabel}</span>
      <span className="mx-1 text-gray-400">→</span>
      <span className="text-green-700 font-medium">{newLabel}</span>
    </span>
  );
}

// ── Change Entry ──────────────────────────────────────────────────────────────

function ChangeEntry({ change }: { change: AnnotationChange }) {
  return (
    <div
      className="flex items-start gap-3 py-3 border-b border-gray-100 last:border-0"
      data-testid={`annotation-change-${change.id}`}
    >
      <div className="flex-shrink-0 mt-0.5">{actionBadge(change.action)}</div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span>{formatTimestamp(change.timestamp)}</span>
          <span>·</span>
          <span>{change.user}</span>
          <span>·</span>
          <span className="font-mono">cluster {change.clusterId}</span>
        </div>
        <div className="mt-1">
          <LabelDiff previousLabel={change.previousLabel} newLabel={change.newLabel} />
        </div>
        {change.reason && <p className="mt-1 text-xs text-gray-400 italic">{change.reason}</p>}
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function AnnotationLog({ changes, datasetName }: AnnotationLogProps) {
  const [search, setSearch] = useState('');
  const [actionFilter, setActionFilter] = useState<AnnotationChange['action'] | 'all'>('all');

  const filtered = useMemo(() => {
    let result = changes;
    if (actionFilter !== 'all') {
      result = result.filter((c) => c.action === actionFilter);
    }
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (c) =>
          c.clusterId.toLowerCase().includes(q) ||
          c.newLabel.toLowerCase().includes(q) ||
          (c.previousLabel?.toLowerCase().includes(q) ?? false) ||
          c.user.toLowerCase().includes(q)
      );
    }
    // Chronological: newest first
    return [...result].sort(
      (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    );
  }, [changes, search, actionFilter]);

  return (
    <div className="space-y-4" data-testid="annotation-log">
      {datasetName && (
        <h2 className="text-lg font-semibold text-gray-900">{datasetName} — Annotation Log</h2>
      )}

      <p className="text-xs text-gray-500">{changes.length} total changes</p>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <input
          type="text"
          placeholder="Search cluster, label, user…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm flex-1"
          aria-label="Search annotation log"
        />
        <select
          value={actionFilter}
          onChange={(e) => setActionFilter(e.target.value as typeof actionFilter)}
          className="rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          aria-label="Filter by action"
        >
          <option value="all">All actions</option>
          <option value="create">Create</option>
          <option value="update">Update</option>
          <option value="finalize">Finalize</option>
          <option value="revert">Revert</option>
        </select>
      </div>

      {/* Change list */}
      {filtered.length === 0 ? (
        <p className="text-sm text-gray-400 text-center py-8">No annotation changes found</p>
      ) : (
        <div className="bg-white border border-gray-200 rounded-lg px-4">
          {filtered.map((change) => (
            <ChangeEntry key={change.id} change={change} />
          ))}
        </div>
      )}
    </div>
  );
}
