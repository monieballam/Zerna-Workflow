'use client';

import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import EmbeddingComparison, {
  type EmbeddingEntry,
} from '@/components/embedding/EmbeddingComparison';
import LazyEmbeddingViewer from '@/components/embedding/LazyEmbeddingViewer';
import type { CellMetadata, Embedding, EmbeddingCell } from '@/lib/embedding-types';
import ClusterInspector from '@/components/runs/explorer/ClusterInspector';
import type { ClusterInspectorSummary } from '@/components/runs/explorer/cluster-inspector-types';
import EmbeddingBottomLegend from '@/components/runs/explorer/EmbeddingBottomLegend';
import EmbeddingContextStrip from '@/components/runs/explorer/EmbeddingContextStrip';
import ExploreCellsWorkspace from '@/components/runs/explorer/ExploreCellsWorkspace';
import RunCompositionOverview from '@/components/runs/explorer/RunCompositionOverview';
import type { ExplorerHierarchyFilterAxes } from '@/lib/explorer-field-metadata';
import {
  explorerColorByHintsForView,
  explorerViewByLabelForField,
  explorerViewByOptions,
  formatExplorerFieldLabel,
  hierarchyAxesArePopulated,
  hierarchyScopedLevel2Values,
  hierarchyScopedLevel3Values,
  pickDefaultExplorerColorField,
  sortExplorerFieldsForUi,
  technicalColorFieldsFromAvailable,
} from '@/lib/explorer-field-metadata';
import {
  clusterDisplayLabel,
  loadClusterAliases,
  loadGlobalAliases,
  loadViewOverrideAliases,
  saveGlobalAliases,
  saveViewOverrideAliases,
} from '@/lib/cluster-alias-storage';
import { countUniqueMetadataValues } from '@/lib/run-composition';
import {
  allowedHierarchyEmbeddingViews,
  embeddingContextDescription,
  userFacingEmbeddingCoordinateLabel,
} from '@/lib/explorer-embedding-views';
import {
  biologyClusterHeadlineFromCells,
  dominantNonEmptyMetadataField,
  formatLevel3UnresolvedDetail,
  formatLevel3UnresolvedPrimary,
  parseExplorerSyntheticNoFineLevel2,
} from '@/lib/explorer-biology-display';
import {
  applyLevel3ExplorerVizMetadata,
  EXPLORER_LEVEL3_NO_FINE_PREFIX,
} from '@/lib/embedding-legend-utils';

const EXPLORER_MAX_CELLS = 50_000;
const DEFAULT_EXPLORER_VIEW_ID = 'global';
const GENE_FIELD_PREFIX = 'geneExpression:';
const MAX_SPLIT_PANELS = 4;
/** Placeholder value when annotation color select has no active primary field (technical/gene active). */
const ANNOTATION_COLOR_PLACEHOLDER = '__annotation_pick__';
const TECH_COLOR_SENTINEL_ANNOTATION = '__tech_using_annotation__';
const TECH_COLOR_SENTINEL_GENE = '__tech_gene_overlay__';

interface CountSummary {
  label: string;
  count: number;
}

interface ExplorerViewOption {
  id: string;
  label: string;
  lineage_label: string | null;
  obsm_key: string | null;
  n_cells: number;
  embedding_ready: boolean;
}

interface ExplorerPayload {
  run_id: string;
  embedding_key: string;
  embedding: {
    cells: EmbeddingCell[];
    bounds: Embedding['bounds'];
  };
  metadata: Array<CellMetadata>;
  available_fields: string[];
  categorical_fields: string[];
  continuous_fields: string[];
  field_ranges: Record<string, { min: number; max: number }>;
  filter_fields: string[];
  /** Technical / debug cohort filters (cluster, partitions, merged cellType, displayLabel, rawAnnotationLabel, …). */
  advanced_filter_fields?: string[];
  filter_values: Record<string, string[]>;
  hierarchy_filter_axes?: ExplorerHierarchyFilterAxes;
  overview: {
    n_cells: number;
    n_genes: number;
    n_clusters: number | null;
    n_cell_types: number | null;
    n_samples: number | null;
    n_conditions: number | null;
    top_cell_types: CountSummary[];
    top_conditions: CountSummary[];
    artifact_total_cells?: number;
  };
  cluster_summaries: ClusterInspectorSummary[];
  total_cells: number;
  sampled: boolean;
  explorer_view?: string;
  explorer_view_label?: string;
  available_views?: ExplorerViewOption[];
  lineage_embedding_fallback?: boolean;
  lineage_view_unavailable_reason?: string | null;
}

interface GeneOverlayPayload {
  run_id: string;
  gene: string;
  values: Record<string, number>;
  min: number;
  max: number;
  total_cells: number;
  sampled: boolean;
}

function buildBounds(cells: EmbeddingCell[]): Embedding['bounds'] {
  if (cells.length === 0) {
    return { minX: 0, maxX: 1, minY: 0, maxY: 1 };
  }

  const xs = cells.map((cell) => cell.x);
  const ys = cells.map((cell) => cell.y);
  return {
    minX: Math.min(...xs),
    maxX: Math.max(...xs),
    minY: Math.min(...ys),
    maxY: Math.max(...ys),
  };
}

function buildGeneField(gene: string): string {
  return `${GENE_FIELD_PREFIX}${gene}`;
}

function formatClusterFilterValue(
  clusterId: string,
  displayLabel: string | undefined,
  options: { lineagePartitionView: boolean }
): string {
  if (options.lineagePartitionView) {
    if (!displayLabel || displayLabel.trim() === '' || displayLabel === clusterId) {
      return clusterId;
    }
    return `${clusterId} · ${displayLabel}`;
  }
  if (!displayLabel || displayLabel.trim() === '' || displayLabel === clusterId) {
    return `Cluster ${clusterId}`;
  }
  return `Cluster ${clusterId} · ${displayLabel}`;
}

function countUniqueClustersInCohort(metadata: CellMetadata[]): number {
  const set = new Set<string>();
  for (const m of metadata) {
    const c = m.cluster;
    if (c == null) continue;
    const s = String(c).trim();
    if (s) set.add(s);
  }
  return set.size;
}

