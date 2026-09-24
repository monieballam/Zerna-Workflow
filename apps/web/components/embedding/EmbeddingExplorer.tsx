'use client';

import { useState, useMemo, useCallback } from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface EmbeddingPoint {
  cellId: string;
  x: number;
  y: number;
  metadata: Record<string, string | number>;
}

export interface GeneOverlay {
  gene: string;
  values: Record<string, number>; // cellId -> expression
}

export interface EmbeddingExplorerProps {
  points: EmbeddingPoint[];
  metadataFields: string[];
  availableGenes?: string[];
  onLoadGeneOverlay?: (gene: string) => Promise<GeneOverlay>;
  splitFields?: string[];
}

type ViewMode = 'single' | 'split';

// ── Filter Panel ──────────────────────────────────────────────────────────────

function FilterPanel({
  metadataFields,
  activeFilters,
  onToggleFilter,
}: {
  metadataFields: string[];
  activeFilters: Record<string, Set<string>>;
  onToggleFilter: (field: string, value: string) => void;
}) {
  const [expandedField, setExpandedField] = useState<string | null>(null);

  return (
    <div className="space-y-2" data-testid="filter-panel">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Filters</h3>
      {metadataFields.map((field) => (
        <div key={field} className="border border-gray-200 rounded">
          <button
            onClick={() => setExpandedField(expandedField === field ? null : field)}
            className="w-full text-left px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 flex justify-between items-center"
          >
            <span>{field}</span>
            <span className="text-xs text-gray-400">{activeFilters[field]?.size ?? 0} active</span>
          </button>
          {expandedField === field && (
            <div className="px-3 pb-2 space-y-1 max-h-40 overflow-y-auto">
              <button
                onClick={() => {
                  (activeFilters[field] ?? new Set()).forEach((v) => onToggleFilter(field, v));
                }}
                className="text-xs text-blue-600 hover:underline"
              >
                Clear all
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Gene Overlay Selector ─────────────────────────────────────────────────────

function GeneOverlaySelector({
  availableGenes,
  selectedGene,
  onSelectGene,
  isLoading,
}: {
  availableGenes: string[];
  selectedGene: string | null;
  onSelectGene: (gene: string | null) => void;
  isLoading: boolean;
}) {
  const [search, setSearch] = useState('');
  const filtered = useMemo(
    () => availableGenes.filter((g) => g.toLowerCase().includes(search.toLowerCase())).slice(0, 50),
    [availableGenes, search]
  );

  return (
    <div className="space-y-2" data-testid="gene-overlay-selector">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Gene Overlay</h3>
      <input
        type="text"
        placeholder="Search genes…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
      />
      {selectedGene && (
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-blue-700">{selectedGene}</span>
          <button
            onClick={() => onSelectGene(null)}
            className="text-xs text-gray-400 hover:text-gray-600"
          >
            ✕
          </button>
          {isLoading && <span className="text-xs text-gray-400">Loading…</span>}
        </div>
      )}
      <ul className="max-h-32 overflow-y-auto space-y-0.5">
        {filtered.map((gene) => (
          <li key={gene}>
            <button
              onClick={() => onSelectGene(gene)}
              className={`w-full text-left px-2 py-1 text-xs rounded hover:bg-gray-100 ${
                selectedGene === gene ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-700'
              }`}
            >
              {gene}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Embedding Canvas (simplified scatter) ─────────────────────────────────────

function EmbeddingCanvas({
  points,
  colorBy,
  geneOverlay,
}: {
  points: EmbeddingPoint[];
  colorBy: string;
  geneOverlay: GeneOverlay | null;
}) {
  const svgWidth = 600;
  const svgHeight = 450;
  const padding = 30;

  const { xMin, xMax, yMin, yMax } = useMemo(() => {
    if (points.length === 0) return { xMin: 0, xMax: 1, yMin: 0, yMax: 1 };
    let xMin = Infinity,
      xMax = -Infinity,
      yMin = Infinity,
      yMax = -Infinity;
    for (const p of points) {
      if (p.x < xMin) xMin = p.x;
      if (p.x > xMax) xMax = p.x;
      if (p.y < yMin) yMin = p.y;
      if (p.y > yMax) yMax = p.y;
    }
    return { xMin, xMax, yMin, yMax };
  }, [points]);

  const scaleX = (v: number) =>
    padding + ((v - xMin) / (xMax - xMin || 1)) * (svgWidth - 2 * padding);
  const scaleY = (v: number) =>
    padding + ((v - yMin) / (yMax - yMin || 1)) * (svgHeight - 2 * padding);

  return (
    <svg
      width={svgWidth}
      height={svgHeight}
      className="block w-full border border-gray-200 rounded bg-white"
      data-testid="embedding-canvas"
      role="img"
      aria-label={`Embedding scatter plot colored by ${geneOverlay ? geneOverlay.gene : colorBy}`}
    >
      {points.map((p) => (
        <circle
          key={p.cellId}
          cx={scaleX(p.x)}
          cy={scaleY(p.y)}
          r={1.5}
          fill={geneOverlay ? expressionColor(geneOverlay.values[p.cellId] ?? 0) : '#6366f1'}
          opacity={0.7}
        />
      ))}
    </svg>
  );
}

function expressionColor(value: number): string {
  // Simple blue-to-red gradient for gene expression
  const clamped = Math.max(0, Math.min(1, value));
  const r = Math.round(clamped * 220);
  const b = Math.round((1 - clamped) * 220);
  return `rgb(${r}, 40, ${b})`;
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function EmbeddingExplorer({
  points,
  metadataFields,
  availableGenes = [],
  onLoadGeneOverlay,
  splitFields = [],
}: EmbeddingExplorerProps) {
  const [colorBy, setColorBy] = useState(metadataFields[0] ?? 'cluster');
  const [viewMode, setViewMode] = useState<ViewMode>('single');
  const [splitField, setSplitField] = useState(splitFields[0] ?? '');
  const [selectedGene, setSelectedGene] = useState<string | null>(null);
  const [geneOverlay, setGeneOverlay] = useState<GeneOverlay | null>(null);
  const [isLoadingGene, setIsLoadingGene] = useState(false);
  const [activeFilters, setActiveFilters] = useState<Record<string, Set<string>>>({});

  const handleToggleFilter = useCallback((field: string, value: string) => {
    setActiveFilters((prev) => {
      const next = { ...prev };
      const set = new Set(next[field] ?? []);
      if (set.has(value)) set.delete(value);
      else set.add(value);
      next[field] = set;
      return next;
    });
  }, []);

  const handleSelectGene = useCallback(
    async (gene: string | null) => {
      setSelectedGene(gene);
      if (!gene) {
        setGeneOverlay(null);
        return;
      }
      if (onLoadGeneOverlay) {
        setIsLoadingGene(true);
        try {
          const overlay = await onLoadGeneOverlay(gene);
          setGeneOverlay(overlay);
        } finally {
          setIsLoadingGene(false);
        }
      }
    },
    [onLoadGeneOverlay]
  );

  // Apply filters
  const filteredPoints = useMemo(() => {
    const filterEntries = Object.entries(activeFilters).filter(([, set]) => set.size > 0);
    if (filterEntries.length === 0) return points;
    return points.filter((p) =>
      filterEntries.every(([field, allowed]) => allowed.has(String(p.metadata[field] ?? '')))
    );
  }, [points, activeFilters]);

  // Split view groups
  const splitGroups = useMemo(() => {
    if (viewMode !== 'split' || !splitField) return null;
    const groups: Record<string, EmbeddingPoint[]> = {};
    for (const p of filteredPoints) {
      const key = String(p.metadata[splitField] ?? 'unknown');
      (groups[key] ??= []).push(p);
    }
    return groups;
  }, [viewMode, splitField, filteredPoints]);

  return (
    <div className="flex gap-4" data-testid="embedding-explorer">
      {/* Sidebar controls */}
      <div className="w-56 shrink-0 space-y-4">
        {/* Color-by selector */}
        <div>
          <label
            htmlFor="explorer-color-by"
            className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1"
          >
            Color by
          </label>
          <select
            id="explorer-color-by"
            value={colorBy}
            onChange={(e) => setColorBy(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          >
            {metadataFields.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>

        {/* View mode toggle */}
        <div>
          <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">
            View mode
          </label>
          <div className="flex gap-1">
            <button
              onClick={() => setViewMode('single')}
              className={`flex-1 px-2 py-1.5 text-xs rounded-md border ${
                viewMode === 'single'
                  ? 'border-blue-500 bg-blue-50 text-blue-700 font-medium'
                  : 'border-gray-300 text-gray-600 hover:bg-gray-50'
              }`}
            >
              Single
            </button>
            <button
              onClick={() => setViewMode('split')}
              className={`flex-1 px-2 py-1.5 text-xs rounded-md border ${
                viewMode === 'split'
                  ? 'border-blue-500 bg-blue-50 text-blue-700 font-medium'
                  : 'border-gray-300 text-gray-600 hover:bg-gray-50'
              }`}
            >
              Split
            </button>
          </div>
          {viewMode === 'split' && splitFields.length > 0 && (
            <select
              value={splitField}
              onChange={(e) => setSplitField(e.target.value)}
              className="w-full mt-1 rounded-md border border-gray-300 px-2 py-1.5 text-sm"
              aria-label="Split by field"
            >
              {splitFields.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          )}
        </div>

        <FilterPanel
          metadataFields={metadataFields}
          activeFilters={activeFilters}
          onToggleFilter={handleToggleFilter}
        />

        {availableGenes.length > 0 && (
          <GeneOverlaySelector
            availableGenes={availableGenes}
            selectedGene={selectedGene}
            onSelectGene={(gene) => {
              void handleSelectGene(gene);
            }}
            isLoading={isLoadingGene}
          />
        )}

        <div className="text-xs text-gray-400">{filteredPoints.length.toLocaleString()} cells</div>
      </div>

      {/* Main canvas area */}
      <div className="flex-1 min-w-0">
        {viewMode === 'single' || !splitGroups ? (
          <EmbeddingCanvas points={filteredPoints} colorBy={colorBy} geneOverlay={geneOverlay} />
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {Object.entries(splitGroups).map(([groupKey, groupPoints]) => (
              <div key={groupKey}>
                <h4 className="text-xs font-medium text-gray-600 mb-1">
                  {splitField}: {groupKey}
                </h4>
                <EmbeddingCanvas points={groupPoints} colorBy={colorBy} geneOverlay={geneOverlay} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
