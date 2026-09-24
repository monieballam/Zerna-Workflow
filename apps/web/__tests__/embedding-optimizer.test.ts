import { describe, it, expect } from 'vitest';
import {
  cullTiles,
  computeDecimationStep,
  decimateTileIndices,
  FrameBudgetLimiter,
} from '@/lib/embedding-optimizer';
import type { Tile, Viewport } from '@/lib/embedding-types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeTile(
  id: string,
  minX: number,
  minY: number,
  maxX: number,
  maxY: number,
  count = 10
): Tile {
  return {
    id,
    bounds: { minX, minY, maxX, maxY },
    cellIndices: Array.from({ length: count }, (_, i) => i),
  };
}

function makeViewport(x: number, y: number, width: number, height: number, zoom = 1): Viewport {
  return { x, y, width, height, zoom };
}

// ---------------------------------------------------------------------------
// cullTiles
// ---------------------------------------------------------------------------

describe('cullTiles', () => {
  const tiles: Tile[] = [
    makeTile('a', 0, 0, 10, 10),
    makeTile('b', 20, 20, 30, 30),
    makeTile('c', 50, 50, 60, 60),
  ];

  it('keeps tiles that overlap the viewport', () => {
    const vp = makeViewport(0, 0, 25, 25);
    const result = cullTiles(tiles, vp);
    expect(result.map((t) => t.id)).toEqual(['a', 'b']);
  });

  it('removes tiles completely outside the viewport', () => {
    const vp = makeViewport(100, 100, 10, 10);
    const result = cullTiles(tiles, vp);
    expect(result).toHaveLength(0);
  });

  it('returns all tiles when viewport covers everything', () => {
    const vp = makeViewport(-10, -10, 200, 200);
    const result = cullTiles(tiles, vp);
    expect(result).toHaveLength(3);
  });

  it('handles partial overlap correctly', () => {
    const vp = makeViewport(5, 5, 20, 20);
    const result = cullTiles(tiles, vp);
    // tile a: 0-10 overlaps 5-25 ✓, tile b: 20-30 overlaps 5-25 ✓
    expect(result.map((t) => t.id)).toEqual(['a', 'b']);
  });
});

// ---------------------------------------------------------------------------
// computeDecimationStep
// ---------------------------------------------------------------------------

describe('computeDecimationStep', () => {
  it('returns 1 for small datasets', () => {
    expect(computeDecimationStep(100_000)).toBe(1);
    expect(computeDecimationStep(500_000)).toBe(1);
  });

  it('returns step > 1 for large datasets', () => {
    expect(computeDecimationStep(1_000_000)).toBe(2);
    expect(computeDecimationStep(2_000_000)).toBe(4);
  });

  it('returns 1 for zero cells', () => {
    expect(computeDecimationStep(0)).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// decimateTileIndices
// ---------------------------------------------------------------------------

describe('decimateTileIndices', () => {
  it('returns all indices when step is 1', () => {
    const indices = [0, 1, 2, 3, 4];
    expect(decimateTileIndices(indices, 1)).toEqual(indices);
  });

  it('keeps every Nth index', () => {
    const indices = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
    expect(decimateTileIndices(indices, 3)).toEqual([0, 3, 6, 9]);
  });

  it('handles empty array', () => {
    expect(decimateTileIndices([], 5)).toEqual([]);
  });

  it('does not mutate the original array', () => {
    const indices = [0, 1, 2, 3];
    const result = decimateTileIndices(indices, 2);
    expect(result).not.toBe(indices);
    expect(indices).toEqual([0, 1, 2, 3]);
  });
});

// ---------------------------------------------------------------------------
// FrameBudgetLimiter
// ---------------------------------------------------------------------------

describe('FrameBudgetLimiter', () => {
  it('starts with multiplier of 1', () => {
    const limiter = new FrameBudgetLimiter();
    expect(limiter.detailMultiplier).toBe(1);
  });

  it('increases multiplier when frame exceeds budget', () => {
    const limiter = new FrameBudgetLimiter();
    limiter.recordFrameTime(32); // 2x over 16ms budget
    expect(limiter.detailMultiplier).toBeGreaterThan(1);
  });

  it('gradually restores multiplier when frames are fast', () => {
    const limiter = new FrameBudgetLimiter();
    limiter.recordFrameTime(32); // spike
    const spiked = limiter.detailMultiplier;

    // Several fast frames
    for (let i = 0; i < 20; i++) {
      limiter.recordFrameTime(8);
    }
    expect(limiter.detailMultiplier).toBeLessThan(spiked);
  });

  it('caps multiplier at 8', () => {
    const limiter = new FrameBudgetLimiter();
    limiter.recordFrameTime(200); // very slow
    expect(limiter.detailMultiplier).toBeLessThanOrEqual(8);
  });

  it('records last frame time', () => {
    const limiter = new FrameBudgetLimiter();
    limiter.recordFrameTime(12);
    expect(limiter.lastFrameMs).toBe(12);
  });

  it('resets to defaults', () => {
    const limiter = new FrameBudgetLimiter();
    limiter.recordFrameTime(50);
    limiter.reset();
    expect(limiter.detailMultiplier).toBe(1);
    expect(limiter.lastFrameMs).toBe(0);
  });
});