function normalizeClusterSummaries(rows: ClusterInspectorSummary[]): ClusterInspectorSummary[] {
  return rows.map((c) => ({
    ...c,
    display_label_secondary: c.display_label_secondary ?? null,
    raw_annotation_label_mode: c.raw_annotation_label_mode ?? null,
    annotation_support_markers: c.annotation_support_markers ?? [],
    annotation_support_source_label: c.annotation_support_source_label ?? null,
    annotation_support_aligned_with_primary_headline:
      c.annotation_support_aligned_with_primary_headline !== false,
    annotation_support_partition_de_overlap: Boolean(c.annotation_support_partition_de_overlap),
    annotation_mode: c.annotation_mode ?? null,
    retrieval_tiebreak_applied: Boolean(c.retrieval_tiebreak_applied),
    conservative_status: c.conservative_status ?? null,
    conservative_reason: c.conservative_reason ?? null,
    runner_up_labels: c.runner_up_labels ?? [],
  }));
}

function StatCard({
  label,
  value,
  subtitle,
}: {
  label: string;
  value: string | number;
  subtitle?: string;
}) {
  return (
    <div className="card p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-gray-900">
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>
      {subtitle && <p className="mt-1 text-xs text-gray-400">{subtitle}</p>}
    </div>
  );
}

