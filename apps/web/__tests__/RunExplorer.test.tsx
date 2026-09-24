import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import RunExplorer from '@/components/runs/RunExplorer';

vi.mock('@/components/embedding/LazyEmbeddingViewer', () => ({
  default: ({
    embedding,
    availableFields,
    activeColorField,
  }: {
    embedding: { cells: unknown[] };
    availableFields: string[];
    activeColorField?: string;
  }) => (
    <div data-testid="lazy-embedding-viewer">
      viewer({embedding.cells.length} cells / {availableFields.join(',')} /{' '}
      {activeColorField ?? 'none'})
    </div>
  ),
}));

vi.mock('@/components/embedding/EmbeddingComparison', () => ({
  default: ({
    entries,
    activeColorField,
  }: {
    entries: Array<{ label: string }>;
    activeColorField?: string;
  }) => (
    <div data-testid="embedding-comparison">
      comparison({entries.length} entries / {activeColorField ?? 'none'})
    </div>
  ),
}));

const payload = {
  run_id: 'run-1',
  embedding_key: 'X_umap',
  embedding: {
    cells: [
      { id: 'cell-1', x: 0, y: 0 },
      { id: 'cell-2', x: 1, y: 1 },
    ],
    bounds: { minX: 0, maxX: 1, minY: 0, maxY: 1 },
  },
  metadata: [
    {
      cellId: 'cell-1',
      lineage: 'Immune',
      level2: 'T cells',
      level3: 'CD8',
      displayLabel: 'CD8 T',
      cluster: '0',
      cellType: 'T cell',
      condition: 'Tumor',
      sample: 'S1',
    },
    {
      cellId: 'cell-2',
      lineage: 'Stromal',
      level2: 'Fibroblasts',
      level3: 'CAF',
      displayLabel: 'CAF',
      cluster: '1',
      cellType: 'B cell',
      condition: 'Normal',
      sample: 'S2',
    },
  ],
  available_fields: [
    'lineage',
    'level2',
    'level3',
    'displayLabel',
    'cluster',
    'cellType',
    'sample',
    'condition',
  ],
  categorical_fields: [
    'lineage',
    'level2',
    'level3',
    'displayLabel',
    'cluster',
    'cellType',
    'sample',
    'condition',
  ],
  continuous_fields: [],
  field_ranges: {},
  filter_fields: ['lineage', 'sample', 'condition'],
  advanced_filter_fields: [
    'displayLabel',
    'cellType',
    'rawAnnotationLabel',
    'level2',
    'level3',
    'cluster',
  ],
  filter_values: {
    cluster: ['0', '1'],
    condition: ['Tumor', 'Normal'],
    lineage: ['Immune', 'Stromal'],
    level2: ['T cells', 'Fibroblasts'],
    level3: ['CD8', 'CAF'],
    sample: ['S1', 'S2'],
    cellType: ['T cell', 'B cell'],
    displayLabel: ['CD8 T', 'CAF'],
    rawAnnotationLabel: ['T cell', 'B cell'],
  },
  hierarchy_filter_axes: {
    level2_by_lineage: {
      Immune: ['T cells'],
      Stromal: ['Fibroblasts'],
    },
    level3_by_lineage_major: {
      'Immune|T cells': ['CD8'],
      'Stromal|Fibroblasts': ['CAF'],
    },
  },
  overview: {
    n_cells: 2,
    n_genes: 100,
    n_clusters: 2,
    n_cell_types: 2,
    n_samples: 2,
    n_conditions: 2,
    top_cell_types: [
      { label: 'T cell', count: 1 },
      { label: 'B cell', count: 1 },
    ],
    top_conditions: [
      { label: 'Tumor', count: 1 },
      { label: 'Normal', count: 1 },
    ],
  },
  cluster_summaries: [
    {
      cluster_id: '0',
      n_cells: 1,
      label: 'T cell',
      confidence: 'high',
      summary: 'T cell cluster',
      top_markers: ['CD3D', 'TRBC1'],
      evidence_count: 2,
      evidence_hits: [{ cluster_id: 'prior_1', label: 'T cell', lineage: 'Lymphoid', score: 0.91 }],
      top_cell_types: [{ cell_type: 'T cell', score: 0.91, n_markers: 6 }],
    },
    {
      cluster_id: '1',
      n_cells: 1,
      label: 'B cell',
      confidence: 'medium',
      summary: 'B cell cluster',
      top_markers: ['MS4A1'],
      evidence_count: 1,
      evidence_hits: [{ cluster_id: 'prior_2', label: 'B cell', lineage: 'Lymphoid', score: 0.73 }],
      top_cell_types: [{ cell_type: 'B cell', score: 0.73, n_markers: 4 }],
    },
  ],
  total_cells: 2,
  sampled: false,
  explorer_view: 'global',
  explorer_view_label: 'Global',
  available_views: [
    {
      id: 'global',
      label: 'Global',
      lineage_label: null,
      obsm_key: null,
      n_cells: 2,
      embedding_ready: true,
    },
    {
      id: 'immune',
      label: 'Immune',
      lineage_label: 'Immune',
      obsm_key: 'X_umap_lineage_immune',
      n_cells: 2,
      embedding_ready: true,
    },
    {
      id: 'fine_t_cells',
      label: 'T cells (fine)',
      lineage_label: 'T cells',
      obsm_key: 'X_umap_fine_t_cells',
      n_cells: 1,
      embedding_ready: true,
    },
  ],
};

