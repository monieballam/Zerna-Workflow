/**
 * Optimization utilities for WebGL embedding rendering.
 *
 * - Frustum culling: skip tiles outside the viewport
 * - LOD decimation: sample every Nth point when >500k cells are visible
 * - Frame budget: reduce detail if rendering exceeds 16ms
 */

import type { Tile, Viewport } from './embedding-types';

// ---------------------------------------------------------------------------
// Frustum culling
// ---------------------------------------------------------------------------

/**
 * Returns only the tiles whose bounds intersect the given viewport.
 * Tiles completely outside the viewport are discarded.
 */
export function cullTiles(tiles: Tile[], viewport: Viewport): Tile[] {
  const vMaxX = viewport.x + viewport.width;
  const vMaxY = viewport.y + viewport.height;

  return tiles.filter(
    (tile) =>
      tile.bounds.minX < vMaxX &&
      tile.bounds.maxX > viewport.x &&
      tile.bounds.minY < vMaxY &&
      tile.bounds.maxY > viewport.y
  );
}

// ---------------------------------------------------------------------------
// Level-of-detail point decimation
// ---------------------------------------------------------------------------

const LOD_THRESHOLD = 500_000;

/**
 * Compute a decimation step for the given number of visible cells.
 * When visibleCellCount > LOD_THRESHOLD, returns N > 1 meaning
 * "render every Nth point". Otherwise returns 1 (no decimation).
 */
export function computeDecimationStep(visibleCellCount: number): number {
  if (visibleCellCount <= LOD_THRESHOLD) return 1;
  // Scale linearly: 1M cells → step 2, 2M → step 4, etc.
  return Math.max(1, Math.ceil(visibleCellCount / LOD_THRESHOLD));
}

/**
 * Decimate a tile's cell indices by keeping every Nth index.
 * Returns a new array — the original is not mutated.
 */
export function decimateTileIndices(indices: number[], step: number): number[] {
  if (step <= 1) return indices;
  const result: number[] = [];
  for (let i = 0; i < indices.length; i += step) {
    result.push(indices[i]);
  }
  return result;
}

// ---------------------------------------------------------------------------
// Frame budget limiter
// ---------------------------------------------------------------------------

const TARGET_FRAME_MS = 16; // 60 fps

/**
 * Tracks frame render times and suggests a detail level multiplier.
 * If the last frame exceeded the budget, the multiplier increases
 * (reducing detail). If frames are well within budget, it decreases
 * (restoring detail).
 */
export class FrameBudgetLimiter {
  private _detailMultiplier = 1;
  private _lastFrameMs = 0;

  /** Record how long the last frame took to render. */
  recordFrameTime(ms: number): void {
    this._lastFrameMs = ms;

    if (ms > TARGET_FRAME_MS) {
      // Over budget — reduce detail (increase multiplier)
      this._detailMultiplier = Math.min(8, this._detailMultiplier * (ms / TARGET_FRAME_MS));
    } else if (ms < TARGET_FRAME_MS * 0.7 && this._detailMultiplier > 1) {
      // Well within budget — slowly restore detail
      this._detailMultiplier = Math.max(1, this._detailMultiplier * 0.9);
    }
  }

  /** Current detail multiplier. Higher = less detail. */
  get detailMultiplier(): number {
    return this._detailMultiplier;
  }

  /** Last recorded frame time in milliseconds. */
  get lastFrameMs(): number {
    return this._lastFrameMs;
  }

  /** Reset to full detail. */
  reset(): void {
    this._detailMultiplier = 1;
    this._lastFrameMs = 0;
  }
}
