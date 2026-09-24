import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import EmbeddingComparison from '@/components/embedding/EmbeddingComparison';
import type { EmbeddingEntry } from '@/components/embedding/EmbeddingComparison';

// Mock EmbeddingViewer — it relies on WebGL/deck.gl which isn't available in jsdom
vi.mock('@/components/embedding/EmbeddingViewer', () => ({
  default: ({ embedding }: { embedding: { cells: unknown[] } }) => (
    <div data-testid="embedding-viewer">viewer({embedding.cells.length} cells)</div>
  ),
}));

const makeEntry = (label: string): EmbeddingEntry => ({
  label,
  embedding: {
    cells: [{ id: 'c1', x: 0, y: 0 }],
    bounds: { minX: -1, maxX: 1, minY: -1, maxY: 1 },
  },
  metadata: [{ cellId: 'c1', cluster: 'A' }],
  availableFields: ['cluster'],
});

describe('EmbeddingComparison', () => {
  const entries = [makeEntry('Before batch correction'), makeEntry('After batch correction')];

  it('renders both panel labels', () => {
    render(<EmbeddingComparison entries={entries} />);
    expect(screen.getByText('Before batch correction')).toBeTruthy();
    expect(screen.getByText('After batch correction')).toBeTruthy();
  });

  it('renders an EmbeddingViewer for each entry', () => {
    render(<EmbeddingComparison entries={entries} />);
    expect(screen.getAllByTestId('embedding-viewer')).toHaveLength(2);
  });

  it('shows the sync toggle button', () => {
    render(<EmbeddingComparison entries={entries} />);
    expect(screen.getByRole('button', { name: /sync viewports/i })).toBeTruthy();
  });

  it('sync toggle is on by default', () => {
    render(<EmbeddingComparison entries={entries} />);
    const btn = screen.getByRole('button', { name: /sync viewports/i });
    expect(btn.textContent).toContain('on');
  });

  it('toggling sync changes the button label', () => {
    render(<EmbeddingComparison entries={entries} />);
    const btn = screen.getByRole('button', { name: /sync viewports/i });
    expect(btn.textContent).toContain('on');
    fireEvent.click(btn);
    expect(btn.textContent).toContain('off');
    fireEvent.click(btn);
    expect(btn.textContent).toContain('on');
  });
});