const immuneExplorerPayload = {
  ...payload,
  explorer_view: 'immune',
  explorer_view_label: 'Immune (lineage)',
  embedding_key: 'X_umap_lineage_immune',
  embedding: {
    cells: [
      { id: 'cell-1', x: 10, y: 20 },
      { id: 'cell-2', x: 30, y: 40 },
    ],
    bounds: { minX: 10, maxX: 30, minY: 20, maxY: 40 },
  },
  lineage_embedding_fallback: false,
};

const fineTCellsExplorerPayload = {
  ...immuneExplorerPayload,
  explorer_view: 'fine_t_cells',
  explorer_view_label: 'T cells (fine)',
  embedding_key: 'X_umap_fine_t_cells',
  embedding: {
    cells: [
      { id: 'cell-1', x: -1, y: -2 },
      { id: 'cell-2', x: 3, y: 4 },
    ],
    bounds: { minX: -1, maxX: 3, minY: -2, maxY: 4 },
  },
};

const geneOverlay = {
  run_id: 'run-1',
  gene: 'EPCAM',
  values: {
    'cell-1': 0.2,
    'cell-2': 0.8,
  },
  min: 0.2,
  max: 0.8,
  total_cells: 2,
  sampled: false,
};

function openClusterInspector() {
  const root = screen.getByTestId('results-cluster-inspector-details');
  const summary = root.querySelector('summary');
  expect(summary).toBeTruthy();
  fireEvent.click(summary!);
}

function explorerResponseForUrl(url: string) {
  if (url.includes('/gene-overlay')) {
    return geneOverlay;
  }
  let explorerView: string;
  try {
    const u = url.includes('?') ? new URL(url, 'http://localhost') : null;
    explorerView = u?.searchParams.get('explorer_view') ?? 'global';
  } catch {
    explorerView = 'global';
  }
  if (explorerView === 'immune') return immuneExplorerPayload;
  if (explorerView === 'fine_t_cells') return fineTCellsExplorerPayload;
  return payload;
}

