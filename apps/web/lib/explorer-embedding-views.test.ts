import { describe, expect, it } from 'vitest';
import {
  allowedHierarchyEmbeddingViews,
  userFacingEmbeddingCoordinateLabel,
} from '@/lib/explorer-embedding-views';

const catalog = [
  {
    id: 'global',
    label: 'Global',
    lineage_label: null,
    obsm_key: null,
    n_cells: 100,
    embedding_ready: true,
  },
  {
    id: 'immune',
    label: 'Immune',
    lineage_label: 'Immune',
    obsm_key: 'X_umap_lineage_immune',
    n_cells: 40,
    embedding_ready: true,
  },
  {
    id: 'stromal',
    label: 'Stromal',
    lineage_label: 'Stromal',
    obsm_key: 'X_umap_lineage_stromal',
    n_cells: 10,
    embedding_ready: false,
  },
  {
    id: 'fine_myeloid',
    label: 'Myeloid (fine)',
    lineage_label: 'Myeloid',
    obsm_key: 'X_umap_fine_myeloid',
    n_cells: 20,
    embedding_ready: true,
  },
];

function filters(lineage: string[] | null, level2: string[] | null) {
  const out: Record<string, Set<string>> = {};
  if (lineage?.length) out.lineage = new Set(lineage);
  if (level2?.length) out.level2 = new Set(level2);
  return out;
}

describe('allowedHierarchyEmbeddingViews', () => {
  it('returns only global when no lineage selection', () => {
    const r = allowedHierarchyEmbeddingViews(catalog, {});
    expect(r.map((x) => x.id)).toEqual(['global']);
  });

  it('adds lineage-local view when exactly one lineage matches a ready catalog entry', () => {
    const r = allowedHierarchyEmbeddingViews(catalog, filters(['Immune'], null));
    expect(r.map((x) => x.id)).toEqual(['global', 'immune']);
  });

  it('does not add lineage-local when embedding is not ready', () => {
    const r = allowedHierarchyEmbeddingViews(catalog, filters(['Stromal'], null));
    expect(r.map((x) => x.id)).toEqual(['global']);
  });

  it('does not add lineage-local for multiple lineages', () => {
    const r = allowedHierarchyEmbeddingViews(catalog, filters(['Immune', 'Stromal'], null));
    expect(r.map((x) => x.id)).toEqual(['global']);
  });

  it('adds fine view when one lineage and one supported level2 are selected', () => {
    const r = allowedHierarchyEmbeddingViews(catalog, filters(['Immune'], ['Myeloid']));
    expect(r.map((x) => x.id)).toEqual(['global', 'immune', 'fine_myeloid']);
  });

  it('does not add fine view without lineage selection', () => {
    const r = allowedHierarchyEmbeddingViews(catalog, filters(null, ['Myeloid']));
    expect(r.map((x) => x.id)).toEqual(['global']);
  });

  it('does not add fine view for multiple level2 selections', () => {
    const r = allowedHierarchyEmbeddingViews(catalog, filters(['Immune'], ['Myeloid', 'T cells']));
    expect(r.map((x) => x.id)).toEqual(['global', 'immune']);
  });
});

const catalogWithEpiEndo = [
  {
    id: 'global',
    label: 'Global',
    lineage_label: null,
    obsm_key: null,
    n_cells: 200,
    embedding_ready: true,
  },
  {
    id: 'epithelial',
    label: 'Epithelial',
    lineage_label: 'Epithelial',
    obsm_key: 'X_umap_lineage_epithelial',
    n_cells: 80,
    embedding_ready: true,
  },
  {
    id: 'endothelial',
    label: 'Endothelial',
    lineage_label: 'Endothelial',
    obsm_key: 'X_umap_lineage_endothelial',
    n_cells: 40,
    embedding_ready: true,
  },
];

describe('allowedHierarchyEmbeddingViews epithelial/endothelial', () => {
  it('adds epithelial lineage-local view when exactly one Epithelial lineage is selected', () => {
    const r = allowedHierarchyEmbeddingViews(catalogWithEpiEndo, filters(['Epithelial'], null));
    expect(r.map((x) => x.id)).toEqual(['global', 'epithelial']);
  });

  it('adds endothelial lineage-local view when exactly one Endothelial lineage is selected', () => {
    const r = allowedHierarchyEmbeddingViews(catalogWithEpiEndo, filters(['Endothelial'], null));
    expect(r.map((x) => x.id)).toEqual(['global', 'endothelial']);
  });

  it('does not add epithelial view when embedding is not ready', () => {
    const cat = catalogWithEpiEndo.map((v) =>
      v.id === 'epithelial' ? { ...v, embedding_ready: false } : v
    );
    const r = allowedHierarchyEmbeddingViews(cat, filters(['Epithelial'], null));
    expect(r.map((x) => x.id)).toEqual(['global']);
  });
});

describe('userFacingEmbeddingCoordinateLabel', () => {
  it('labels cancer-relevant lineage-local embeddings clearly', () => {
    expect(userFacingEmbeddingCoordinateLabel('epithelial')).toBe('Epithelial embedding');
    expect(userFacingEmbeddingCoordinateLabel('endothelial')).toBe('Endothelial embedding');
  });
});
