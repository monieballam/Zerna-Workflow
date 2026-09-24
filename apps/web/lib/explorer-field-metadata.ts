/**
 * Explorer / embedding field ordering and labels.
 * Keep aligned with `FIELD_DEFINITIONS` in `apps/api/services/run_explorer_service.py`.
 */

/** Primary annotation hierarchy + common facets (API response keys / metadata keys). */
export const EXPLORER_FIELD_DISPLAY_ORDER: readonly string[] = [
  'lineage',
  'level2',
  'level3',
  'cluster',
  'globalCluster',
  'cellType',
  'tissue',
  'confidenceBucket',
  'confidence',
  'sample',
  'condition',
  'batch',
  'patient',
  'displayLabel',
  'rawAnnotationLabel',
  'lineageSubcluster',
  'fineSubcluster',
];

const DISPLAY_LABELS: Record<string, string> = {
  cluster: 'Cluster (technical)',
  globalCluster: 'Global cluster (Leiden)',
  lineageSubcluster: 'Lineage partition ID (P2)',
  fineSubcluster: 'Fine partition ID (P3)',
  cellType: 'Cell type (merged column — final_display first, not raw Zerna)',
  lineage: 'Lineage',
  level2: 'Major cell type',
  level3: 'Fine type / subtype',
  displayLabel: 'Display label (conservative UI — may hide fine subtype)',
  tissue: 'Tissue',
  confidenceBucket: 'Confidence bucket',
  confidence: 'Confidence',
  sample: 'Sample',
  condition: 'Condition',
  batch: 'Batch',
  patient: 'Patient',
  rawAnnotationLabel: 'Raw Zerna label',
};

/**
 * Short helper copy for Explorer filter panels (primary + advanced).
 * Keys match API metadata / filter field names.
 */
export const EXPLORER_FILTER_FIELD_HELP: Record<string, string> = {
  cellType:
    'Merged column: prefers final_display, then celltype/zr/CellTypist — annotation_label is last resort only. For biology, use lineage / level2 / level3; use rawAnnotationLabel for the explicit legacy engine string.',
  lineage:
    'Pipeline auto_level1 — broad compartment. Pick exactly one lineage to unlock optional lineage-local coordinates in the Embedding toolbar (Global stays default until you switch). Major/fine coloring remains under View by.',
  level2:
    'Pipeline auto_level2 — major group. On canonical runs with hierarchy axes, cohort filter choices list only majors that co-occur with your selected lineage(s), matching the explorer branch model. Pick exactly one lineage and one major to unlock fine-branch embedding coordinates.',
  level3:
    'Structural fine subtype (normalized auto_level3 / level3_final_safe on canonical runs). Cohort filter choices are branch-scoped: pick lineage and major type first; rawAnnotationLabel is never used as a Level 3 filter source. On legacy artifacts without full auto columns, fine subtype is color-by only.',
  displayLabel:
    'Readable summary string (final_display): conservative; may omit fine subtype. Use for labels and diagnostics, not as the main hierarchy axis (use lineage / level2 / level3).',
  rawAnnotationLabel:
    'Raw annotation_label string from the pipeline (legacy / engine). Use lineage / level2 / level3 for biology; this is for debugging and cohort coloring only.',
  cluster:
    'Technical cluster ID for the current embedding view (e.g. global Leiden, or partition IDs in subset views). Use Advanced color options.',
  globalCluster:
    'Global Leiden / cluster ID from the full-dataset embedding (unchanged in lineage views).',
  lineageSubcluster: 'P2 lineage partition ID (e.g. Immune:0) — Advanced / debug.',
  fineSubcluster:
    'P3 fine partition ID from obs fine_subcluster (e.g. T_cells:0). For biology, prefer Fine type / subtype (auto_level3); use this for partition debugging.',
  sample: 'Sample or specimen identifier from the dataset.',
  condition: 'Experimental condition, group, or disease state.',
};

/** Keys treated as legacy / advanced in filter UI copy (not primary annotation trio + display label). */
export const EXPLORER_LEGACY_FIELD_KEYS = new Set<string>(['rawAnnotationLabel']);

/**
 * Any field that can be primary “View by” in at least one embedding mode (for docs / metadata).
 * Actual View by options are mode-specific — see {@link explorerViewByOptions}.
 */
export const EXPLORER_PRIMARY_COLOR_BY_FIELDS: readonly string[] = ['lineage', 'level2', 'level3'];

/** Global explorer: broad + major + fine subtype in the primary View by control. */
const VIEW_BY_GLOBAL_LAYER_ORDER: readonly { field: string; label: string }[] = [
  { field: 'lineage', label: 'Broad (lineage · auto_level1)' },
  { field: 'level2', label: 'Major cell type (auto_level2)' },
  { field: 'level3', label: 'Fine subtype (auto_level3)' },
];

