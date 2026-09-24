/**
 * EmbeddingRenderer — WebGL-based renderer for large single-cell embeddings.
 *
 * Uses deck.gl ScatterplotLayer for GPU-accelerated rendering.
 * OrthographicView fit uses deck.gl semantics: zoom 0 maps 1 world unit to 1 CSS pixel;
 * each +1 zoom doubles on-screen size (scale ∝ 2^zoom).
 */

import { COORDINATE_SYSTEM, Deck, OrthographicView } from '@deck.gl/core';
import { ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import type {
  ColorMapping,
  Embedding,
  EmbeddingCell,
  CellMetadata,
  Point,
  Tile,
  Viewport,
} from './embedding-types';
import { shortenPlotLabel } from './embedding-label-short';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TILE_SIZE = 10_000; // cells per tile for large datasets
const LARGE_DATASET_THRESHOLD = 100_000;

/** Use this fraction of the CSS viewport when fitting the embedding (margin). */
const VIEWPORT_FILL_FRACTION = 0.92;

const MIN_ZOOM = -10;
const MAX_ZOOM = 24;

/** Max category labels in normal mode (largest / spatially separated first). */
const MAX_CENTROID_LABELS_NORMAL = 12;
/** Focus mode: at most one centroid label. */
const MAX_CENTROID_LABELS_FOCUS = 1;
/** Min world-units between label centroids to reduce overlap (fraction of embedding span). */
const MIN_LABEL_CENTROID_SEP_FRAC = 0.042;

/** Minimum cells in a category to draw a centroid label. */
const MIN_CELLS_PER_LABEL = 5;

// Viridis color scale — 10 sample points [R, G, B] (0-255)
const VIRIDIS: Array<[number, number, number]> = [
  [68, 1, 84],
  [72, 40, 120],
  [62, 74, 137],
  [49, 104, 142],
  [38, 130, 142],
  [31, 158, 137],
  [53, 183, 121],
  [110, 206, 88],
  [181, 222, 43],
  [253, 231, 37],
];

// Default categorical palette (up to 20 categories)
const CATEGORICAL_PALETTE: Array<[number, number, number]> = [
  [31, 119, 180],
  [255, 127, 14],
  [44, 160, 44],
  [214, 39, 40],
  [148, 103, 189],
  [140, 86, 75],
  [227, 119, 194],
  [127, 127, 127],
  [188, 189, 34],
  [23, 190, 207],
  [174, 199, 232],
  [255, 187, 120],
  [152, 223, 138],
  [255, 152, 150],
  [197, 176, 213],
  [196, 156, 148],
  [247, 182, 210],
  [199, 199, 199],
  [219, 219, 141],
  [158, 218, 229],
];

// ---------------------------------------------------------------------------
// View fitting (deck.gl OrthographicView)
// ---------------------------------------------------------------------------

export interface FittedEmbeddingView {
  target: [number, number, number];
  zoom: number;
  /** Bounds used for zoom math (same as embedding.bounds; exposed for diagnostics). */
  dataWidth: number;
  dataHeight: number;
}

/** Orthographic view state we pass to deck.gl (controller may add extra fields). */
export interface EmbeddingOrthoViewState {
  target: [number, number, number];
  zoom: number;
  transitionDuration?: number;
}

function parseDeckZoom(raw: unknown): number {
  if (typeof raw === 'number') return raw;
  if (Array.isArray(raw) && typeof raw[0] === 'number') return raw[0];
  return 0;
}

function viewStateFromDeckCallback(viewState: unknown): EmbeddingOrthoViewState | null {
  if (typeof viewState !== 'object' || viewState === null) return null;
  const vs = viewState as {
    target?: unknown;
    zoom?: unknown;
    transitionDuration?: unknown;
  };
  if (!Array.isArray(vs.target) || vs.target.length < 2) return null;
  const tgt = vs.target;
  const el0: unknown = tgt[0];
  const el1: unknown = tgt[1];
  const el2: unknown = tgt[2];
  if (typeof el0 !== 'number' || typeof el1 !== 'number') return null;
  const z = parseDeckZoom(vs.zoom);
  return {
    target: [el0, el1, typeof el2 === 'number' ? el2 : 0],
    zoom: z,
    transitionDuration:
      typeof vs.transitionDuration === 'number' ? vs.transitionDuration : undefined,
  };
}

/**
 * Compute OrthographicView state so embedding bounds fill the viewport (letterboxed).
 * See https://deck.gl/docs/api-reference/core/orthographic-view — zoom 0 => 1 world unit = 1 px.
 */
export function computeOrthographicFit(params: {
  bounds: { minX: number; maxX: number; minY: number; maxY: number };
  viewportCssPx: { w: number; h: number };
  fillFraction?: number;
}): FittedEmbeddingView {
  const fill = params.fillFraction ?? VIEWPORT_FILL_FRACTION;
  const { minX, maxX, minY, maxY } = params.bounds;
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const dataW = Math.max(maxX - minX, 1e-12);
  const dataH = Math.max(maxY - minY, 1e-12);
  const availW = Math.max(params.viewportCssPx.w * fill, 1);
  const availH = Math.max(params.viewportCssPx.h * fill, 1);
  // span in pixels at zoom z is span_world * 2^z
  const zoomX = Math.log2(availW / dataW);
  const zoomY = Math.log2(availH / dataH);
  const zoom = Math.min(zoomX, zoomY, MAX_ZOOM);
  const zoomClamped = Math.max(zoom, MIN_ZOOM);
  return {
    target: [cx, cy, 0],
    zoom: zoomClamped,
    dataWidth: dataW,
    dataHeight: dataH,
  };
}

export interface EmbeddingRendererOptions {
  formatCategoryLegendLabel?: (field: string, rawValue: string) => string;
  /**
   * On-plot centroid text only. When omitted, {@link formatCategoryLegendLabel} is used
   * (which can inject cluster-inspector biology names and disagree with View by).
   */
  formatCentroidLabel?: (field: string, rawValue: string) => string;
  /** Shorter in-plot label text; legend / tooltips use full formatter. */
  formatPlotLabelShort?: (field: string, rawValue: string) => string;
  /** Log fit diagnostics once after first layout (also if localStorage zerna:embedding:debug=1). */
  enableFitLogging?: boolean;
}

export interface EmbeddingDebugSnapshot {
  embeddingBounds: { minX: number; maxX: number; minY: number; maxY: number };
  fitted: FittedEmbeddingView;
  viewportCss: { w: number; h: number };
  lastViewStateZoom: number;
  /** True when current camera matches the stored fitted target/zoom (within tolerance). */
  cameraMatchesFittedExtent: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Sample the viridis scale for a normalised value in [0, 1]. */
function sampleViridis(t: number): [number, number, number] {
  const clamped = Math.max(0, Math.min(1, t));
  const idx = clamped * (VIRIDIS.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.min(lo + 1, VIRIDIS.length - 1);
  const frac = idx - lo;
  return [
    Math.round(VIRIDIS[lo][0] + frac * (VIRIDIS[hi][0] - VIRIDIS[lo][0])),
    Math.round(VIRIDIS[lo][1] + frac * (VIRIDIS[hi][1] - VIRIDIS[lo][1])),
    Math.round(VIRIDIS[lo][2] + frac * (VIRIDIS[hi][2] - VIRIDIS[lo][2])),
  ];
}

/** Partition cells into spatial tiles for large datasets. */
function buildTiles(embedding: Embedding): Tile[] {
  const { cells } = embedding;
  if (cells.length <= LARGE_DATASET_THRESHOLD) {
    return [
      {
        id: 'tile-0',
        bounds: embedding.bounds,
        cellIndices: cells.map((_, i) => i),
      },
    ];
  }

  const { minX, maxX, minY, maxY } = embedding.bounds;
  const cols = Math.ceil(Math.sqrt(cells.length / TILE_SIZE));
  const rows = cols;
  const cellW = (maxX - minX) / cols;
  const cellH = (maxY - minY) / rows;

  const tileMap = new Map<string, number[]>();

  cells.forEach((cell, idx) => {
    const col = Math.min(Math.floor((cell.x - minX) / cellW), cols - 1);
    const row = Math.min(Math.floor((cell.y - minY) / cellH), rows - 1);
    const key = `${row}-${col}`;
    if (!tileMap.has(key)) tileMap.set(key, []);
    tileMap.get(key)!.push(idx);
  });

  const tiles: Tile[] = [];
  tileMap.forEach((indices, key) => {
    const [r, c] = key.split('-').map(Number);
    tiles.push({
      id: `tile-${key}`,
      bounds: {
        minX: minX + c * cellW,
        maxX: minX + (c + 1) * cellW,
        minY: minY + r * cellH,
        maxY: minY + (r + 1) * cellH,
      },
      cellIndices: indices,
    });
  });

  return tiles;
}

/** Test whether a point is inside a polygon (ray-casting). */
function pointInPolygon(point: Point, polygon: Point[]): boolean {
  let inside = false;
  const { x, y } = point;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i].x;
    const yi = polygon[i].y;
    const xj = polygon[j].x;
    const yj = polygon[j].y;
    const intersect = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

interface CentroidLabel {
  x: number;
  y: number;
  text: string;
}

function spatiallyThinCentroids(
  items: Array<{ raw: string; x: number; y: number; n: number }>,
  minDist: number,
  maxOut: number
): typeof items {
  const out: typeof items = [];
  for (const item of items) {
    if (out.length >= maxOut) break;
    const ok = out.every((o) => {
      const dx = item.x - o.x;
      const dy = item.y - o.y;
      return Math.hypot(dx, dy) >= minDist;
    });
    if (ok) out.push(item);
  }
  return out;
}

function computeCentroidLabels(
  embedding: Embedding,
  metadata: CellMetadata[],
  field: string,
  formatLabel: (raw: string) => string,
  opts: {
    plotShort?: (raw: string) => string;
    focusOnlyRaw?: string | null;
  }
): CentroidLabel[] {
  const metaById = new Map(metadata.map((m) => [m.cellId, m]));
  const groups = new Map<string, { sx: number; sy: number; n: number }>();
  for (const c of embedding.cells) {
    const m = metaById.get(c.id);
    const raw = String(m?.[field] ?? '').trim();
    if (!raw) continue;
    const g = groups.get(raw) ?? { sx: 0, sy: 0, n: 0 };
    g.sx += c.x;
    g.sy += c.y;
    g.n += 1;
    groups.set(raw, g);
  }

  let entries = [...groups.entries()].filter(([, g]) => g.n >= MIN_CELLS_PER_LABEL);

  if (opts.focusOnlyRaw != null && opts.focusOnlyRaw !== '') {
    const hit = entries.find(([r]) => r === opts.focusOnlyRaw);
    entries = hit ? [hit] : [];
  }

  const sorted = entries.sort((a, b) => b[1].n - a[1].n);
  const { minX, maxX, minY, maxY } = embedding.bounds;
  const span = Math.max(maxX - minX, maxY - minY, 1e-9);
  const minDist = span * MIN_LABEL_CENTROID_SEP_FRAC;

  const maxLabels =
    opts.focusOnlyRaw != null && opts.focusOnlyRaw !== ''
      ? MAX_CENTROID_LABELS_FOCUS
      : MAX_CENTROID_LABELS_NORMAL;

  const candidates = sorted.slice(0, maxLabels * 3).map(([raw, g]) => ({
    raw,
    x: g.sx / g.n,
    y: g.sy / g.n,
    n: g.n,
  }));

  const thinned =
    opts.focusOnlyRaw != null && candidates.length <= 1
      ? candidates
      : spatiallyThinCentroids(candidates, minDist, maxLabels);

  const toText = (raw: string) => {
    const full = formatLabel(raw);
    const t = opts.plotShort ? opts.plotShort(raw) : shortenPlotLabel(full);
    return t.length > 40 ? `${t.slice(0, 37)}…` : t;
  };

  return thinned.map(({ raw, x, y }) => ({
    x,
    y,
    text: toText(raw),
  }));
}

function pixelsPerWorldUnit(zoom: number): number {
  return Math.pow(2, zoom);
}

/**
 * Point radius in pixels: scales with zoom and global density so categories stay visible when fitted.
 */
/** Match categorical coloring used by ``EmbeddingRenderer`` (for legend swatches). */
export function categoricalRgbForValue(
  rawValue: string,
  palette?: Record<string, [number, number, number]>
): [number, number, number] {
  if (palette && palette[rawValue]) {
    return palette[rawValue];
  }
  const hash = rawValue.split('').reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  return CATEGORICAL_PALETTE[hash % CATEGORICAL_PALETTE.length];
}

function computePointRadiusPixels(zoom: number, embedding: Embedding): number {
  const { minX, maxX, minY, maxY } = embedding.bounds;
  const area = Math.max((maxX - minX) * (maxY - minY), 1e-12);
  const n = Math.max(embedding.cells.length, 1);
  const density = n / area;
  const meanSpacingWorld = 1 / Math.sqrt(density);
  const ppu = pixelsPerWorldUnit(zoom);
  const meanSpacingPx = meanSpacingWorld * ppu;
  const fromDensity = meanSpacingPx * 0.22;
  return Math.min(10, Math.max(1.5, fromDensity));
}

// ---------------------------------------------------------------------------
// EmbeddingRenderer
// ---------------------------------------------------------------------------

export class EmbeddingRenderer {
  // deck.gl's published types do not model OrthographicView target state cleanly.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private deck: Deck<any> | null = null;
  private embedding: Embedding;
  private metadata: CellMetadata[];
  private colorMapping: ColorMapping;
  private tiles: Tile[];
  private metaByCell: Map<string, CellMetadata>;
  private onSelectionChange: (cellIds: string[]) => void;
  private options: EmbeddingRendererOptions;

  private viewState: EmbeddingOrthoViewState | null = null;
  private _currentZoomLevel = 0;
  private _cssWidth = 800;
  private _cssHeight = 600;
  private _fitted: FittedEmbeddingView | null = null;
  private _labelsEnabled = false;
  private _labelField: string | null = null;
  /** When label field matches focus, only that centroid is labeled. */
  private _labelFocus: { field: string; rawValue: string } | null = null;
  private _fitLogged = false;
  /** Dim non-matching cells while keeping full embedding context. */
  private _focus: { field: string; rawValue: string } | null = null;
  /** Temporary highlight from legend hover. */
  private _hover: { field: string; rawValue: string } | null = null;

  constructor(
    canvas: HTMLCanvasElement,
    embedding: Embedding,
    metadata: CellMetadata[],
    colorMapping: ColorMapping,
    onSelectionChange: (cellIds: string[]) => void,
    options: EmbeddingRendererOptions = {}
  ) {
    this.embedding = embedding;
    this.metadata = metadata;
    this.colorMapping = colorMapping;
    this.onSelectionChange = onSelectionChange;
    this.options = options;

    this.metaByCell = new Map(metadata.map((m) => [m.cellId, m]));
    this.tiles = buildTiles(embedding);

    this._initDeck(canvas);
  }

  // -------------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------------

  renderTiles(viewport: Viewport, lod: number): void {
    if (!this.deck) return;

    const visibleTiles = this.tiles.filter((tile) => this._tileIntersectsViewport(tile, viewport));

    const layers = visibleTiles.map((tile) => this._buildScatterLayer(tile, lod, viewport.zoom));

    this.deck.setProps({ layers });
  }

  updateColors(colorMapping: ColorMapping): void {
    this.colorMapping = colorMapping;
    if (!this.deck) return;

    this.deck.setProps({ layers: this._buildAllLayers(this._currentZoomLevel) });
    this.deck.redraw('colors');
  }

  /**
   * Toggle centroid labels for the given metadata field.
   * When ``focusCategory`` matches ``field``, only that category gets a centroid label.
   */
  setLabelsOptions(opts: {
    enabled: boolean;
    field: string | null;
    focusCategory?: { field: string; rawValue: string } | null;
  }): void {
    this._labelsEnabled = opts.enabled && opts.field != null && opts.field !== '';
    this._labelField = this._labelsEnabled ? opts.field : null;
    const f = opts.focusCategory;
    this._labelFocus =
      f && opts.field && f.field === opts.field
        ? { field: f.field, rawValue: String(f.rawValue) }
        : null;
    if (!this.deck) return;
    this.deck.setProps({ layers: this._buildAllLayers(this._currentZoomLevel) });
    this.deck.redraw('labels');
  }

  /**
   * Focus one categorical value for the current color-by field: other cells are muted (light gray, low alpha).
   * Only applies when ``colorMapping.type === 'categorical'`` and ``field`` matches the active color field.
   */
  setFocusCategory(field: string | null, rawValue: string | null): void {
    if (field && rawValue != null && String(rawValue).length > 0) {
      this._focus = { field, rawValue: String(rawValue) };
    } else {
      this._focus = null;
    }
    if (!this.deck) return;
    this.deck.setProps({ layers: this._buildAllLayers(this._currentZoomLevel) });
    this.deck.redraw('focus');
  }

  /** Legend hover: dim other categories slightly less than focus. */
  setHoverCategory(field: string | null, rawValue: string | null): void {
    if (field && rawValue != null && String(rawValue).length > 0) {
      this._hover = { field, rawValue: String(rawValue) };
    } else {
      this._hover = null;
    }
    if (!this.deck) return;
    this.deck.setProps({ layers: this._buildAllLayers(this._currentZoomLevel) });
    this.deck.redraw('hover');
  }

  resizeViewport(cssWidth: number, cssHeight: number): void {
    if (!this.deck) return;
    const w = Math.max(1, Math.round(cssWidth));
    const h = Math.max(1, Math.round(cssHeight));
    this._cssWidth = w;
    this._cssHeight = h;

    const fitted = computeOrthographicFit({
      bounds: this.embedding.bounds,
      viewportCssPx: { w, h },
      fillFraction: VIEWPORT_FILL_FRACTION,
    });
    this._fitted = fitted;
    this._currentZoomLevel = fitted.zoom;

    const base = this.viewState ?? {
      target: [0, 0, 0] as [number, number, number],
      zoom: 0,
    };
    const nextView: EmbeddingOrthoViewState = {
      ...base,
      target: fitted.target,
      zoom: fitted.zoom,
      transitionDuration: 0,
    };
    this.viewState = nextView;

    this.deck.setProps({
      width: w,
      height: h,
      viewState: nextView,
      layers: this._buildAllLayers(fitted.zoom),
    });
    this.deck.redraw('resize');

    this._maybeLogFit('resize', fitted);
  }

  selectCells(lassoPath: Point[]): string[] {
    if (lassoPath.length < 3) return [];

    const selected: string[] = [];
    for (const cell of this.embedding.cells) {
      if (pointInPolygon({ x: cell.x, y: cell.y }, lassoPath)) {
        selected.push(cell.id);
      }
    }

    this.onSelectionChange(selected);
    return selected;
  }

  /** Reset camera to the fitted embedding extent (same as initial load / resize refit). */
  zoomToFit(): void {
    if (!this.deck) return;
    const fitted = computeOrthographicFit({
      bounds: this.embedding.bounds,
      viewportCssPx: { w: this._cssWidth, h: this._cssHeight },
      fillFraction: VIEWPORT_FILL_FRACTION,
    });
    this._fitted = fitted;
    this._currentZoomLevel = fitted.zoom;

    const base = this.viewState ?? {
      target: [0, 0, 0] as [number, number, number],
      zoom: 0,
    };
    const nextView: EmbeddingOrthoViewState = {
      ...base,
      target: fitted.target,
      zoom: fitted.zoom,
      transitionDuration: 200,
    };
    this.viewState = nextView;

    this.deck.setProps({
      viewState: nextView,
      layers: this._buildAllLayers(fitted.zoom),
    });
    this.deck.redraw('zoomToFit');

    this._maybeLogFit('reset', fitted);
  }

  getDebugSnapshot(): EmbeddingDebugSnapshot | null {
    if (!this.deck) return null;
    const fitted =
      this._fitted ??
      computeOrthographicFit({
        bounds: this.embedding.bounds,
        viewportCssPx: { w: this._cssWidth, h: this._cssHeight },
      });
    const vs = this.viewState;
    const t = vs?.target;
    const z = this._currentZoomLevel;
    let cameraMatchesFittedExtent = false;
    if (t && t.length >= 2) {
      const ex = 1e-6 * Math.max(fitted.dataWidth, 1e-12);
      const ey = 1e-6 * Math.max(fitted.dataHeight, 1e-12);
      cameraMatchesFittedExtent =
        Math.abs(z - fitted.zoom) < 0.02 &&
        Math.abs(t[0] - fitted.target[0]) <= ex &&
        Math.abs(t[1] - fitted.target[1]) <= ey;
    }
    return {
      embeddingBounds: { ...this.embedding.bounds },
      fitted,
      viewportCss: { w: this._cssWidth, h: this._cssHeight },
      lastViewStateZoom: z,
      cameraMatchesFittedExtent,
    };
  }

  destroy(): void {
    this.deck?.finalize();
    this.deck = null;
  }

  // -------------------------------------------------------------------------
  // Private
  // -------------------------------------------------------------------------

  private _maybeLogFit(reason: string, fitted: FittedEmbeddingView): void {
    let verbose = false;
    try {
      verbose =
        typeof window !== 'undefined' &&
        window.localStorage?.getItem('zerna:embedding:debug') === '1';
    } catch {
      /* ignore */
    }
    const force = this.options.enableFitLogging === true;
    const devOnce =
      process.env.NODE_ENV === 'development' &&
      !this._fitLogged &&
      this.options.enableFitLogging !== false;
    if (!verbose && !force && !devOnce) return;
    if (!verbose && devOnce) this._fitLogged = true;
    const b = this.embedding.bounds;

    console.info('[Zerna embedding fit]', {
      reason,
      embeddingXY: { minX: b.minX, maxX: b.maxX, minY: b.minY, maxY: b.maxY },
      dataSpan: { w: fitted.dataWidth, h: fitted.dataHeight },
      viewportCss: { w: this._cssWidth, h: this._cssHeight },
      fittedTarget: fitted.target,
      fittedZoom: fitted.zoom,
      viewportFillFraction: VIEWPORT_FILL_FRACTION,
      reasonDetail: reason,
      hint: 'localStorage zerna:embedding:debug=1 logs every resize/reset.',
    });
  }

  private _onViewStateChange = (info: { viewState: unknown }): void => {
    if (!this.deck) return;
    const vs = viewStateFromDeckCallback(info.viewState);
    if (!vs) return;
    const z = vs.zoom;
    const zoomChanged = Math.abs(z - this._currentZoomLevel) > 1e-5;
    this._currentZoomLevel = z;
    this.viewState = vs;
    if (zoomChanged) {
      this.deck.setProps({
        viewState: vs,
        layers: this._buildAllLayers(z),
      });
    } else {
      this.deck.setProps({ viewState: vs });
    }
  };

  private _initDeck(canvas: HTMLCanvasElement): void {
    const gl = canvas.getContext('webgl2', {
      alpha: true,
      antialias: true,
      preserveDrawingBuffer: false,
    });

    if (!gl) {
      throw new Error('WebGL2 is unavailable for the embedding viewer');
    }

    const rect =
      typeof canvas.getBoundingClientRect === 'function' ? canvas.getBoundingClientRect() : null;
    let cssW = rect ? Math.round(rect.width) : 0;
    let cssH = rect ? Math.round(rect.height) : 0;
    if (cssW < 2 || cssH < 2) {
      cssW = canvas.clientWidth || canvas.width || 800;
      cssH = canvas.clientHeight || canvas.height || 600;
    }
    this._cssWidth = cssW;
    this._cssHeight = cssH;

    const fitted = computeOrthographicFit({
      bounds: this.embedding.bounds,
      viewportCssPx: { w: cssW, h: cssH },
      fillFraction: VIEWPORT_FILL_FRACTION,
    });
    this._fitted = fitted;
    this._currentZoomLevel = fitted.zoom;

    const initialVs: EmbeddingOrthoViewState = {
      target: fitted.target,
      zoom: fitted.zoom,
      transitionDuration: 0,
    };
    this.viewState = initialVs;

    this.deck = new Deck({
      gl,
      width: cssW,
      height: cssH,
      useDevicePixels: true,
      views: new OrthographicView({ id: 'ortho' }),
      viewState: initialVs,
      controller: true,
      onViewStateChange: this._onViewStateChange,
      layers: this._buildAllLayers(fitted.zoom),
    });
    this.deck.redraw('init');

    this._maybeLogFit('init', fitted);
  }

  private _buildAllLayers(zoom: number): (ScatterplotLayer | TextLayer)[] {
    const radius = computePointRadiusPixels(zoom, this.embedding);
    const scatterLayers = this.tiles.map((tile) => this._buildScatterLayer(tile, 1, zoom, radius));

    if (this._labelsEnabled && this._labelField) {
      const lf = this._labelField;
      const fmt = this.options.formatCentroidLabel ?? this.options.formatCategoryLegendLabel;
      const fmtShort = this.options.formatPlotLabelShort;
      const formatOne = (raw: string) => (fmt ? fmt(lf, raw) : raw);
      const plotShort = fmtShort ? (raw: string) => fmtShort(lf, raw) : undefined;
      const focusOnlyRaw =
        this._labelFocus && this._labelFocus.field === lf ? this._labelFocus.rawValue : null;
      const items = computeCentroidLabels(this.embedding, this.metadata, lf, formatOne, {
        plotShort,
        focusOnlyRaw,
      });
      if (items.length > 0) {
        const labelLayer = new TextLayer({
          id: 'embedding-centroid-labels',
          coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
          data: items,
          getPosition: (d: CentroidLabel) => [d.x, d.y, 0] as [number, number, number],
          getText: (d: CentroidLabel) => d.text,
          getSize: 12,
          sizeUnits: 'pixels',
          getColor: [25, 35, 50, 255],
          outlineWidth: 2,
          outlineColor: [255, 255, 255, 230],
          fontFamily: 'ui-sans-serif, system-ui, sans-serif',
          pickable: false,
        });
        return [...scatterLayers, labelLayer];
      }
    }

    return scatterLayers;
  }

  private _buildScatterLayer(
    tile: Tile,
    lod: number,
    zoom: number,
    radiusOverride?: number
  ): ScatterplotLayer {
    const cells = tile.cellIndices.map((i) => this.embedding.cells[i]);
    const base = radiusOverride ?? computePointRadiusPixels(zoom, this.embedding);
    const radius = Math.max(1, base / lod);

    return new ScatterplotLayer({
      id: `scatter-${tile.id}`,
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      data: cells,
      getPosition: (d: EmbeddingCell) => [d.x, d.y, 0] as [number, number, number],
      getRadius: radius,
      radiusUnits: 'pixels',
      getFillColor: (d: EmbeddingCell) => this._getColor(d.id),
      pickable: true,
      updateTriggers: {
        getFillColor: [this.colorMapping, this._focus, this._hover],
        getRadius: [zoom, this.embedding.cells.length],
      },
    });
  }

  private _getColor(cellId: string): [number, number, number, number] {
    const meta = this.metaByCell.get(cellId);
    const cm = this.colorMapping;

    let rgba: [number, number, number, number];

    if (cm.type === 'continuous') {
      const value = meta ? (meta[cm.field] as number | undefined) : undefined;
      if (value == null) rgba = [180, 180, 180, 200];
      else {
        const t = (value - cm.min) / (cm.max - cm.min || 1);
        const [r, g, b] = sampleViridis(t);
        rgba = [r, g, b, 220];
      }
    } else {
      const value = meta ? String(meta[cm.field] ?? '') : '';
      if (cm.palette && cm.palette[value]) {
        const [r, g, b] = cm.palette[value];
        rgba = [r, g, b, 220];
      } else {
        const [r, g, b] = categoricalRgbForValue(value, cm.palette);
        rgba = [r, g, b, 220];
      }
    }

    if (cm.type === 'categorical') {
      const v = meta ? String(meta[cm.field] ?? '').trim() : '';
      if (this._focus && this._focus.field === cm.field && v !== this._focus.rawValue) {
        return [236, 236, 236, 42];
      }
      if (
        this._hover &&
        !this._focus &&
        this._hover.field === cm.field &&
        v !== this._hover.rawValue
      ) {
        return [rgba[0], rgba[1], rgba[2], 72];
      }
    }

    return rgba;
  }

  private _tileIntersectsViewport(tile: Tile, viewport: Viewport): boolean {
    const { x, y, width, height } = viewport;
    const vMaxX = x + width;
    const vMaxY = y + height;
    return (
      tile.bounds.minX < vMaxX &&
      tile.bounds.maxX > x &&
      tile.bounds.minY < vMaxY &&
      tile.bounds.maxY > y
    );
  }
}
