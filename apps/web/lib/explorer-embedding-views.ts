/**
 * Hierarchy-aware embedding options for the run explorer.
 * Mirrors server-side EXPLORER_LINEAGE_VIEWS / EXPLORER_FINE_VIEWS (see run_explorer_service.py).
 */

export interface ExplorerEmbeddingViewOption {
  id: string;
  label: string;
  lineage_label: string | null;
  obsm_key: string | null;
  n_cells: number;
  embedding_ready: boolean;
}

/** Canonical auto_level2 (and common legacy spellings) → fine explorer_view id. */
const FINE_LEVEL2_TO_VIEW_ID: Record<string, string> = {
  'T cells': 'fine_t_cells',
  'T cell': 'fine_t_cells',
  'B cells': 'fine_b_cells',
  'B cell': 'fine_b_cells',
  Myeloid: 'fine_myeloid',
  Fibroblasts: 'fine_fibroblasts',
  'Smooth muscle': 'fine_smooth_muscle',
};

function isLineageCatalogEntry(v: ExplorerEmbeddingViewOption): boolean {
  return (
    v.id !== 'global' &&
    !v.id.startsWith('fine_') &&
    v.lineage_label != null &&
    v.lineage_label !== ''
  );
}

/**
 * Embedding modes the user may pick explicitly, given current cohort filter chips.
 * Policy: global always (when ready); lineage-local only for exactly one lineage selection;
 * branch-local only for exactly one lineage and one level2 selection, and only for majors
 * that have a persisted fine UMAP in the catalog.
 */
export function allowedHierarchyEmbeddingViews(
  availableViews: ExplorerEmbeddingViewOption[] | undefined,
  activeFilters: Record<string, Set<string>>
): ExplorerEmbeddingViewOption[] {
  if (!availableViews?.length) return [];
  const out: ExplorerEmbeddingViewOption[] = [];
  const global = availableViews.find((v) => v.id === 'global');
  if (global?.embedding_ready) {
    out.push(global);
  }

  const lineageSel = activeFilters.lineage;
  if (lineageSel && lineageSel.size === 1) {
    const l1 = [...lineageSel][0];
    const lineageView = availableViews.find(
      (v) => isLineageCatalogEntry(v) && v.lineage_label === l1 && v.embedding_ready
    );
    if (lineageView) {
      out.push(lineageView);
    }
  }

  const level2Sel = activeFilters.level2;
  if (lineageSel && lineageSel.size === 1 && level2Sel && level2Sel.size === 1) {
    const l2 = [...level2Sel][0].trim();
    const fineId = FINE_LEVEL2_TO_VIEW_ID[l2];
    if (fineId) {
      const fine = availableViews.find((v) => v.id === fineId && v.embedding_ready);
      if (fine) {
        out.push(fine);
      }
    }
  }

  return out;
}

/** Short labels for the embedding coordinate selector (explicit user choice). */
export function userFacingEmbeddingCoordinateLabel(viewId: string): string {
  switch (viewId) {
    case 'global':
      return 'Global embedding';
    case 'immune':
      return 'Immune embedding';
    case 'stromal':
      return 'Stromal embedding';
    case 'epithelial':
      return 'Epithelial embedding';
    case 'endothelial':
      return 'Endothelial embedding';
    case 'fine_t_cells':
      return 'T cells embedding';
    case 'fine_b_cells':
      return 'B cells embedding';
    case 'fine_myeloid':
      return 'Myeloid embedding';
    case 'fine_fibroblasts':
      return 'Fibroblasts embedding';
    case 'fine_smooth_muscle':
      return 'Smooth muscle embedding';
    default:
      return viewId;
  }
}

export function embeddingContextDescription(viewId: string, embeddingKey: string): string {
  const key = embeddingKey.replace(/^X_/, '').toUpperCase();
  if (viewId === 'global') {
    return `Global UMAP · ${key} · View by: lineage, major type, and fine subtype (auto_level1–3). Display label, clusters, and partitions are under Advanced.`;
  }
  if (viewId.startsWith('fine_')) {
    return `Fine-branch embedding · ${key} · Local coordinates for the selected major type; cluster summaries follow P3 fine partitions.`;
  }
  if (viewId !== 'global') {
    return `Lineage-local embedding · ${key} · Local coordinates for the selected broad lineage; cluster summaries follow P2 lineage partitions.`;
  }
  return `Embedding · ${key}`;
}
