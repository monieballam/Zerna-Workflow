/**
 * Unit tests for EmbeddingRenderer and related utilities.
 *
 * We test the pure logic (tile building, color mapping, lasso selection)
 * without requiring a real WebGL context.
 * deck.gl is aliased to lightweight stubs via vitest.config.ts.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type {
  Embedding,
  CellMetadata,
  ContinuousColorMapping,
  CategoricalColorMapping,
  Point,
} from '../lib/embedding-types';
import { EmbeddingRenderer, computeOrthographicFit } from '../lib/embedding-renderer';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeEmbedding(n: number): Embedding {
  const cells = Array.from({ length: n }, (_, i) => ({
    id: `cell-${i}`,
    x: (i % 100) * 1.0,
    y: Math.floor(i / 100) * 1.0,
  }));
  return {
    cells,
    bounds: { minX: 0, maxX: 99, minY: 0, maxY: Math.ceil(n / 100) },
  };
}

function makeMetadata(embedding: Embedding): CellMetadata[] {
  return embedding.cells.map((c, i) => ({
    cellId: c.id,
    cluster: `cluster-${i % 5}`,
    expression: i * 0.1,
  }));
}

function makeCanvas(): HTMLCanvasElement {
  return {
    getContext: vi.fn().mockReturnValue({}),
    getBoundingClientRect: () =>
      ({ width: 800, height: 600, top: 0, left: 0, bottom: 600, right: 800 }) as DOMRect,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    clientWidth: 800,
    clientHeight: 600,
    width: 800,
    height: 600,
  } as unknown as HTMLCanvasElement;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('EmbeddingRenderer — tile building', () => {
  it('creates a single tile for small embeddings (<= 100k cells)', () => {
    const embedding = makeEmbedding(1_000);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = { type: 'categorical', field: 'cluster' };
    const renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, vi.fn());
    // Access private tiles via cast
    const tiles = (renderer as unknown as { tiles: unknown[] }).tiles;
    expect(tiles).toHaveLength(1);
    renderer.destroy();
  });

  it('creates multiple tiles for large embeddings (> 100k cells)', () => {
    const embedding = makeEmbedding(110_000);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = { type: 'categorical', field: 'cluster' };
    const renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, vi.fn());
    const tiles = (renderer as unknown as { tiles: unknown[] }).tiles;
    expect(tiles.length).toBeGreaterThan(1);
    renderer.destroy();
  });

  it('all cells are covered by tiles (no cell is lost)', () => {
    const embedding = makeEmbedding(150_000);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = { type: 'categorical', field: 'cluster' };
    const renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, vi.fn());
    const tiles = (renderer as unknown as { tiles: Array<{ cellIndices: number[] }> }).tiles;
    const totalCovered = tiles.reduce((sum, t) => sum + t.cellIndices.length, 0);
    expect(totalCovered).toBe(embedding.cells.length);
    renderer.destroy();
  });
});

describe('EmbeddingRenderer — lasso selection', () => {
  let renderer: InstanceType<typeof EmbeddingRenderer>;
  let onSelectionChange: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    const embedding = makeEmbedding(100);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = { type: 'categorical', field: 'cluster' };
    onSelectionChange = vi.fn();
    renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, onSelectionChange);
  });

  it('returns empty array for degenerate lasso (< 3 points)', () => {
    const result = renderer.selectCells([
      { x: 0, y: 0 },
      { x: 1, y: 1 },
    ]);
    expect(result).toEqual([]);
    expect(onSelectionChange).not.toHaveBeenCalled();
  });

  it('selects cells inside the lasso polygon', () => {
    // Cells at (0,0) to (9,0) — select a box around x=[0,5], y=[-1,1]
    const lasso: Point[] = [
      { x: -0.5, y: -0.5 },
      { x: 5.5, y: -0.5 },
      { x: 5.5, y: 0.5 },
      { x: -0.5, y: 0.5 },
    ];
    const selected = renderer.selectCells(lasso);
    // Cells 0-5 have x=0..5, y=0 — all inside the box
    expect(selected.length).toBeGreaterThanOrEqual(6);
    expect(selected).toContain('cell-0');
    expect(selected).toContain('cell-5');
  });

  it('calls onSelectionChange with selected cell ids', () => {
    const lasso: Point[] = [
      { x: -0.5, y: -0.5 },
      { x: 2.5, y: -0.5 },
      { x: 2.5, y: 0.5 },
      { x: -0.5, y: 0.5 },
    ];
    renderer.selectCells(lasso);
    expect(onSelectionChange).toHaveBeenCalledOnce();
    const [ids] = onSelectionChange.mock.calls[0] as [string[]];
    expect(Array.isArray(ids)).toBe(true);
  });

  it('selects no cells when lasso is outside embedding bounds', () => {
    const lasso: Point[] = [
      { x: 1000, y: 1000 },
      { x: 2000, y: 1000 },
      { x: 2000, y: 2000 },
      { x: 1000, y: 2000 },
    ];
    const selected = renderer.selectCells(lasso);
    expect(selected).toHaveLength(0);
  });
});

describe('EmbeddingRenderer — color mapping', () => {
  it('updateColors does not throw', () => {
    const embedding = makeEmbedding(50);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = { type: 'categorical', field: 'cluster' };
    const renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, vi.fn());
    const newColorBy: ContinuousColorMapping = {
      type: 'continuous',
      field: 'expression',
      min: 0,
      max: 10,
    };
    expect(() => renderer.updateColors(newColorBy)).not.toThrow();
    renderer.destroy();
  });
});

describe('computeOrthographicFit', () => {
  it('uses high zoom when embedding span is small in a large viewport (cells fill panel)', () => {
    const fitted = computeOrthographicFit({
      bounds: { minX: 0, maxX: 1, minY: 0, maxY: 1 },
      viewportCssPx: { w: 800, h: 600 },
      fillFraction: 0.92,
    });
    expect(fitted.zoom).toBeGreaterThan(5);
    expect(fitted.target[0]).toBeCloseTo(0.5);
    expect(fitted.target[1]).toBeCloseTo(0.5);
  });

  it('uses lower zoom when embedding span is huge', () => {
    const fitted = computeOrthographicFit({
      bounds: { minX: 0, maxX: 1e6, minY: 0, maxY: 1e6 },
      viewportCssPx: { w: 800, h: 800 },
      fillFraction: 0.92,
    });
    expect(fitted.zoom).toBeLessThan(0);
  });
});

describe('EmbeddingRenderer — renderTiles and zoomToFit', () => {
  it('renderTiles does not throw for a valid viewport', () => {
    const embedding = makeEmbedding(200);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = { type: 'categorical', field: 'cluster' };
    const renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, vi.fn());
    expect(() =>
      renderer.renderTiles({ x: 0, y: 0, width: 800, height: 600, zoom: 1 }, 1)
    ).not.toThrow();
    renderer.destroy();
  });

  it('zoomToFit does not throw', () => {
    const embedding = makeEmbedding(50);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = { type: 'categorical', field: 'cluster' };
    const renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, vi.fn());
    expect(() => renderer.zoomToFit()).not.toThrow();
    renderer.destroy();
  });

  it('setLabelsOptions and getDebugSnapshot do not throw', () => {
    const embedding = makeEmbedding(80);
    const metadata = makeMetadata(embedding);
    const colorBy: CategoricalColorMapping = { type: 'categorical', field: 'cluster' };
    const renderer = new EmbeddingRenderer(makeCanvas(), embedding, metadata, colorBy, vi.fn());
    expect(() => renderer.setLabelsOptions({ enabled: true, field: 'cluster' })).not.toThrow();
    expect(renderer.getDebugSnapshot()?.embeddingBounds).toBeDefined();
    renderer.destroy();
  });
});
