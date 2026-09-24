'use client';

import { useState } from 'react';
import React from 'react';
import type { AnnotationRevision } from '@zerna/sdk';
import { formatDateTime } from '@/lib/dates';

// ── Types ─────────────────────────────────────────────────────────────────────

export type ApprovalStatus = 'pending' | 'approved' | 'rejected';

export interface ApprovalWorkflowProps {
  runId: string;
  revisions: AnnotationRevision[];
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** Async function that calls POST /v1/annotations/{id}/approve */
  approveRevision: (revisionId: string) => Promise<AnnotationRevision>;
  /** Async function that calls PATCH /v1/annotations/{id} with rejected status */
  rejectRevision: (revisionId: string) => Promise<AnnotationRevision>;
  /** Called after approve/reject succeeds */
  onStatusChange?: (revision: AnnotationRevision) => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getApprovalStatus(revision: AnnotationRevision): ApprovalStatus {
  if (revision.approved_at) return 'approved';
  return 'pending';
}

function computeDiff(
  current: AnnotationRevision,
  previous: AnnotationRevision | null
): { changedCells: number; addedCells: number; removedCells: number } {
  if (!previous) {
    return {
      changedCells: 0,
      addedCells: Object.keys(current.annotations).length,
      removedCells: 0,
    };
  }

  const prevKeys = new Set(Object.keys(previous.annotations));
  const currKeys = new Set(Object.keys(current.annotations));

  let changedCells = 0;
  let addedCells = 0;
  let removedCells = 0;

  for (const key of currKeys) {
    if (!prevKeys.has(key)) {
      addedCells++;
    } else {
      const prevAnn = JSON.stringify(previous.annotations[key]);
      const currAnn = JSON.stringify(current.annotations[key]);
      if (prevAnn !== currAnn) changedCells++;
    }
  }

  for (const key of prevKeys) {
    if (!currKeys.has(key)) removedCells++;
  }

  return { changedCells, addedCells, removedCells };
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: ApprovalStatus }) {
  const styles: Record<ApprovalStatus, string> = {
    pending: 'bg-yellow-100 text-yellow-700',
    approved: 'bg-green-100 text-green-700',
    rejected: 'bg-red-100 text-red-700',
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles[status]}`}
      data-testid={`status-badge-${status}`}
    >
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function ApprovalWorkflow({
  revisions,
  isLoading = false,
  error = null,
  onRetry,
  approveRevision,
  rejectRevision,
  onStatusChange,
}: ApprovalWorkflowProps) {
  const [actionState, setActionState] = useState<
    Record<string, { loading: boolean; error: string | null }>
  >({});

  const sortedRevisions = [...revisions].sort((a, b) => b.revision_number - a.revision_number);

  const pendingRevisions = sortedRevisions.filter((r) => getApprovalStatus(r) === 'pending');

  async function handleApprove(revisionId: string) {
    setActionState((s) => ({
      ...s,
      [revisionId]: { loading: true, error: null },
    }));
    try {
      const updated = await approveRevision(revisionId);
      onStatusChange?.(updated);
    } catch (err) {
      setActionState((s) => ({
        ...s,
        [revisionId]: {
          loading: false,
          error: err instanceof Error ? err.message : 'Failed to approve',
        },
      }));
      return;
    }
    setActionState((s) => ({
      ...s,
      [revisionId]: { loading: false, error: null },
    }));
  }

  async function handleReject(revisionId: string) {
    setActionState((s) => ({
      ...s,
      [revisionId]: { loading: true, error: null },
    }));
    try {
      const updated = await rejectRevision(revisionId);
      onStatusChange?.(updated);
    } catch (err) {
      setActionState((s) => ({
        ...s,
        [revisionId]: {
          loading: false,
          error: err instanceof Error ? err.message : 'Failed to reject',
        },
      }));
      return;
    }
    setActionState((s) => ({
      ...s,
      [revisionId]: { loading: false, error: null },
    }));
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div
        className="card p-6 flex items-center justify-center"
        style={{ minHeight: 200 }}
        data-testid="approval-workflow-loading"
      >
        <div className="flex flex-col items-center gap-3 text-gray-500">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600" />
          <span className="text-sm">Loading revisions…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="card p-6 flex items-center justify-center"
        style={{ minHeight: 200 }}
        data-testid="approval-workflow-error"
      >
        <div className="flex flex-col items-center gap-3 text-center">
          <p className="text-sm text-red-600">{error}</p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
            >
              Retry
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="approval-workflow">
      {/* Summary */}
      <div className="card p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">Annotation approval</h2>
          <span className="text-xs text-gray-500">{pendingRevisions.length} pending</span>
        </div>
      </div>

      {/* Revision list */}
      {sortedRevisions.length === 0 ? (
        <div className="card p-6 text-center">
          <p className="text-sm text-gray-500">No annotation revisions found.</p>
        </div>
      ) : (
        <ul className="space-y-3" data-testid="revision-list">
          {sortedRevisions.map((revision, idx) => {
            const previous = sortedRevisions[idx + 1] ?? null;
            const diff = computeDiff(revision, previous);
            const status = getApprovalStatus(revision);
            const state = actionState[revision.id];

            return (
              <li
                key={revision.id}
                className="card p-4"
                data-testid={`revision-card-${revision.revision_number}`}
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-3">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-gray-900 text-sm">
                        Revision #{revision.revision_number}
                      </span>
                      <StatusBadge status={status} />
                      {revision.method && (
                        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                          {revision.method}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-400">
                      Created {formatDateTime(revision.created_at)}
                    </p>
                    {revision.approved_at && (
                      <p className="text-xs text-green-600">
                        Approved {formatDateTime(revision.approved_at)}
                      </p>
                    )}
                  </div>

                  {/* Actions */}
                  {status === 'pending' && (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => {
                          void handleApprove(revision.id);
                        }}
                        disabled={state?.loading}
                        data-testid={`approve-btn-${revision.revision_number}`}
                        className="rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        {state?.loading ? '…' : 'Approve'}
                      </button>
                      <button
                        onClick={() => {
                          void handleReject(revision.id);
                        }}
                        disabled={state?.loading}
                        data-testid={`reject-btn-${revision.revision_number}`}
                        className="rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        {state?.loading ? '…' : 'Reject'}
                      </button>
                    </div>
                  )}
                </div>

                {/* Diff summary */}
                <div
                  className="flex gap-4 text-xs text-gray-500 border-t border-gray-100 pt-3"
                  data-testid={`diff-summary-${revision.revision_number}`}
                >
                  <span>
                    <span className="font-medium text-gray-700">
                      {Object.keys(revision.annotations).length}
                    </span>{' '}
                    total cells
                  </span>
                  {diff.addedCells > 0 && (
                    <span className="text-green-600">+{diff.addedCells} added</span>
                  )}
                  {diff.changedCells > 0 && (
                    <span className="text-blue-600">~{diff.changedCells} changed</span>
                  )}
                  {diff.removedCells > 0 && (
                    <span className="text-red-600">-{diff.removedCells} removed</span>
                  )}
                </div>

                {/* Action error */}
                {state?.error && (
                  <p
                    className="mt-2 text-xs text-red-600"
                    data-testid={`action-error-${revision.revision_number}`}
                  >
                    {state.error}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