export default function RunExplorer({ runId }: { runId: string }) {
  const [data, setData] = useState<ExplorerPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [embeddingRefetchBusy, setEmbeddingRefetchBusy] = useState(false);
  const explorerFirstLoadRef = useRef(true);
  const [explorerViewRequestId, setExplorerViewRequestId] = useState(DEFAULT_EXPLORER_VIEW_ID);
  const [error, setError] = useState<string | null>(null);
  const [activeFilters, setActiveFilters] = useState<Record<string, Set<string>>>({});
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);
  const [colorField, setColorField] = useState('');
  const [splitField, setSplitField] = useState('');
  const [geneInput, setGeneInput] = useState('');
  const [geneOverlay, setGeneOverlay] = useState<GeneOverlayPayload | null>(null);
  const [geneLoading, setGeneLoading] = useState(false);
  const [geneError, setGeneError] = useState<string | null>(null);
  const [clusterAliases, setClusterAliases] = useState<Record<string, string>>({});
  const [focusPopulation, setFocusPopulation] = useState<{
    field: string;
    rawValue: string;
  } | null>(null);
  const [legendHoverRaw, setLegendHoverRaw] = useState<string | null>(null);
  const [labelMode, setLabelMode] = useState<'none' | 'cluster' | 'cellType'>('none');
  const [technicalColorOpen, setTechnicalColorOpen] = useState(false);

  useEffect(() => {
    setClusterAliases(loadClusterAliases(runId, explorerViewRequestId));
  }, [runId, explorerViewRequestId]);

  useEffect(() => {
    let cancelled = false;

    async function fetchExplorer() {
      const isCold = explorerFirstLoadRef.current;
      try {
        if (isCold) {
          setLoading(true);
        } else {
          setEmbeddingRefetchBusy(true);
        }
        const params = new URLSearchParams({
          max_cells: String(EXPLORER_MAX_CELLS),
          explorer_view: explorerViewRequestId,
        });
        const res = await fetch(`/api/proxy/v1/runs/${runId}/explorer?${params.toString()}`);
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const json = (await res.json()) as ExplorerPayload;
        const viewId = json.explorer_view ?? DEFAULT_EXPLORER_VIEW_ID;
        if (!cancelled) {
          setData({
            ...json,
            cluster_summaries: normalizeClusterSummaries(json.cluster_summaries),
          });
          setSelectedClusterId(json.cluster_summaries[0]?.cluster_id ?? null);
          setColorField(pickDefaultExplorerColorField(json.available_fields, viewId));
          setLabelMode('none');
          setError(null);
          explorerFirstLoadRef.current = false;
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load run explorer');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          setEmbeddingRefetchBusy(false);
        }
      }
    }

    void fetchExplorer();
    return () => {
      cancelled = true;
    };
  }, [runId, explorerViewRequestId]);

  const loadGeneOverlay = useCallback(
    async (rawGene: string) => {
      const gene = rawGene.trim();
      if (!gene) return;

      setGeneInput(gene);
      setGeneError(null);
      setGeneLoading(true);

      try {
        const res = await fetch(
          `/api/proxy/v1/runs/${runId}/gene-overlay?gene=${encodeURIComponent(gene)}&max_cells=${EXPLORER_MAX_CELLS}`
        );
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const payload = (await res.json()) as GeneOverlayPayload;
        setGeneOverlay(payload);
        setColorField(buildGeneField(payload.gene));
        setFocusPopulation(null);
        setLegendHoverRaw(null);
      } catch (err) {
        setGeneError(err instanceof Error ? err.message : 'Failed to load gene overlay');
      } finally {
        setGeneLoading(false);
      }
    },
    [runId]
  );

  const clearGeneOverlay = useCallback(() => {
    setGeneOverlay(null);
    setGeneError(null);
    setGeneInput('');
    setFocusPopulation(null);
    setLegendHoverRaw(null);
    if (data) {
      setColorField(
        pickDefaultExplorerColorField(
          data.available_fields,
          data.explorer_view ?? DEFAULT_EXPLORER_VIEW_ID
        )
      );
    }
  }, [data]);

  const handleGeneSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      void loadGeneOverlay(geneInput);
    },
    [geneInput, loadGeneOverlay]
  );

  const cohortFiltersActive = useMemo(
    () => Object.values(activeFilters).some((s) => s.size > 0),
    [activeFilters]
  );

  const filtered = useMemo(() => {
    if (!data) {
      return {
        embedding: null as Embedding | null,
        metadata: [] as CellMetadata[],
        clusterSummaries: [] as ClusterInspectorSummary[],
        shownCells: 0,
      };
    }

    const combined = data.embedding.cells.map((cell, idx) => ({
      cell,
      metadata: data.metadata[idx] ?? { cellId: cell.id },
    }));

    const filteredCombined = combined.filter(({ metadata }) =>
      Object.entries(activeFilters).every(([field, values]) => {
        if (values.size === 0) return true;
        const value = metadata[field];
        return value != null && values.has(String(value));
      })
    );

    const filteredCells = filteredCombined.map((entry) => entry.cell);
    const filteredMetadata = filteredCombined.map((entry) => entry.metadata);
    if (filteredCells.length === 0) {
      return {
        embedding: null,
        metadata: [] as CellMetadata[],
        clusterSummaries: [] as ClusterInspectorSummary[],
        shownCells: 0,
      };
    }
    const allowedClusters = new Set(
      filteredMetadata
        .map((metadata) => metadata.cluster)
        .filter((value): value is string => typeof value === 'string' && value.length > 0)
    );

    return {
      embedding: {
        cells: filteredCells,
        bounds: buildBounds(filteredCells),
      },
      metadata: filteredMetadata,
      clusterSummaries:
        filteredCombined.length === 0
          ? []
          : data.cluster_summaries.filter((cluster) =>
              allowedClusters.size === 0 ? true : allowedClusters.has(cluster.cluster_id)
            ),
      shownCells: filteredCells.length,
    };
  }, [activeFilters, data]);

  const allowedEmbeddingOptions = useMemo(
    () => allowedHierarchyEmbeddingViews(data?.available_views, activeFilters),
    [data?.available_views, activeFilters]
  );

  const allowedEmbeddingIds = useMemo(
    () => new Set(allowedEmbeddingOptions.map((o) => o.id)),
    [allowedEmbeddingOptions]
  );

  useEffect(() => {
    if (explorerViewRequestId === DEFAULT_EXPLORER_VIEW_ID) return;
    if (!allowedEmbeddingIds.has(explorerViewRequestId)) {
      setExplorerViewRequestId(DEFAULT_EXPLORER_VIEW_ID);
    }
  }, [allowedEmbeddingIds, explorerViewRequestId]);

  const embeddingSelectValue = allowedEmbeddingIds.has(explorerViewRequestId)
    ? explorerViewRequestId
    : DEFAULT_EXPLORER_VIEW_ID;

  const compositionOverviewCounts = useMemo(() => {
    if (!data) {
      return { nSamples: null as number | null, nConditions: null as number | null };
    }
    const meta = filtered.metadata;
    const fieldSet = new Set(data.available_fields);
    const uniq = (field: string): number | null => {
      if (!fieldSet.has(field)) return null;
      return countUniqueMetadataValues(meta, field);
    };
    const nS = uniq('sample');
    const nC = uniq('condition');
    if (cohortFiltersActive) {
      return { nSamples: nS, nConditions: nC };
    }
    return {
      nSamples: nS ?? data.overview.n_samples,
      nConditions: nC ?? data.overview.n_conditions,
    };
  }, [cohortFiltersActive, data, filtered.metadata]);

  /** Top summary cards: when filters are on, derive only from filtered.metadata (no overview fallback). */
  const filteredTopSummary = useMemo(() => {
    if (!data || !cohortFiltersActive) return null;
    const meta = filtered.metadata;
    const fieldSet = new Set(data.available_fields);
    const uniq = (field: string): number | null => {
      if (!fieldSet.has(field)) return null;
      return countUniqueMetadataValues(meta, field);
    };
    return {
      nClusters: countUniqueClustersInCohort(meta),
      nSamples: uniq('sample'),
      nConditions: uniq('condition'),
    };
  }, [cohortFiltersActive, data, filtered.metadata]);

  const filterPanelValues = useMemo(() => {
    if (!data) {
      return {} as Record<string, string[]>;
    }
    return { ...data.filter_values };
  }, [data]);

  useEffect(() => {
    if (!data?.hierarchy_filter_axes || !hierarchyAxesArePopulated(data.hierarchy_filter_axes)) {
      return;
    }
    const fv2 = data.filter_values.level2;
    if (!fv2?.length) return;
    const allowedL2 = new Set(
      hierarchyScopedLevel2Values(
        data.hierarchy_filter_axes,
        fv2,
        activeFilters.lineage ?? new Set()
      )
    );
    setActiveFilters((prev) => {
      const cur = prev.level2;
      if (!cur || cur.size === 0) return prev;
      const next =
        allowedL2.size === 0
          ? new Set<string>()
          : new Set([...cur].filter((v) => allowedL2.has(v)));
      if (next.size === cur.size && [...next].every((x) => cur.has(x))) return prev;
      return { ...prev, level2: next };
    });
  }, [data, activeFilters.lineage]);

  useEffect(() => {
    if (!data?.hierarchy_filter_axes || !hierarchyAxesArePopulated(data.hierarchy_filter_axes)) {
      return;
    }
    const fv = data.filter_values.level3;
    if (!fv?.length) return;
    const allowed = new Set(
      hierarchyScopedLevel3Values(
        data.hierarchy_filter_axes,
        fv,
        activeFilters.lineage ?? new Set(),
        activeFilters.level2 ?? new Set()
      )
    );
    setActiveFilters((prev) => {
      const cur = prev.level3;
      if (!cur || cur.size === 0) return prev;
      const next =
        allowed.size === 0 ? new Set<string>() : new Set([...cur].filter((v) => allowed.has(v)));
      if (next.size === cur.size && [...next].every((x) => cur.has(x))) return prev;
      return { ...prev, level3: next };
    });
  }, [data, activeFilters.lineage, activeFilters.level2]);

  useEffect(() => {
    if (!data) return;
    const allowed = new Set([...data.filter_fields, ...(data.advanced_filter_fields ?? [])]);
    setActiveFilters((prev) => {
      const next: Record<string, Set<string>> = {};
      let dropped = false;
      for (const [k, v] of Object.entries(prev)) {
        if (allowed.has(k)) {
          next[k] = v;
        } else {
          dropped = true;
        }
      }
      if (!dropped) {
        return prev;
      }
      return next;
    });
  }, [data]);

  const geneField = geneOverlay ? buildGeneField(geneOverlay.gene) : null;

  const viewerMetadata = useMemo(() => {
    if (geneOverlay == null || geneField == null) {
      return filtered.metadata;
    }
    return filtered.metadata.map((metadata) => ({
      ...metadata,
      [geneField]: geneOverlay.values[metadata.cellId] ?? 0,
    }));
  }, [filtered.metadata, geneField, geneOverlay]);

  /** Level3 color-by: empty fine subtype → stable key per major type for plot + legend (see applyLevel3ExplorerVizMetadata). */
  const embeddingDisplayMetadata = useMemo(() => {
    if (colorField !== 'level3') return viewerMetadata;
    return applyLevel3ExplorerVizMetadata(viewerMetadata);
  }, [colorField, viewerMetadata]);

  const viewerAvailableFields = useMemo(() => {
    if (!data) return [];
    if (geneField == null) return data.available_fields;
    return Array.from(new Set([...data.available_fields, geneField]));
  }, [data, geneField]);

  const viewerContinuousFields = useMemo(() => {
    if (!data) return [];
    if (geneField == null) return data.continuous_fields;
    return Array.from(new Set([...data.continuous_fields, geneField]));
  }, [data, geneField]);

  const viewerFieldRanges = useMemo(() => {
    if (!data) return {};
    if (geneField == null || geneOverlay == null) return data.field_ranges;
    return {
      ...data.field_ranges,
      [geneField]: {
        min: geneOverlay.min,
        max: geneOverlay.max,
      },
    };
  }, [data, geneField, geneOverlay]);

  const sortedViewerFields = useMemo(
    () => sortExplorerFieldsForUi(viewerAvailableFields),
    [viewerAvailableFields]
  );

  const resolvedExplorerViewId = data?.explorer_view ?? DEFAULT_EXPLORER_VIEW_ID;
  const isFinePartitionView = resolvedExplorerViewId.startsWith('fine_');
  const isLineagePartitionView = resolvedExplorerViewId !== 'global' && !isFinePartitionView;
  const isPartitionExplorerView = resolvedExplorerViewId !== 'global';

  /** Map partition ``cluster`` id → dominant ``globalCluster`` (Leiden) for cross-embedding alias resolution. */
  const partitionClusterToGlobalCluster = useMemo(() => {
    const m = new Map<string, string>();
    if (!isPartitionExplorerView) return m;
    const ids = new Set(
      filtered.metadata.map((r) => String(r.cluster ?? '').trim()).filter((id) => id.length > 0)
    );
    for (const pid of ids) {
      const cells = filtered.metadata.filter((r) => String(r.cluster ?? '').trim() === pid);
      const gc = dominantNonEmptyMetadataField(cells, 'globalCluster');
      if (gc) m.set(pid, gc);
    }
    return m;
  }, [filtered.metadata, isPartitionExplorerView]);

  const viewByOptions = useMemo(
    () => (data ? explorerViewByOptions(data.available_fields, resolvedExplorerViewId) : []),
    [data, resolvedExplorerViewId]
  );
  const primaryColorFields = useMemo(() => viewByOptions.map((o) => o.field), [viewByOptions]);

  const technicalColorFields = useMemo(
    () =>
      data ? technicalColorFieldsFromAvailable(data.available_fields, resolvedExplorerViewId) : [],
    [data, resolvedExplorerViewId]
  );

  const colorByHintLines = useMemo(
    () =>
      explorerColorByHintsForView(resolvedExplorerViewId, {
        isFinePartitionView,
      }),
    [resolvedExplorerViewId, isFinePartitionView]
  );

  useEffect(() => {
    if (!data) return;
    if (primaryColorFields.length === 0 && technicalColorFields.length > 0) {
      setTechnicalColorOpen(true);
    }
  }, [data, primaryColorFields.length, technicalColorFields.length]);

  useEffect(() => {
    if (!data) return;
    if (colorField && sortedViewerFields.includes(colorField)) return;
    setColorField(pickDefaultExplorerColorField(data.available_fields, resolvedExplorerViewId));
  }, [colorField, data, sortedViewerFields, resolvedExplorerViewId]);

  const embeddingContextViewLine = useMemo(() => {
    if (!data) return null;
    return embeddingContextDescription(resolvedExplorerViewId, data.embedding_key);
  }, [data, resolvedExplorerViewId]);

  const explorerFilterFieldKeys = useMemo(() => {
    if (!data) return [];
    return [...data.filter_fields, ...(data.advanced_filter_fields ?? [])];
  }, [data]);

  const splitFieldOptions = useMemo(() => {
    if (!data) return [];
    const raw = explorerFilterFieldKeys.filter((field) => {
      const nValues = data.filter_values[field]?.length ?? 0;
      return nValues >= 2 && nValues <= 8;
    });
    return sortExplorerFieldsForUi(raw);
  }, [data, explorerFilterFieldKeys]);

  const clusterAssignedLabelById = useMemo(() => {
    const m = new Map<string, string>();
    if (!data) return m;
    for (const c of data.cluster_summaries) {
      m.set(c.cluster_id, c.label);
    }
    return m;
  }, [data]);

  const clusterLabelWithAlias = useCallback(
    (clusterId: string, assignedLabel: string) =>
      clusterDisplayLabel(clusterId, assignedLabel, clusterAliases, {
        linkedGlobalClusterId: partitionClusterToGlobalCluster.get(String(clusterId)) ?? null,
      }),
    [clusterAliases, partitionClusterToGlobalCluster]
  );

  const clusterFilterLabels = useMemo(() => {
    if (!data) return new Map<string, string>();
    return new Map(
      data.cluster_summaries.map((cluster) => [
        cluster.cluster_id,
        formatClusterFilterValue(
          cluster.cluster_id,
          clusterLabelWithAlias(cluster.cluster_id, cluster.label),
          { lineagePartitionView: isPartitionExplorerView }
        ),
      ])
    );
  }, [data, clusterLabelWithAlias, isPartitionExplorerView]);

  const formatCategoryLegendLabel = useCallback(
    (field: string, rawValue: string) => {
      if (field === 'level3' && rawValue.startsWith(EXPLORER_LEVEL3_NO_FINE_PREFIX)) {
        const l2 = parseExplorerSyntheticNoFineLevel2(rawValue);
        return formatLevel3UnresolvedPrimary(l2);
      }
      if (field === 'cluster') {
        const assigned = clusterAssignedLabelById.get(rawValue) ?? rawValue;
        return clusterLabelWithAlias(rawValue, assigned);
      }
      return rawValue;
    },
    [clusterAssignedLabelById, clusterLabelWithAlias]
  );

  /**
   * On-plot centroid strings: same display names as the legend (``formatCategoryLegendLabel``).
   * Technical cluster mode applies browser display aliases; lineage / level2 / level3 stay canonical.
   * Technical id stays in the prefix when it differs from the display string (global: "Cluster N · …",
   * lineage/fine partitions: "PartitionId · …").
   */
  const formatCentroidLabel = useCallback(
    (field: string, rawValue: string) => {
      if (field === 'cluster') {
        const display = formatCategoryLegendLabel('cluster', rawValue);
        return formatClusterFilterValue(rawValue, display, {
          lineagePartitionView: isPartitionExplorerView,
        });
      }
      return formatCategoryLegendLabel(field, rawValue);
    },
    [formatCategoryLegendLabel, isPartitionExplorerView]
  );

  const formatMetadataDisplayValue = useCallback(
    (field: string, rawValue: string) => {
      if (field === 'level3' && rawValue.startsWith(EXPLORER_LEVEL3_NO_FINE_PREFIX)) {
        const l2 = parseExplorerSyntheticNoFineLevel2(rawValue);
        return formatLevel3UnresolvedDetail(l2);
      }
      if (field === 'cluster') {
        const assigned = clusterAssignedLabelById.get(rawValue) ?? rawValue;
        return clusterLabelWithAlias(rawValue, assigned);
      }
      return rawValue;
    },
    [clusterAssignedLabelById, clusterLabelWithAlias]
  );

  /** Biology-only inspector headline (aliases never replace canonical L1–L3 here). */
  const listLabelFor = useCallback(
    (c: ClusterInspectorSummary) => {
      const cid = String(c.cluster_id);
      const cells = filtered.metadata.filter((m) => String(m.cluster ?? '') === cid);
      return biologyClusterHeadlineFromCells(cells, c.label);
    },
    [filtered.metadata]
  );

  const focusLegendLabel = useMemo(() => {
    if (!focusPopulation) return null;
    return formatCategoryLegendLabel(focusPopulation.field, focusPopulation.rawValue);
  }, [focusPopulation, formatCategoryLegendLabel]);

  const annotationColorSelectValue = useMemo(() => {
    if (geneOverlay) return ANNOTATION_COLOR_PLACEHOLDER;
    if (primaryColorFields.includes(colorField)) return colorField;
    return ANNOTATION_COLOR_PLACEHOLDER;
  }, [geneOverlay, primaryColorFields, colorField]);

  const colorFieldIsViewByLayer = useMemo(() => {
    return primaryColorFields.includes(colorField);
  }, [primaryColorFields, colorField]);

  const technicalColorSelectValue = useMemo(() => {
    if (colorField.startsWith(GENE_FIELD_PREFIX)) return TECH_COLOR_SENTINEL_GENE;
    if (technicalColorFields.includes(colorField)) return colorField;
    return TECH_COLOR_SENTINEL_ANNOTATION;
  }, [colorField, technicalColorFields]);

  const colorFieldDisplayLabel = useMemo(() => {
    if (!colorField) return '—';
    if (geneOverlay && colorField.startsWith(GENE_FIELD_PREFIX)) {
      return 'Gene expression';
    }
    if (data) {
      return explorerViewByLabelForField(colorField, data.available_fields, resolvedExplorerViewId);
    }
    return formatExplorerFieldLabel(colorField);
  }, [colorField, geneOverlay, data, resolvedExplorerViewId]);

  useEffect(() => {
    setFocusPopulation((prev) => {
      if (!prev) return prev;
      if (prev.field !== colorField) return null;
      return prev;
    });
  }, [colorField]);

  const handleSelectCluster = useCallback(
    (id: string) => {
      setSelectedClusterId(id);
      if (colorField === 'cluster') {
        setFocusPopulation({ field: 'cluster', rawValue: id });
      }
    },
    [colorField]
  );

  const clearAllFilters = useCallback(() => {
    setActiveFilters({});
  }, []);

  const handleAliasSave = useCallback(
    (clusterId: string, alias: string) => {
      const t = alias.trim();
      const gid = partitionClusterToGlobalCluster.get(String(clusterId)) ?? null;

      if (explorerViewRequestId === 'global') {
        const base = loadGlobalAliases(runId);
        const nextG = { ...base };
        if (!t) delete nextG[clusterId];
        else nextG[clusterId] = t;
        saveGlobalAliases(runId, nextG);
      } else {
        const baseV = loadViewOverrideAliases(runId, explorerViewRequestId);
        const nextV = { ...baseV };
        if (!t) delete nextV[clusterId];
        else nextV[clusterId] = t;
        saveViewOverrideAliases(runId, explorerViewRequestId, nextV);
        if (gid) {
          const baseG = loadGlobalAliases(runId);
          const nextG = { ...baseG };
          if (!t) delete nextG[gid];
          else nextG[gid] = t;
          saveGlobalAliases(runId, nextG);
        }
      }
      setClusterAliases(loadClusterAliases(runId, explorerViewRequestId));
    },
    [runId, explorerViewRequestId, partitionClusterToGlobalCluster]
  );

  useEffect(() => {
    if (!splitField) return;
    if (splitFieldOptions.includes(splitField)) return;
    setSplitField('');
  }, [splitField, splitFieldOptions]);

  const splitView = useMemo(() => {
    if (filtered.embedding == null || splitField === '') {
      return {
        entries: [] as EmbeddingEntry[],
        omittedGroups: 0,
        totalGroups: 0,
      };
    }

    const groups = new Map<string, { cells: EmbeddingCell[]; metadata: CellMetadata[] }>();
    filtered.embedding.cells.forEach((cell, idx) => {
      const groupValue = embeddingDisplayMetadata[idx]?.[splitField];
      if (groupValue == null || String(groupValue).trim() === '') return;
      const key = String(groupValue);
      const group = groups.get(key) ?? { cells: [], metadata: [] };
      group.cells.push(cell);
      group.metadata.push(embeddingDisplayMetadata[idx]);
      groups.set(key, group);
    });

    const rankedGroups = Array.from(groups.entries()).sort(
      (left, right) => right[1].cells.length - left[1].cells.length
    );
    const entries = rankedGroups.slice(0, MAX_SPLIT_PANELS).map(([value, group]) => {
      const rawVal = String(value);
      const head =
        splitField === 'cluster' && data
          ? clusterLabelWithAlias(rawVal, clusterAssignedLabelById.get(rawVal) ?? rawVal)
          : rawVal;
      return {
        label: `${head} (${group.cells.length.toLocaleString()} cells)`,
        embedding: {
          cells: group.cells,
          bounds: filtered.embedding?.bounds ?? buildBounds(group.cells),
        },
        metadata: group.metadata,
        availableFields: sortedViewerFields,
        continuousFields: viewerContinuousFields,
        fieldRanges: viewerFieldRanges,
      };
    });

    return {
      entries,
      omittedGroups: Math.max(0, rankedGroups.length - entries.length),
      totalGroups: rankedGroups.length,
    };
  }, [
    filtered.embedding,
    splitField,
    embeddingDisplayMetadata,
    sortedViewerFields,
    viewerContinuousFields,
    viewerFieldRanges,
    data,
    clusterAssignedLabelById,
    clusterLabelWithAlias,
  ]);

  useEffect(() => {
    if (!filtered.clusterSummaries.some((cluster) => cluster.cluster_id === selectedClusterId)) {
      setSelectedClusterId(filtered.clusterSummaries[0]?.cluster_id ?? null);
    }
  }, [filtered.clusterSummaries, selectedClusterId]);

  const selectedCluster =
    filtered.clusterSummaries.find((cluster) => cluster.cluster_id === selectedClusterId) ??
    filtered.clusterSummaries[0] ??
    null;

  const selectedClusterContextLine = useMemo(() => {
    if (!selectedCluster) return null;
    return listLabelFor(selectedCluster);
  }, [selectedCluster, listLabelFor]);

  const inspectorFineUnresolvedNote = useMemo(() => {
    if (!selectedClusterId) return null;
    const cells = filtered.metadata.filter(
      (m) => String(m.cluster ?? '') === String(selectedClusterId)
    );
    if (cells.length === 0) return null;
    if (dominantNonEmptyMetadataField(cells, 'level3')) return null;
    if (!dominantNonEmptyMetadataField(cells, 'level2')) return null;
    return 'Structural fine subtype (auto_level3) is not resolved for this cluster. The headline shows major type (auto_level2) only.';
  }, [selectedClusterId, filtered.metadata]);

  function toggleFilter(field: string, value: string) {
    setActiveFilters((previous) => {
      const next = { ...previous };
      const values = new Set(next[field] ?? []);
      if (values.has(value)) {
        values.delete(value);
      } else {
        values.add(value);
      }
      next[field] = values;
      return next;
    });
  }

  function clearFilter(field: string) {
    setActiveFilters((previous) => ({
      ...previous,
      [field]: new Set<string>(),
    }));
  }

  if (loading) {
    return (
      <div className="card p-8">
        <div className="flex min-h-72 items-center justify-center text-sm text-gray-500">
          Loading completed run explorer…
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="card p-8">
        <p className="text-sm text-red-600">{error ?? 'Explorer data is unavailable.'}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="run-explorer">
      {data.lineage_embedding_fallback ? (
        <div
          className="rounded-lg border border-amber-200 bg-amber-50/90 px-4 py-2 text-sm text-amber-950"
          data-testid="explorer-lineage-embedding-fallback"
        >
          Lineage-specific UMAP is missing or has no valid coordinates for this compartment. Showing
          the same global embedding coordinates for cells in this lineage (positions match the
          Global view).
        </div>
      ) : null}
      {data.lineage_view_unavailable_reason ? (
        <div
          className="rounded-lg border border-amber-200 bg-amber-50/90 px-4 py-2 text-sm text-amber-950"
          data-testid="explorer-lineage-view-unavailable"
        >
          {data.lineage_view_unavailable_reason}
        </div>
      ) : null}
      <div
        className="grid gap-4 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-6"
        data-testid="explorer-summary-stats"
      >
        <StatCard
          label="Cells"
          value={cohortFiltersActive ? filtered.shownCells : data.overview.n_cells}
          subtitle={
            cohortFiltersActive
              ? `${data.overview.n_cells.toLocaleString()} before filters`
              : data.overview.artifact_total_cells != null &&
                  data.overview.artifact_total_cells !== data.overview.n_cells
                ? `${data.overview.artifact_total_cells.toLocaleString()} in full artifact`
                : undefined
          }
        />
        <StatCard label="Genes" value={data.overview.n_genes} />
        <StatCard
          label="Clusters"
          value={
            cohortFiltersActive && filteredTopSummary
              ? filteredTopSummary.nClusters
              : (data.overview.n_clusters ?? '—')
          }
          subtitle={
            cohortFiltersActive && data.overview.n_clusters != null
              ? `${data.overview.n_clusters.toLocaleString()} before filters`
              : undefined
          }
        />
        <StatCard
          label="Samples"
          value={
            cohortFiltersActive && filteredTopSummary
              ? (filteredTopSummary.nSamples ?? '—')
              : (data.overview.n_samples ?? '—')
          }
          subtitle={
            cohortFiltersActive && data.overview.n_samples != null
              ? `${data.overview.n_samples.toLocaleString()} before filters`
              : undefined
          }
        />
        <StatCard
          label="Conditions"
          value={
            cohortFiltersActive && filteredTopSummary
              ? (filteredTopSummary.nConditions ?? '—')
              : (data.overview.n_conditions ?? '—')
          }
          subtitle={
            cohortFiltersActive && data.overview.n_conditions != null
              ? `${data.overview.n_conditions.toLocaleString()} before filters`
              : undefined
          }
        />
        <StatCard
          label="Embedding"
          value={data.embedding_key.replace('X_', '').toUpperCase()}
          subtitle={
            cohortFiltersActive
              ? data.sampled
                ? `${filtered.shownCells.toLocaleString()} filtered · sampled ${data.total_cells.toLocaleString()} in run`
                : `${filtered.shownCells.toLocaleString()} in filtered cohort · ${data.overview.n_cells.toLocaleString()} before filters`
              : data.sampled
                ? `Showing ${filtered.shownCells.toLocaleString()} of ${data.total_cells.toLocaleString()} cells`
                : `${filtered.shownCells.toLocaleString()} cells in view`
          }
        />
      </div>

      <RunCompositionOverview
        metadata={filtered.metadata}
        availableFields={data.available_fields}
        nSamples={compositionOverviewCounts.nSamples}
        nConditions={compositionOverviewCounts.nConditions}
        onCompositionCategoryFocus={({ field, category }) => {
          setColorField(field);
          setFocusPopulation({ field, rawValue: category });
        }}
      />

      <ExploreCellsWorkspace
        totalCellsInRun={data.total_cells}
        sampled={data.sampled}
        visibleCells={filtered.shownCells}
        filterFields={data.filter_fields}
        advancedFilterFields={data.advanced_filter_fields ?? []}
        cohortFilterFields={explorerFilterFieldKeys}
        filterValues={filterPanelValues}
        hierarchyFilterAxes={data.hierarchy_filter_axes}
        hierarchyAxesPopulated={hierarchyAxesArePopulated(data.hierarchy_filter_axes)}
        activeFilters={activeFilters}
        clusterFilterLabels={clusterFilterLabels}
        onToggleFilter={toggleFilter}
        onClearFilter={clearFilter}
        onClearAllFilters={clearAllFilters}
        focusLabel={focusLegendLabel}
        onClearFocus={() => setFocusPopulation(null)}
        geneOverlayGene={geneOverlay?.gene ?? null}
        onClearGeneOverlay={clearGeneOverlay}
        embeddingContext={
          <EmbeddingContextStrip
            colorFieldLabel={colorFieldDisplayLabel}
            geneOverlayGene={geneOverlay?.gene ?? null}
            focusLabel={focusLegendLabel}
            selectedClusterLine={selectedClusterContextLine}
            viewContextLine={embeddingContextViewLine}
            clusterInspectorLabel={
              isFinePartitionView
                ? 'Fine partition'
                : isLineagePartitionView
                  ? 'Partition'
                  : undefined
            }
          />
        }
        toolbar={
          <div className="flex flex-col gap-3 xl:flex-row xl:flex-wrap xl:items-end">
            <label className="flex min-w-[12rem] flex-1 flex-col gap-1 xl:max-w-[18rem]">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                Embedding coordinates
              </span>
              <select
                data-testid="explorer-embedding-view-select"
                disabled={Boolean(geneOverlay) || allowedEmbeddingOptions.length === 0}
                value={embeddingSelectValue}
                onChange={(e) => setExplorerViewRequestId(e.target.value)}
                className="w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700 disabled:cursor-not-allowed disabled:opacity-60"
                aria-busy={embeddingRefetchBusy}
              >
                {allowedEmbeddingOptions.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {userFacingEmbeddingCoordinateLabel(opt.id)}
                  </option>
                ))}
              </select>
              <span className="text-[10px] leading-snug text-gray-500">
                Global stays the default. Lineage- or branch-local options appear when you select
                exactly one lineage (and one major type for fine views) and the run has those
                embeddings.
                {embeddingRefetchBusy ? ' Loading…' : ''}
              </span>
            </label>
            <label className="flex min-w-[10rem] flex-1 flex-col gap-1 xl:max-w-[14rem]">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                Split view
              </span>
              <select
                value={splitField}
                onChange={(e) => setSplitField(e.target.value)}
                className="w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700"
              >
                <option value="">Single panel</option>
                {splitFieldOptions.map((field) => (
                  <option key={field} value={field}>
                    {formatExplorerFieldLabel(field)}
                  </option>
                ))}
              </select>
            </label>
            <form onSubmit={handleGeneSubmit} className="flex min-w-0 flex-[2] flex-col gap-1">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                Gene expression overlay
              </span>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={geneInput}
                  onChange={(e) => setGeneInput(e.target.value)}
                  placeholder="Gene symbol, e.g. EPCAM"
                  className="min-w-0 flex-1 rounded-md border border-gray-300 px-2 py-1.5 text-sm text-gray-700"
                />
                <button
                  type="submit"
                  disabled={geneLoading || geneInput.trim().length === 0}
                  className="rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {geneLoading ? '…' : 'Plot gene'}
                </button>
                {geneOverlay ? (
                  <>
                    <button
                      type="button"
                      onClick={clearGeneOverlay}
                      className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                    >
                      Clear overlay
                    </button>
                    <button
                      type="button"
                      onClick={clearGeneOverlay}
                      className="rounded-md border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-sm font-medium text-indigo-800 hover:bg-indigo-100"
                    >
                      Back to categories
                    </button>
                  </>
                ) : null}
              </div>
              {geneError ? <p className="text-xs text-red-600">{geneError}</p> : null}
            </form>
            <div className="flex min-w-[12rem] max-w-[22rem] flex-col gap-2">
              <label className="flex flex-col gap-1">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                  View by · lineage, major and fine
                </span>
                <select
                  data-testid="explorer-color-by-annotation"
                  disabled={Boolean(geneOverlay) || primaryColorFields.length === 0}
                  value={
                    primaryColorFields.length === 0
                      ? ANNOTATION_COLOR_PLACEHOLDER
                      : annotationColorSelectValue
                  }
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v === ANNOTATION_COLOR_PLACEHOLDER) return;
                    setColorField(v);
                  }}
                  className="rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <option value={ANNOTATION_COLOR_PLACEHOLDER} disabled>
                    {geneOverlay
                      ? 'Gene overlay active — clear to choose a view'
                      : primaryColorFields.length === 0
                        ? 'No auto hierarchy on this artifact'
                        : 'Select view…'}
                  </option>
                  {viewByOptions.map((o) => (
                    <option key={o.field} value={o.field}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <div className="space-y-0.5 text-[10px] leading-snug text-gray-500">
                  {colorByHintLines.map((line) => (
                    <p key={line}>{line}</p>
                  ))}
                </div>
              </label>
              <details
                className="rounded-md border border-gray-200 bg-gray-50/80 px-2 py-1.5"
                open={technicalColorOpen}
                onToggle={(e) => setTechnicalColorOpen(e.currentTarget.open)}
              >
                <summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-wide text-gray-600">
                  Advanced & technical color options
                </summary>
                <label className="mt-2 flex flex-col gap-1">
                  <span className="text-[10px] text-gray-500">
                    Tissue, lineage (when not in View by), fine partition, technical cluster, cell
                    type (debug)
                  </span>
                  <select
                    data-testid="explorer-color-by-technical"
                    disabled={
                      Boolean(geneOverlay) ||
                      technicalColorFields.length === 0 ||
                      colorField.startsWith(GENE_FIELD_PREFIX)
                    }
                    value={technicalColorSelectValue}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === TECH_COLOR_SENTINEL_ANNOTATION || v === TECH_COLOR_SENTINEL_GENE) {
                        return;
                      }
                      setColorField(v);
                    }}
                    className="rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <option value={TECH_COLOR_SENTINEL_ANNOTATION}>
                      {colorFieldIsViewByLayer ? 'Using View by above' : 'Pick a technical field…'}
                    </option>
                    {colorField.startsWith(GENE_FIELD_PREFIX) ? (
                      <option value={TECH_COLOR_SENTINEL_GENE}>
                        Gene expression overlay active
                      </option>
                    ) : null}
                    {technicalColorFields.map((f) => (
                      <option key={f} value={f}>
                        {formatExplorerFieldLabel(f)}
                      </option>
                    ))}
                  </select>
                </label>
              </details>
            </div>
            <label className="flex min-w-[8rem] flex-col gap-1">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                Label mode
              </span>
              <select
                value={labelMode}
                onChange={(e) => setLabelMode(e.target.value as 'none' | 'cluster' | 'cellType')}
                className="rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700"
              >
                <option value="none">Off</option>
                <option value="cluster">Cluster centroids</option>
                <option value="cellType">Match View by (centroids)</option>
              </select>
            </label>
          </div>
        }
      >
        {filtered.embedding == null ? (
          <div className="flex min-h-72 items-center justify-center rounded border border-dashed border-gray-200 text-sm text-gray-400">
            No cells match the active filters.
          </div>
        ) : splitField !== '' && splitView.entries.length > 1 ? (
          <div className="space-y-3" data-testid="split-view">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500">
              <span>
                Split across {splitView.totalGroups} visible groups (largest panels first).
              </span>
              {splitView.omittedGroups > 0 && (
                <span>
                  Showing {MAX_SPLIT_PANELS} panels; {splitView.omittedGroups} smaller groups
                  omitted.
                </span>
              )}
            </div>
            <EmbeddingComparison
              entries={splitView.entries}
              activeColorField={colorField}
              onActiveColorFieldChange={setColorField}
              formatCategoryLegendLabel={formatCategoryLegendLabel}
              formatCentroidLabel={formatCentroidLabel}
              formatMetadataDisplayValue={formatMetadataDisplayValue}
              labelMode={labelMode}
              onLabelModeChange={setLabelMode}
              focusCategory={focusPopulation}
              legendHoverRaw={legendHoverRaw}
              hideInternalLegend
              compactToolbar
            />
            <EmbeddingBottomLegend
              metadata={embeddingDisplayMetadata}
              colorField={colorField}
              isCategorical={!viewerContinuousFields.includes(colorField)}
              continuousMin={geneOverlay?.min ?? 0}
              continuousMax={geneOverlay?.max ?? 1}
              geneName={geneOverlay?.gene ?? null}
              formatCategoryLegendLabel={formatCategoryLegendLabel}
              focusRawValue={
                focusPopulation && focusPopulation.field === colorField
                  ? focusPopulation.rawValue
                  : null
              }
              hoverRawValue={legendHoverRaw}
              onFocusRawValue={(raw) => {
                if (raw == null) {
                  setFocusPopulation(null);
                  return;
                }
                setFocusPopulation({ field: colorField, rawValue: raw });
              }}
              onHoverRawValue={setLegendHoverRaw}
            />
          </div>
        ) : (
          <>
            <LazyEmbeddingViewer
              eager
              embedding={filtered.embedding}
              metadata={embeddingDisplayMetadata}
              availableFields={sortedViewerFields}
              continuousFields={viewerContinuousFields}
              fieldRanges={viewerFieldRanges}
              activeColorField={colorField}
              onActiveColorFieldChange={setColorField}
              formatCategoryLegendLabel={formatCategoryLegendLabel}
              formatCentroidLabel={formatCentroidLabel}
              formatMetadataDisplayValue={formatMetadataDisplayValue}
              labelMode={labelMode}
              onLabelModeChange={setLabelMode}
              focusCategory={focusPopulation}
              legendHoverRaw={legendHoverRaw}
              hideInternalLegend
              compactToolbar
            />
            <EmbeddingBottomLegend
              metadata={embeddingDisplayMetadata}
              colorField={colorField}
              isCategorical={!viewerContinuousFields.includes(colorField)}
              continuousMin={geneOverlay?.min ?? 0}
              continuousMax={geneOverlay?.max ?? 1}
              geneName={geneOverlay?.gene ?? null}
              formatCategoryLegendLabel={formatCategoryLegendLabel}
              focusRawValue={
                focusPopulation && focusPopulation.field === colorField
                  ? focusPopulation.rawValue
                  : null
              }
              hoverRawValue={legendHoverRaw}
              onFocusRawValue={(raw) => {
                if (raw == null) {
                  setFocusPopulation(null);
                  return;
                }
                setFocusPopulation({ field: colorField, rawValue: raw });
              }}
              onHoverRawValue={setLegendHoverRaw}
            />
          </>
        )}
      </ExploreCellsWorkspace>

      <ClusterInspector
        clusterSummaries={filtered.clusterSummaries}
        selectedClusterId={selectedClusterId}
        onSelectCluster={handleSelectCluster}
        selectedCluster={selectedCluster}
        geneOverlayGene={geneOverlay?.gene ?? null}
        onMarkerClick={(gene) => void loadGeneOverlay(gene)}
        listLabelFor={listLabelFor}
        aliasForSelected={
          selectedCluster ? (clusterAliases[selectedCluster.cluster_id]?.trim() ?? '') : ''
        }
        onAliasSave={handleAliasSave}
        userClusterAliases={clusterAliases}
        biologyFineUnresolvedNote={inspectorFineUnresolvedNote}
        inspectorMode={isPartitionExplorerView ? 'lineage' : 'global'}
        partitionSubtype={
          isPartitionExplorerView ? (isFinePartitionView ? 'fine' : 'lineage') : undefined
        }
      />
    </div>
  );
}
