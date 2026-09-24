/**
 * Unit tests for ApprovalWorkflow component.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import type { AnnotationRevision } from '@zerna/sdk';
import ApprovalWorkflow from '../components/annotation/ApprovalWorkflow';

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeRevision(overrides: Partial<AnnotationRevision> = {}): AnnotationRevision {
  return {
    id: 'rev-1',
    run_id: 'run-1',
    revision_number: 1,
    annotations: {
      'cell-0': { tissue: 'blood', lineage: 'myeloid', cell_type: 'monocyte', confidence: 0.95 },
      'cell-1': { tissue: 'blood', lineage: 'lymphoid', cell_type: 'T cell', confidence: 0.88 },
    },
    knowledge_pack_id: null,
    method: 'celltypist',
    approved_by: null,
    approved_at: null,
    created_by: 'user-1',
    created_at: '2025-01-15T10:00:00Z',
    ...overrides,
  };
}

function defaultProps(overrides: Partial<Parameters<typeof ApprovalWorkflow>[0]> = {}) {
  return {
    runId: 'run-1',
    revisions: [makeRevision()],
    approveRevision: vi
      .fn()
      .mockResolvedValue(
        makeRevision({ approved_at: '2025-01-16T10:00:00Z', approved_by: 'user-2' })
      ),
    rejectRevision: vi.fn().mockResolvedValue(makeRevision()),
    ...overrides,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('ApprovalWorkflow', () => {
  it('renders pending revisions list', () => {
    render(<ApprovalWorkflow {...defaultProps()} />);
    expect(screen.getByTestId('revision-list')).toBeTruthy();
    expect(screen.getByTestId('revision-card-1')).toBeTruthy();
    expect(screen.getByText('Revision #1')).toBeTruthy();
  });

  it('renders multiple revisions', () => {
    const revisions = [
      makeRevision({ revision_number: 1 }),
      makeRevision({ id: 'rev-2', revision_number: 2, method: 'manual' }),
    ];
    render(<ApprovalWorkflow {...defaultProps({ revisions })} />);
    expect(screen.getByTestId('revision-card-1')).toBeTruthy();
    expect(screen.getByTestId('revision-card-2')).toBeTruthy();
  });

  it('shows diff summary between revisions', () => {
    const revisions = [
      makeRevision({ revision_number: 1 }),
      makeRevision({
        id: 'rev-2',
        revision_number: 2,
        annotations: {
          'cell-0': {
            tissue: 'blood',
            lineage: 'myeloid',
            cell_type: 'macrophage',
            confidence: 0.9,
          },
          'cell-1': { tissue: 'blood', lineage: 'lymphoid', cell_type: 'T cell', confidence: 0.88 },
          'cell-2': {
            tissue: 'bone marrow',
            lineage: 'myeloid',
            cell_type: 'neutrophil',
            confidence: 0.7,
          },
        },
      }),
    ];
    render(<ApprovalWorkflow {...defaultProps({ revisions })} />);
    // Rev 2 diff vs rev 1: 1 changed (cell-0), 1 added (cell-2)
    const diff2 = screen.getByTestId('diff-summary-2');
    expect(diff2.textContent).toContain('changed');
    expect(diff2.textContent).toContain('added');
  });

  it('shows approve and reject buttons for pending revisions', () => {
    render(<ApprovalWorkflow {...defaultProps()} />);
    expect(screen.getByTestId('approve-btn-1')).toBeTruthy();
    expect(screen.getByTestId('reject-btn-1')).toBeTruthy();
  });

  it('calls approveRevision API on approve button click', async () => {
    const approveRevision = vi
      .fn()
      .mockResolvedValue(
        makeRevision({ approved_at: '2025-01-16T10:00:00Z', approved_by: 'user-2' })
      );
    render(<ApprovalWorkflow {...defaultProps({ approveRevision })} />);

    fireEvent.click(screen.getByTestId('approve-btn-1'));

    await waitFor(() => {
      expect(approveRevision).toHaveBeenCalledWith('rev-1');
    });
  });

  it('calls rejectRevision API on reject button click', async () => {
    const rejectRevision = vi.fn().mockResolvedValue(makeRevision());
    render(<ApprovalWorkflow {...defaultProps({ rejectRevision })} />);

    fireEvent.click(screen.getByTestId('reject-btn-1'));

    await waitFor(() => {
      expect(rejectRevision).toHaveBeenCalledWith('rev-1');
    });
  });

  it('calls onStatusChange after approve', async () => {
    const updatedRevision = makeRevision({
      approved_at: '2025-01-16T10:00:00Z',
      approved_by: 'user-2',
    });
    const approveRevision = vi.fn().mockResolvedValue(updatedRevision);
    const onStatusChange = vi.fn();

    render(<ApprovalWorkflow {...defaultProps({ approveRevision, onStatusChange })} />);

    fireEvent.click(screen.getByTestId('approve-btn-1'));

    await waitFor(() => {
      expect(onStatusChange).toHaveBeenCalledWith(updatedRevision);
    });
  });

  it('shows pending status badge for unapproved revision', () => {
    render(<ApprovalWorkflow {...defaultProps()} />);
    expect(screen.getByTestId('status-badge-pending')).toBeTruthy();
  });

  it('shows approved status badge for approved revision', () => {
    const revisions = [
      makeRevision({
        approved_at: '2025-01-16T10:00:00Z',
        approved_by: 'user-2',
      }),
    ];
    render(<ApprovalWorkflow {...defaultProps({ revisions })} />);
    expect(screen.getByTestId('status-badge-approved')).toBeTruthy();
  });

  it('does not show approve/reject buttons for approved revision', () => {
    const revisions = [
      makeRevision({
        approved_at: '2025-01-16T10:00:00Z',
        approved_by: 'user-2',
      }),
    ];
    render(<ApprovalWorkflow {...defaultProps({ revisions })} />);
    expect(screen.queryByTestId('approve-btn-1')).toBeNull();
    expect(screen.queryByTestId('reject-btn-1')).toBeNull();
  });

  it('shows loading state', () => {
    render(<ApprovalWorkflow {...defaultProps({ isLoading: true })} />);
    expect(screen.getByTestId('approval-workflow-loading')).toBeTruthy();
    expect(screen.getByText(/loading revisions/i)).toBeTruthy();
  });

  it('shows error state with message', () => {
    render(<ApprovalWorkflow {...defaultProps({ error: 'Failed to load revisions' })} />);
    expect(screen.getByTestId('approval-workflow-error')).toBeTruthy();
    expect(screen.getByText('Failed to load revisions')).toBeTruthy();
  });

  it('shows retry button in error state when onRetry provided', () => {
    const onRetry = vi.fn();
    render(<ApprovalWorkflow {...defaultProps({ error: 'Network error', onRetry })} />);
    const retryBtn = screen.getByRole('button', { name: /retry/i });
    fireEvent.click(retryBtn);
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('shows empty state when no revisions', () => {
    render(<ApprovalWorkflow {...defaultProps({ revisions: [] })} />);
    expect(screen.getByText(/no annotation revisions found/i)).toBeTruthy();
  });

  it('shows error message when approve fails', async () => {
    const approveRevision = vi.fn().mockRejectedValue(new Error('Unauthorized'));
    render(<ApprovalWorkflow {...defaultProps({ approveRevision })} />);

    fireEvent.click(screen.getByTestId('approve-btn-1'));

    await waitFor(() => {
      expect(screen.getByTestId('action-error-1')).toBeTruthy();
      expect(screen.getByText('Unauthorized')).toBeTruthy();
    });
  });

  it('shows total cell count in diff summary', () => {
    render(<ApprovalWorkflow {...defaultProps()} />);
    const diff = screen.getByTestId('diff-summary-1');
    expect(diff.textContent).toContain('2'); // 2 cells in the revision
    expect(diff.textContent).toContain('total cells');
  });
});
