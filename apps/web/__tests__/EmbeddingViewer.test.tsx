/**
 * Unit tests for EmbeddingViewer component.
 * deck.gl is aliased to lightweight stubs via vitest.config.ts.
 */

import { describe, expect, it } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { Embedding, CellMetadata } from '../lib/embedding-types';
import { EmbeddingViewer } from '../components/embedding';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeEmbedding(n = 10): Embedding {
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

function makeMetadata(embedding: Embedding): CellMetadata[] {
  return embedding.cells.map((c, i) => ({
    cellId: c.id,
    cluster: `c${i % 3}`,
    expression: i * 0.5,
  }));
}

const defaultProps = () => {
  const embedding = makeEmbedding(10);
  return {
    embedding,
    metadata: makeMetadata(embedding),
    availableFields: ['cluster', 'cell_type', 'expression'],
    continuousFields: ['expression'],
    fieldRanges: { expression: { min: 0, max: 5 } },
  };
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('EmbeddingViewer', () => {
  function getColorBySelect(): HTMLSelectElement {
    const select = screen.getByRole('combobox', { name: /color by/i });
    if (!(select instanceof HTMLSelectElement)) {
      throw new TypeError('Expected an HTMLSelectElement');
    }
    return select;
  }

  it('renders a canvas element', () => {
    render(<EmbeddingViewer {...defaultProps()} />);
    expect(document.querySelector('canvas')).toBeTruthy();
  });

  it('renders toolbar buttons', () => {
    render(<EmbeddingViewer {...defaultProps()} />);
    expect(screen.getByText('Reset view')).toBeTruthy();
    expect(screen.getByText('Lasso: off')).toBeTruthy();
  });

  it('renders color-by dropdown with available fields', () => {
    render(<EmbeddingViewer {...defaultProps()} />);
    const select = getColorBySelect();
    const options: string[] = [];
    for (let index = 0; index < select.options.length; index += 1) {
      options.push(select.options.item(index)?.value ?? '');
    }
    expect(options).toContain('cluster');
    expect(options).toContain('cell_type');
    expect(options).toContain('expression');
  });

  it('toggles lasso button label on click', () => {
    render(<EmbeddingViewer {...defaultProps()} />);
    const btn = screen.getByText('Lasso: off');
    fireEvent.click(btn);
    expect(screen.getByText('Lasso: on')).toBeTruthy();
    fireEvent.click(screen.getByText('Lasso: on'));
    expect(screen.getByText('Lasso: off')).toBeTruthy();
  });

  it('does not show sidebar when no cells are selected', () => {
    render(<EmbeddingViewer {...defaultProps()} />);
    expect(screen.queryByText(/Selected/)).toBeNull();
  });

  it('canvas has width and height attributes', () => {
    render(<EmbeddingViewer {...defaultProps()} />);
    const canvas = document.querySelector('canvas') as HTMLCanvasElement;
    expect(canvas.width).toBeGreaterThan(0);
    expect(canvas.height).toBeGreaterThan(0);
  });

  it('color-by select defaults to first available field', () => {
    render(<EmbeddingViewer {...defaultProps()} />);
    const select = getColorBySelect();
    expect(select.value).toBe('cluster');
  });

  it('changing color-by select does not throw', () => {
    render(<EmbeddingViewer {...defaultProps()} />);
    const select = getColorBySelect();
    expect(() => fireEvent.change(select, { target: { value: 'expression' } })).not.toThrow();
  });

  it('honors an externally controlled color field', () => {
    render(<EmbeddingViewer {...defaultProps()} activeColorField="expression" />);
    const select = getColorBySelect();
    expect(select.value).toBe('expression');
  });
});
