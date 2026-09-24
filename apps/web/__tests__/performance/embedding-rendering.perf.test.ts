/**
 * Performance tests for embedding rendering logic.
 *
 * Tests tile building, color mapping computation, and lasso selection
 * performance for datasets up to 1M cells. These are unit-style tests
 * of the rendering logic — no browser or WebGL context required.
 *
 * Validates: Requirements 17.1, 17.2
 */

import { describe, it, expect, vi } from 'vitest';
import type {
  Embedding,
  CellMetadata,
  CategoricalColorMapping,
  ContinuousColorMapping,
  Point,
} from '../../lib/embedding-types';
import { EmbeddingRenderer } from '../../lib/embedding-renderer';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeEmbedding(n: number): Embedding {
  const cells = Array.from({ length: n }, (_, i) => ({
    id: `cell-${i}`,
    x: (i % 1000) * 1.0,
    y: Math.floor(i / 1000) * 1.0,
  }));
  const maxY = Math.ceil(n / 1000);
  return {
    cells,
    bounds: { minX: 0, maxX: 999, minY: 0, maxY: maxY > 0 ? maxY : 1 },
  };
}

function makeMetadata(embedding: Embedding): CellMetadata[] {
  return embedding.cells.map((c, i) => ({
    cellId: c.id,
    cluster: `cluster-${i % 20}`,
    expression: Math.random() * 10,
  }));
}

function makeCanvas(): HTMLCanvasElement {
  return {
    getContext: vi.fn().mockReturnValue({}),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    width: 1920,
    height: 1080,
  } as unknown as HTMLCanvasElement;
}

// ---------------------------------------------------------------------------
// Tile building performance
// ---------------------------------------------------------------------------

describe('Tile building performance', () => {
  it('builds tiles for 1M cells in < 5 seconds', () => {
    const embedding = makeEmbedding(1_000_000);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = {
      type: 'categorical',
      field: 'cluster',
    };

    const start = performance.now();
    const renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, vi.fn());
    const elapsed = performance.now() - start;

    const tiles = (renderer as unknown as { tiles: Array<{ cellIndices: number[] }> }).tiles;
    expect(tiles.length).toBeGreaterThan(1);

    // All cells must be covered
    const totalCovered = tiles.reduce((sum, t) => sum + t.cellIndices.length, 0);
    expect(totalCovered).toBe(1_000_000);

    expect(elapsed).toBeLessThan(5000);
    renderer.destroy();
  });

  it('builds tiles for 100k cells in < 500ms', () => {
    const embedding = makeEmbedding(100_000);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = {
      type: 'categorical',
      field: 'cluster',
    };

    const start = performance.now();
    const renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, vi.fn());
    const elapsed = performance.now() - start;

    expect(elapsed).toBeLessThan(500);
    renderer.destroy();
  });
});

// ---------------------------------------------------------------------------
// Color mapping computation performance
// ---------------------------------------------------------------------------

describe('Color mapping computation performance', () => {
  it('updates continuous color mapping for 1M cells in < 3 seconds', () => {
    const embedding = makeEmbedding(1_000_000);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = {
      type: 'categorical',
      field: 'cluster',
    };
    const renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, vi.fn());

    const newColorBy: ContinuousColorMapping = {
      type: 'continuous',
      field: 'expression',
      min: 0,
      max: 10,
    };

    const start = performance.now();
    renderer.updateColors(newColorBy);
    const elapsed = performance.now() - start;

    expect(elapsed).toBeLessThan(3000);
    renderer.destroy();
  });

  it('switches categorical color mapping for 500k cells in < 2 seconds', () => {
    const embedding = makeEmbedding(500_000);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = {
      type: 'categorical',
      field: 'cluster',
    };
    const renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, vi.fn());

    const newColorBy: CategoricalColorMapping = {
      type: 'categorical',
      field: 'cluster',
      palette: {
        'cluster-0': [255, 0, 0],
        'cluster-1': [0, 255, 0],
        'cluster-2': [0, 0, 255],
      },
    };

    const start = performance.now();
    renderer.updateColors(newColorBy);
    const elapsed = performance.now() - start;

    expect(elapsed).toBeLessThan(2000);
    renderer.destroy();
  });
});

// ---------------------------------------------------------------------------
// Lasso selection performance
// ---------------------------------------------------------------------------

describe('Lasso selection performance', () => {
  it('selects cells from 1M cell embedding in < 5 seconds', () => {
    const embedding = makeEmbedding(1_000_000);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = {
      type: 'categorical',
      field: 'cluster',
    };
    const onSelect = vi.fn();
    const renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, onSelect);

    // Lasso covering roughly 10% of the embedding space
    const lasso: Point[] = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 100 },
      { x: 0, y: 100 },
    ];

    const start = performance.now();
    const selected = renderer.selectCells(lasso);
    const elapsed = performance.now() - start;

    expect(selected.length).toBeGreaterThan(0);
    expect(onSelect).toHaveBeenCalledOnce();
    expect(elapsed).toBeLessThan(5000);
    renderer.destroy();
  });

  it('handles small lasso on large embedding in < 2 seconds', () => {
    const embedding = makeEmbedding(1_000_000);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = {
      type: 'categorical',
      field: 'cluster',
    };
    const renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, vi.fn());

    // Very small lasso — should still iterate all cells
    const lasso: Point[] = [
      { x: 500, y: 500 },
      { x: 502, y: 500 },
      { x: 502, y: 502 },
      { x: 500, y: 502 },
    ];

    const start = performance.now();
    renderer.selectCells(lasso);
    const elapsed = performance.now() - start;

    expect(elapsed).toBeLessThan(2000);
    renderer.destroy();
  });

  it('empty lasso returns immediately', () => {
    const embedding = makeEmbedding(1_000_000);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = {
      type: 'categorical',
      field: 'cluster',
    };
    const renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, vi.fn());

    const start = performance.now();
    const result = renderer.selectCells([{ x: 0, y: 0 }]);
    const elapsed = performance.now() - start;

    expect(result).toEqual([]);
    expect(elapsed).toBeLessThan(10);
    renderer.destroy();
  });
});