/** Lineage / fine-branch embeddings: major + fine (subtype biology belongs in compartment views). */
const VIEW_BY_COMPARTMENT_LAYER_ORDER: readonly { field: string; label: string }[] = [
  { field: 'level2', label: 'Major cell type (auto_level2)' },
  { field: 'level3', label: 'Fine subtype (auto_level3)' },
];

/** Global vs lineage / fine-compartment embedding mode. */
export function explorerViewColorMode(explorerViewId: string): 'global' | 'compartment' {
  const v = (explorerViewId || 'global').trim().toLowerCase();
  return v === 'global' ? 'global' : 'compartment';
}

/**
 * Primary “View by” color options for the current embedding mode.
 * - **Global:** lineage + level2 + level3.
 * - **Lineage / fine views (API-only):** level2 + level3.
 */
export function explorerViewByOptions(
  available: string[],
  explorerViewId: string = 'global'
): { field: string; label: string }[] {
  const set = new Set(available);
  const order =
    explorerViewColorMode(explorerViewId) === 'global'
      ? VIEW_BY_GLOBAL_LAYER_ORDER
      : VIEW_BY_COMPARTMENT_LAYER_ORDER;
  return order.filter((o) => set.has(o.field));
}

/**
 * Advanced color-by only: tissue, broad lineage (when not primary View by), P3 partition,
 * technical cluster for the current embedding, merged cell-type debug column.
 * No display label, global cluster, P2 partition, confidence, cohort facets, or raw Zerna here.
 */
export const EXPLORER_TECHNICAL_COLOR_BY_FIELDS: readonly string[] = [
  'tissue',
  'lineage',
  'fineSubcluster',
  'cluster',
  'cellType',
];

/** Fields offered in the unified View by control (broad / major / fine), in display order. */
export function primaryColorFieldsFromAvailable(
  available: string[],
  explorerViewId: string = 'global'
): string[] {
  return explorerViewByOptions(available, explorerViewId).map((o) => o.field);
}

/**
 * Advanced / technical color fields. Excludes the **current** View by primary fields
 * (e.g. ``lineage`` appears here in compartment mode only).
 */
export function technicalColorFieldsFromAvailable(
  available: string[],
  explorerViewId: string = 'global'
): string[] {
  const set = new Set(available);
  const skip = new Set(primaryColorFieldsFromAvailable(available, explorerViewId));

  return EXPLORER_TECHNICAL_COLOR_BY_FIELDS.filter((f) => set.has(f) && !skip.has(f));
}

/**
 * Default view-by field: global → broad (lineage) when present; compartment → major (level2) when present.
 */
export function pickDefaultExplorerColorField(
  available: string[],
  explorerViewId: string = 'global'
): string {
  const opts = explorerViewByOptions(available, explorerViewId);
  if (opts.length === 0) {
    const tech = technicalColorFieldsFromAvailable(available, explorerViewId);
    if (tech.length > 0) return tech[0];
    return available[0] ?? '';
  }
  const mode = explorerViewColorMode(explorerViewId);
  if (mode === 'global') {
    const broad = opts.find((o) => o.field === 'lineage');
    if (broad) return broad.field;
    return opts[0].field;
  }
  const major = opts.find((o) => o.field === 'level2');
  if (major) return major.field;
  return opts[0].field;
}

/** Short helper lines under View by (single block; no duplicate optional fine section). */
export function explorerColorByHintsForView(
  explorerViewId: string,
  opts: { isFinePartitionView: boolean }
): readonly string[] {
  const mode = explorerViewColorMode(explorerViewId);
  if (mode === 'global') {
    return [
      'Use View by for lineage (auto_level1), major type (auto_level2), and fine subtype (auto_level3). Cross-lineage fine labels can be heterogeneous — interpret next to the composition chart above.',
      'Tissue, technical cluster, fine partition (P3), and merged cell type (debug) are under Advanced & technical.',
    ];
  }
  if (opts.isFinePartitionView) {
    return [
      'Major and Fine match auto_level2 and auto_level3 on this fine-branch embedding — use them for subtype biology here.',
      'Broad lineage (auto_level1), tissue, technical cluster, fine partition (P3), and merged cell type (debug) are under Advanced when present.',
    ];
  }
  return [
    'Major and Fine match auto_level2 and auto_level3 within this lineage compartment.',
    'Broad lineage, tissue, technical cluster, fine partition (P3), and merged cell type (debug) are under Advanced when present.',
  ];
}

