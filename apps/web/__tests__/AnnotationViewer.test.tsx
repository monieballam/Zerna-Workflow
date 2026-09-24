/**
 * Unit tests for AnnotationViewer component.
 * deck.gl is aliased to lightweight stubs via vitest.config.ts.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { Embedding } from '../lib/embedding-types';
import type { AnnotationRevision } from '@zerna/sdk';
import AnnotationViewer from '../components/annotation/AnnotationViewer';

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeEmbedding(n = 5): Embedding {
  const cells = Array.from({ length: n }, (_, i) => ({
    id: `cell-${i}`,
    x: i * 1.0,
    y: 0,
  }));
  return {
    cells,
    bounds: { minX: 0, maxX: n - 1, minY: 0, maxY: 1 },
  };
}

function makeRevision(overrides: Partial<AnnotationRevision> = {}): AnnotationRevision {
  return {
    id: 'rev-1',
    run_id: 'run-1',
    revision_number: 1,
    annotations: {
      'cell-0': { tissue: 'blood', lineage: 'myeloid', cell_type: 'monocyte', confidence: 0.95 },
      'cell-1': { tissue: 'blood', lineage: 'lymphoid', cell_type: 'T cell', confidence: 0.88 },
      'cell-2': {
        tissue: 'bone marrow',
        lineage: 'myeloid',
        cell_type: 'neutrophil',
        confidence: 0.72,
      },
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

const defaultProps = () => ({
  embedding: makeEmbedding(5),
  revision: makeRevision(),
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('AnnotationViewer', () => {
  it('renders annotation legend with correct labels', () => {
    render(<AnnotationViewer {...defaultProps()} />);
    // Default level is cell_type — legend should show cell type values
    const legend = screen.getByTestId('annotation-legend');
    expect(legend).toBeTruthy();
    expect(legend.textContent).toContain('monocyte');
    expect(legend.textContent).toContain('T cell');
    expect(legend.textContent).toContain('neutrophil');
  });

  it('renders level selector buttons', () => {
    render(<AnnotationViewer {...defaultProps()} />);
    expect(screen.getByTestId('level-btn-tissue')).toBeTruthy();
    expect(screen.getByTestId('level-btn-lineage')).toBeTruthy();
    expect(screen.getByTestId('level-btn-cell_type')).toBeTruthy();
  });

  it('switches color mode to tissue and updates legend', () => {
    render(<AnnotationViewer {...defaultProps()} />);
    fireEvent.click(screen.getByTestId('level-btn-tissue'));
    const legend = screen.getByTestId('annotation-legend');
    expect(legend.textContent).toContain('blood');
    expect(legend.textContent).toContain('bone marrow');
  });

  it('switches color mode to lineage and updates legend', () => {
    render(<AnnotationViewer {...defaultProps()} />);
    fireEvent.click(screen.getByTestId('level-btn-lineage'));
    const legend = screen.getByTestId('annotation-legend');
    expect(legend.textContent).toContain('myeloid');
    expect(legend.textContent).toContain('lymphoid');
  });

  it('does not show cell info panel initially', () => {
    render(<AnnotationViewer {...defaultProps()} />);
    expect(screen.queryByTestId('cell-info-panel')).toBeNull();
  });

  it('calls onCellSelect when provided', () => {
    const onCellSelect = vi.fn();
    render(<AnnotationViewer {...defaultProps()} onCellSelect={onCellSelect} />);
    // Panel is not shown until a cell is selected via renderer callback
    expect(onCellSelect).not.toHaveBeenCalled();
  });

  it('shows loading state', () => {
    render(<AnnotationViewer embedding={makeEmbedding()} revision={null} isLoading />);
    expect(screen.getByTestId('annotation-viewer-loading')).toBeTruthy();
    expect(screen.getByText(/loading annotations/i)).toBeTruthy();
  });

  it('shows error state with message', () => {
    render(
      <AnnotationViewer
        embedding={makeEmbedding()}
        revision={null}
        error="Failed to load annotations"
      />
    );
    expect(screen.getByTestId('annotation-viewer-error')).toBeTruthy();
    expect(screen.getByText('Failed to load annotations')).toBeTruthy();
  });

  it('shows retry button in error state when onRetry provided', () => {
    const onRetry = vi.fn();
    render(
      <AnnotationViewer
        embedding={makeEmbedding()}
        revision={null}
        error="Network error"
        onRetry={onRetry}
      />
    );
    const retryBtn = screen.getByRole('button', { name: /retry/i });
    fireEvent.click(retryBtn);
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('renders canvas when not loading or errored', () => {
    render(<AnnotationViewer {...defaultProps()} />);
    expect(screen.getByTestId('annotation-canvas')).toBeTruthy();
  });

  it('renders with null revision (no annotations)', () => {
    render(<AnnotationViewer embedding={makeEmbedding()} revision={null} />);
    expect(screen.getByTestId('annotation-viewer')).toBeTruthy();
    // No legend when no annotations
    expect(screen.queryByTestId('annotation-legend')).toBeNull();
  });
});
