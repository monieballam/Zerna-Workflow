/**
 * TypeScript types for the WebGL embedding renderer.
 * Supports large single-cell embeddings (UMAP, t-SNE) with tile-based rendering.
 */

/** A 2D point in embedding space */
export interface Point {
  x: number;
  y: number;
}

/** Viewport describing the visible region of the embedding canvas */
export interface Viewport {
  x: number;
  y: number;
  width: number;
  height: number;
  zoom: number;
}

/** A single cell's position in the embedding */
export interface EmbeddingCell {
  /** Unique cell identifier */
  id: string;
  /** X coordinate in embedding space */
  x: number;
  /** Y coordinate in embedding space */
  y: number;
}

/** The full embedding dataset */
export interface Embedding {
  /** Ordered list of cells with their 2D coordinates */
  cells: EmbeddingCell[];
  /** Bounding box of the embedding space */
  bounds: {
    minX: number;
    maxX: number;
    minY: number;
    maxY: number;
  };
}

/** Metadata for a single cell */
export interface CellMetadata {
  /** Cell identifier matching EmbeddingCell.id */
  cellId: string;
  /** Cluster assignment */
  cluster?: string;
  /** Cell type annotation */
  cellType?: string;
  /** Arbitrary key-value metadata */
  [key: string]: string | number | boolean | undefined;
}

/** Continuous color mapping (e.g. gene expression, pathway score) */
export interface ContinuousColorMapping {
  type: 'continuous';
  /** Metadata key to color by */
  field: string;
  /** Minimum value for color scale */
  min: number;
  /** Maximum value for color scale */
  max: number;
  /** Color scale name — "viridis" is the default */
  scale?: 'viridis';
}

/** Categorical color mapping (e.g. cluster, cell type) */
export interface CategoricalColorMapping {
  type: 'categorical';
  /** Metadata key to color by */
  field: string;
  /** Map from category value to [R, G, B] color (0-255) */
  palette?: Record<string, [number, number, number]>;
}

export type ColorMapping = ContinuousColorMapping | CategoricalColorMapping;

/** A tile covering a spatial region of the embedding */
export interface Tile {
  id: string;
  bounds: { minX: number; maxX: number; minY: number; maxY: number };
  /** Indices into the parent Embedding.cells array */
  cellIndices: number[];
}