/** @deprecated Prefer explorerColorByHintsForView(explorerViewId, opts). */
export const EXPLORER_COLOR_BY_HINT_LINES: readonly string[] = explorerColorByHintsForView(
  'global',
  { isFinePartitionView: false }
);

/** @deprecated No secondary annotation strip; fine subtype is primary View by on global. */
export function globalSecondaryAnnotationColorFields(): string[] {
  return [];
}

export function formatExplorerFieldLabel(field: string): string {
  if (DISPLAY_LABELS[field]) return DISPLAY_LABELS[field];
  if (field.startsWith('geneExpression:')) {
    return `Gene: ${field.slice('geneExpression:'.length)}`;
  }
  return field
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/_/g, ' ')
    .replace(/^./, (c) => c.toUpperCase());
}

/** Context strip / legend: friendly View by label, or {@link formatExplorerFieldLabel} as fallback. */
export function explorerViewByLabelForField(
  field: string,
  available: string[],
  explorerViewId: string
): string {
  const o = explorerViewByOptions(available, explorerViewId).find((x) => x.field === field);
  return o?.label ?? formatExplorerFieldLabel(field);
}

/**
 * Order fields for color-by and similar dropdowns: canonical hierarchy first, then the rest A–Z.
 */
export function sortExplorerFieldsForUi(fields: string[]): string[] {
  const set = new Set(fields);
  const primary = EXPLORER_FIELD_DISPLAY_ORDER.filter((f) => set.has(f));
  const rest = fields
    .filter((f) => !EXPLORER_FIELD_DISPLAY_ORDER.includes(f))
    .sort((a, b) => a.localeCompare(b));
  return [...primary, ...rest];
}

/** Metadata keys to show first in cell selection sidebar (canonical hierarchy before display-only). */
export const EXPLORER_METADATA_KEY_ORDER: readonly string[] = [
  'lineage',
  'level2',
  'level3',
  'displayLabel',
  'cellType',
  'cluster',
  'rawAnnotationLabel',
];

export function sortExplorerMetadataEntries(entries: [string, unknown][]): [string, unknown][] {
  const order = new Map(EXPLORER_METADATA_KEY_ORDER.map((k, i) => [k, i]));
  return [...entries].sort((a, b) => {
    const ia = order.get(a[0]) ?? 1000;
    const ib = order.get(b[0]) ?? 1000;
    if (ia !== ib) return ia - ib;
    return a[0].localeCompare(b[0]);
  });
}

/** Mirrors ``hierarchy_filter_axes`` from the run explorer API (built from full artifact obs). */
export interface ExplorerHierarchyFilterAxes {
  level2_by_lineage: Record<string, string[]>;
  level3_by_lineage_major: Record<string, string[]>;
}

export function hierarchyAxesArePopulated(axes: ExplorerHierarchyFilterAxes | undefined): boolean {
  return Boolean(axes && Object.keys(axes.level2_by_lineage ?? {}).length > 0);
}

/**
 * When the API supplies hierarchy axes, level-2 filter choices are restricted to major groups that
 * co-occur with the selected broad lineage(s). If nothing is selected at L1, return no L2 options.
 */
export function hierarchyScopedLevel2Values(
  axes: ExplorerHierarchyFilterAxes | undefined,
  allValues: string[] | undefined,
  selectedLineages: Set<string>
): string[] {
  const all = allValues ?? [];
  if (!hierarchyAxesArePopulated(axes)) {
    return all;
  }
  if (selectedLineages.size === 0) {
    return [];
  }
  const allowed = new Set<string>();
  for (const l1 of selectedLineages) {
    const row = axes!.level2_by_lineage[l1];
    if (row) {
      for (const v of row) {
        allowed.add(v);
      }
    }
  }
  return all.filter((v) => allowed.has(v));
}

/**
 * Level-3 filter choices for the union of (L1, L2) pairs implied by the current L1 and L2
 * selections. Empty until both layers have at least one active value.
 */
export function hierarchyScopedLevel3Values(
  axes: ExplorerHierarchyFilterAxes | undefined,
  allValues: string[] | undefined,
  selectedLineages: Set<string>,
  selectedLevel2: Set<string>
): string[] {
  const all = allValues ?? [];
  if (!hierarchyAxesArePopulated(axes)) {
    return all;
  }
  if (selectedLineages.size === 0 || selectedLevel2.size === 0) {
    return [];
  }
  const allowed = new Set<string>();
  for (const l1 of selectedLineages) {
    for (const l2 of selectedLevel2) {
      const key = `${l1}|${l2}`;
      const row = axes!.level3_by_lineage_major[key];
      if (row) {
        for (const v of row) {
          allowed.add(v);
        }
      }
    }
  }
  return all.filter((v) => allowed.has(v));
}