describe('RunExplorer', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const url =
        typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      const body = explorerResponseForUrl(url);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(body),
      } as Response);
    });
  });

  it('renders overview, embedding viewer, and cluster detail', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    openClusterInspector();
    expect(screen.getByText('Explore cells')).toBeTruthy();
    expect(screen.getByText('T cell cluster')).toBeTruthy();
    expect(screen.getByTestId('lazy-embedding-viewer').textContent).toContain('viewer(2 cells');
    expect(screen.getByText('CD3D')).toBeTruthy();
    expect(screen.getByText('Reference matches')).toBeTruthy();
  });

  it('filters the explorer payload by metadata field', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    fireEvent.click(screen.getAllByText('Condition')[0]);
    fireEvent.click(screen.getByLabelText('Tumor'));

    await waitFor(() => {
      expect(screen.getByTestId('lazy-embedding-viewer').textContent).toContain('viewer(1 cells');
    });

    openClusterInspector();
    expect(screen.getByRole('button', { name: /#0/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /#1/ })).toBeNull();
  });

  it('lineage filter subsets UMAP, legend, composition, and cell stat to the filtered cohort', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    const legendAll = screen.getByTestId('embedding-legend-categorical');
    expect(within(legendAll).getByRole('button', { name: /Stromal/i })).toBeTruthy();

    fireEvent.click(screen.getByTestId('explorer-filter-group-lineage').querySelector('summary')!);
    fireEvent.click(screen.getByLabelText('Immune'));

    await waitFor(() => {
      expect(screen.getByTestId('lazy-embedding-viewer').textContent).toContain('viewer(1 cells');
    });

    const legendImmune = screen.getByTestId('embedding-legend-categorical');
    expect(within(legendImmune).getByRole('button', { name: /Immune/i })).toBeTruthy();
    expect(within(legendImmune).queryByRole('button', { name: /Stromal/i })).toBeNull();
    expect(screen.queryByText(/full explorer sample/i)).toBeNull();

    const comp = screen.getByTestId('run-composition-overview');
    await waitFor(() => {
      expect(within(comp).queryByText('Fibroblasts')).toBeNull();
    });

    const cellsCard = screen.getAllByText('Cells')[0].closest('.card');
    expect(cellsCard).toHaveTextContent('1');
    expect(cellsCard).toHaveTextContent(/before filters/);

    const stats = within(screen.getByTestId('explorer-summary-stats'));
    expect(stats.getByText('Clusters').closest('.card')).toHaveTextContent('1');
    expect(stats.getByText('Clusters').closest('.card')).toHaveTextContent(/before filters/);
    expect(stats.getByText('Samples').closest('.card')).toHaveTextContent('1');
    expect(stats.getByText('Samples').closest('.card')).toHaveTextContent(/before filters/);
    expect(stats.getByText('Conditions').closest('.card')).toHaveTextContent('1');
    expect(stats.getByText('Conditions').closest('.card')).toHaveTextContent(/before filters/);
    expect(stats.getByText('Embedding').closest('.card')).toHaveTextContent(/filtered cohort/i);
  });

  it('top summary stats use API overview when no cohort filters', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    const stats = within(screen.getByTestId('explorer-summary-stats'));
    expect(stats.getByText('Clusters').closest('.card')).toHaveTextContent('2');
    expect(stats.getByText('Samples').closest('.card')).toHaveTextContent('2');
    expect(stats.getByText('Conditions').closest('.card')).toHaveTextContent('2');
    expect(stats.getByText('Clusters').closest('.card')).not.toHaveTextContent(/before filters/);
  });

  it('shows cluster labels in the cluster filter while filtering by cluster id', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    fireEvent.click(screen.getAllByText('Cluster')[0]);

    expect(screen.getByLabelText('Cluster 0 · T cell')).toBeTruthy();
    expect(screen.getByLabelText('Cluster 1 · B cell')).toBeTruthy();

    fireEvent.click(screen.getByLabelText('Cluster 0 · T cell'));

    await waitFor(() => {
      expect(screen.getByTestId('lazy-embedding-viewer').textContent).toContain('viewer(1 cells');
    });

    openClusterInspector();
    expect(screen.getByRole('button', { name: /#0/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /#1/ })).toBeNull();
  });

  it('loads a gene overlay from the saved run artifact', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    fireEvent.change(screen.getByPlaceholderText(/gene/i), {
      target: { value: 'EPCAM' },
    });
    fireEvent.click(screen.getByRole('button', { name: /plot gene/i }));

    await waitFor(() => {
      expect(screen.getByTestId('lazy-embedding-viewer').textContent).toContain(
        'geneExpression:EPCAM'
      );
    });

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/gene-overlay?gene=EPCAM&max_cells=50000')
    );
  });

  it('switches to split view for supported metadata fields', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    fireEvent.change(screen.getByDisplayValue('Single panel'), {
      target: { value: 'condition' },
    });

    await waitFor(() => {
      expect(screen.getByTestId('embedding-comparison').textContent).toContain(
        'comparison(2 entries'
      );
    });
  });

  it('renders bottom categorical legend and active cohort banner', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    expect(screen.getByTestId('embedding-legend-categorical')).toBeTruthy();
    expect(screen.getByTestId('active-cohort-banner')).toBeTruthy();
  });

  it('legend click sets focus and clear focus removes it', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('embedding-legend-categorical')).toBeTruthy();
    });

    const legend = screen.getByTestId('embedding-legend-categorical');
    fireEvent.click(within(legend).getByRole('button', { name: /Immune/i }));

    await waitFor(() => {
      expect(screen.getByTestId('focus-chip')).toHaveTextContent(/Focus/i);
    });

    fireEvent.click(screen.getByTestId('clear-focus'));
    expect(screen.queryByTestId('focus-chip')).toBeNull();
  });

  it('replaces categorical legend with expression scale when gene overlay is active', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    fireEvent.change(screen.getByPlaceholderText(/gene/i), {
      target: { value: 'EPCAM' },
    });
    fireEvent.click(screen.getByRole('button', { name: /plot gene/i }));

    await waitFor(() => {
      expect(screen.getByTestId('embedding-legend-expression')).toBeTruthy();
    });
    expect(screen.queryByTestId('embedding-legend-categorical')).toBeNull();
  });

  it('active cohort banner reflects filter chips', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('active-cohort-banner')).toBeTruthy();
    });

    fireEvent.click(screen.getAllByText('Condition')[0]);
    fireEvent.click(screen.getByLabelText('Tumor'));

    await waitFor(() => {
      const banner = screen.getByTestId('active-cohort-banner');
      expect(within(banner).getByText(/Tumor/)).toBeTruthy();
    });

    expect(screen.getByTestId('clear-all-filters')).toBeTruthy();
    expect(screen.getAllByTestId('banner-filter-chip').length).toBeGreaterThan(0);
  });

  it('filter groups are compact details closed by default', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('explorer-filter-group-cluster')).toBeTruthy();
    });

    const clusterGroup = screen.getByTestId('explorer-filter-group-cluster');
    expect(clusterGroup.tagName).toBe('DETAILS');
    expect(clusterGroup).not.toHaveAttribute('open');
  });

  it('embedding context strip shows view-by label and inspector cluster', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('embedding-context-strip')).toBeTruthy();
    });

    const strip = screen.getByTestId('embedding-context-strip');
    expect(strip).toHaveTextContent(/View by/);
    expect(screen.getByTestId('context-cluster-line')).toBeTruthy();
  });

  it('defaults color to lineage on load', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('lazy-embedding-viewer').textContent).toMatch(/\/ lineage\b/);
    });
  });

  it('View by lists broad, major, and fine subtype; fine subtype is not duplicated under Advanced', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      const sel = screen.getByTestId('explorer-color-by-annotation');
      const texts = [...sel.querySelectorAll('option')].map((o) => o.textContent ?? '');
      expect(texts.some((t) => /Broad.*lineage|auto_level1/i.test(t))).toBe(true);
      expect(texts.some((t) => /Major|auto_level2/i.test(t))).toBe(true);
      expect(texts.some((t) => /Fine subtype|auto_level3/i.test(t))).toBe(true);
    });

    await waitFor(() => {
      const tech = screen.getByTestId('explorer-color-by-technical');
      const texts = [...tech.querySelectorAll('option')].map((o) => o.textContent ?? '');
      expect(texts.some((t) => /Fine subtype \(auto_level3\)/i.test(t))).toBe(false);
    });
  });

  it('requests explorer payload with global view on initial load', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('explorer_view=global'));
  });

  it('lineage-scoped level2 filter lists only majors under selected lineage(s)', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    const adv = screen.getByText(/Advanced: final_display/i).closest('details');
    expect(adv).toBeTruthy();
    fireEvent.click(adv!.querySelector('summary')!);

    const l2 = screen.getByTestId('explorer-filter-group-level2');
    fireEvent.click(l2.querySelector('summary')!);
    expect(within(l2).queryByLabelText('T cells')).toBeNull();
    expect(within(l2).queryByLabelText('Fibroblasts')).toBeNull();

    fireEvent.click(screen.getByTestId('explorer-filter-group-lineage').querySelector('summary')!);
    fireEvent.click(screen.getByLabelText('Immune'));
    fireEvent.click(l2.querySelector('summary')!);
    expect(within(l2).getByLabelText('T cells')).toBeTruthy();
    expect(within(l2).queryByLabelText('Fibroblasts')).toBeNull();
  });

  it('structural level3 cohort filter is empty until lineage and major type are selected', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    const adv = screen.getByText(/Advanced: final_display/i).closest('details');
    expect(adv).toBeTruthy();
    fireEvent.click(adv!.querySelector('summary')!);

    const l3Group = screen.getByTestId('explorer-filter-group-level3');
    fireEvent.click(l3Group.querySelector('summary')!);
    expect(within(l3Group).queryByLabelText('CD8')).toBeNull();
    expect(within(l3Group).queryByLabelText('CAF')).toBeNull();

    fireEvent.click(screen.getByTestId('explorer-filter-group-lineage').querySelector('summary')!);
    fireEvent.click(screen.getByLabelText('Immune'));
    fireEvent.click(screen.getByTestId('explorer-filter-group-level2').querySelector('summary')!);
    fireEvent.click(screen.getByLabelText('T cells'));

    fireEvent.click(l3Group.querySelector('summary')!);
    expect(within(l3Group).getByLabelText('CD8')).toBeTruthy();
    expect(within(l3Group).queryByLabelText('CAF')).toBeNull();
  });

  it('structural level3 filter subsets embedding to one subtype within a major branch', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    const adv = screen.getByText(/Advanced: final_display/i).closest('details');
    fireEvent.click(adv!.querySelector('summary')!);

    fireEvent.click(screen.getByTestId('explorer-filter-group-lineage').querySelector('summary')!);
    fireEvent.click(screen.getByLabelText('Immune'));
    fireEvent.click(screen.getByTestId('explorer-filter-group-level2').querySelector('summary')!);
    fireEvent.click(screen.getByLabelText('T cells'));
    fireEvent.click(screen.getByTestId('explorer-filter-group-level3').querySelector('summary')!);
    fireEvent.click(screen.getByLabelText('CD8'));

    await waitFor(() => {
      expect(screen.getByTestId('lazy-embedding-viewer').textContent).toContain('viewer(1 cells');
    });

    const comp = screen.getByTestId('run-composition-overview');
    await waitFor(() => {
      expect(within(comp).queryByText('Fibroblasts')).toBeNull();
    });
  });

  it('does not refetch when lineage filter changes alone (no silent embedding switch)', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    const callsAfterLoad = (global.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls
      .length;

    fireEvent.click(screen.getByTestId('explorer-filter-group-lineage').querySelector('summary')!);
    fireEvent.click(screen.getByLabelText('Immune'));

    await waitFor(() => {
      expect(screen.getByTestId('lazy-embedding-viewer').textContent).toContain('viewer(1 cells');
    });

    const callsAfterFilter = (global.fetch as unknown as { mock: { calls: unknown[][] } }).mock
      .calls.length;
    expect(callsAfterFilter).toBe(callsAfterLoad);
  });

  it('shows lineage-local embedding option when one lineage is selected and catalog has it', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('explorer-embedding-view-select')).toBeTruthy();
    });

    const sel = screen.getByTestId<HTMLSelectElement>('explorer-embedding-view-select');
    const options = sel.options as unknown as HTMLOptionsCollection;
    const initialValues: string[] = [];
    for (let i = 0; i < options.length; i++) {
      initialValues.push(options[i].value);
    }
    expect(initialValues).toEqual(['global']);

    fireEvent.click(screen.getByTestId('explorer-filter-group-lineage').querySelector('summary')!);
    fireEvent.click(screen.getByLabelText('Immune'));

    await waitFor(() => {
      const options = sel.options as unknown as HTMLOptionsCollection;
      const values: string[] = [];
      for (let i = 0; i < options.length; i++) {
        values.push(options[i].value);
      }
      expect(values).toContain('global');
      expect(values).toContain('immune');
    });
  });

  it('refetches with explorer_view when user picks lineage-local embedding', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    fireEvent.click(screen.getByTestId('explorer-filter-group-lineage').querySelector('summary')!);
    fireEvent.click(screen.getByLabelText('Immune'));

    const sel = await screen.findByTestId('explorer-embedding-view-select');
    fireEvent.change(sel, { target: { value: 'immune' } });

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('explorer_view=immune'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('embedding-context-strip')).toHaveTextContent(/Lineage-local/i);
    });
  });

  it('shows fine embedding option when one lineage and one level2 are selected', async () => {
    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    fireEvent.click(screen.getByTestId('explorer-filter-group-lineage').querySelector('summary')!);
    fireEvent.click(screen.getByLabelText('Immune'));

    const advBlock = screen.getByText(/Advanced: final_display/i).closest('details');
    expect(advBlock).toBeTruthy();
    fireEvent.click(advBlock!.querySelector('summary')!);

    fireEvent.click(screen.getByTestId('explorer-filter-group-level2').querySelector('summary')!);
    fireEvent.click(screen.getByLabelText('T cells'));

    const sel = await screen.findByTestId('explorer-embedding-view-select');
    await waitFor(() => {
      const values = [...(sel as HTMLSelectElement).options].map((o) => o.value);
      expect(values).toEqual(['global', 'immune', 'fine_t_cells']);
    });
  });

  it('omits lineage-local option when catalog marks embedding not ready', async () => {
    const noLineageEmb = {
      ...payload,
      available_views: payload.available_views.map((v) =>
        v.id === 'immune' ? { ...v, embedding_ready: false } : v
      ),
    };
    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const url =
        typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes('/gene-overlay')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(geneOverlay) } as Response);
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(noLineageEmb) } as Response);
    });

    render(<RunExplorer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('run-explorer')).toBeTruthy();
    });

    fireEvent.click(screen.getByTestId('explorer-filter-group-lineage').querySelector('summary')!);
    fireEvent.click(screen.getByLabelText('Immune'));

    const sel = await screen.findByTestId('explorer-embedding-view-select');
    await waitFor(() => {
      expect([...(sel as HTMLSelectElement).options].map((o) => o.value)).toEqual(['global']);
    });
  });
});
