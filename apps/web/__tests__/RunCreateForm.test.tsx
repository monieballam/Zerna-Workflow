import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import RunCreateForm from '@/components/runs/RunCreateForm';
import type { Dataset, PipelineTemplate } from '@zerna/sdk';

vi.mock('@/lib/run-actions', () => ({
  createRunAction: vi.fn().mockResolvedValue({}),
  resumeRunAction: vi.fn().mockResolvedValue({}),
}));

vi.mock('react-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-dom')>();
  return {
    ...actual,
    useFormState: (action: unknown, initial: unknown) => [initial, action],
    useFormStatus: () => ({ pending: false }),
  };
});

const makeTemplate = (overrides: Partial<PipelineTemplate> = {}): PipelineTemplate => ({
  id: 'tmpl-1',
  organization_id: 'org-1',
  name: 'Single Cell Pipeline',
  version: '1.1.0',
  definition: {
    metadata: {
      description: 'Test pipeline description shown under the template picker.',
    },
    methods: [
      'qc_filter',
      'doublet_detection',
      { name: 'ambient_correction', enabled_if: 'ambient_correction' },
      'normalize',
      'select_hvg',
      'run_pca',
      { name: 'batch_correct' },
      'cluster',
      'embed',
      'annotate',
      'differential_expression',
      { name: 'pathway_scoring' },
      { name: 'ligand_receptor_analysis' },
    ],
    parameter_schema: {
      properties: {
        min_genes: {
          type: 'integer',
          default: 200,
          description:
            'Drop cells with fewer detected genes than this threshold. Raising it removes emptier droplets and usually speeds later steps slightly, but it can discard small or transcriptionally quiet cell types.',
        },
        max_genes: { type: 'integer', default: 8000 },
        min_cells: { type: 'integer', default: 3 },
        max_mito_pct: { type: 'number', default: 20 },
        resolution: { type: 'number', default: 0.8 },
        clustering_method: {
          type: 'string',
          default: 'leiden',
          enum: ['leiden', 'louvain'],
        },
        n_neighbors: { type: 'integer', default: 15 },
        embedding_method: { type: 'string', default: 'umap', enum: ['umap', 'tsne'] },
        de_mode: {
          type: 'string',
          default: 'marker_ranking',
          enum: [
            'marker_ranking',
            'condition_de_within_celltype',
            'pseudobulk_sample_level_contrast',
          ],
        },
        de_groupby_key: { type: 'string' },
        de_sample_key: { type: 'string' },
        de_condition_key: { type: 'string' },
        de_focus_level: { type: 'string' },
        de_method: { type: 'string', default: 'wilcoxon' },
        de_n_genes: { type: 'integer', default: 50 },
        de_reference_level: { type: 'string' },
        de_compare_level: { type: 'string' },
        de_contrast: { type: 'string' },
        de_min_cells_per_sample: { type: 'integer', default: 10 },
        de_min_samples_per_group: { type: 'integer', default: 2 },
        de_padj_method: { type: 'string', default: 'fdr_bh' },
        de_logfc_threshold: { type: 'number', default: 0.25 },
        annotation_tissue_context: { type: 'string', default: '' },
        annotation_cancer_type: { type: 'string', default: '' },
        annotation_species: { type: 'string', default: 'human' },
        pathway_progeny_top: { type: 'integer', default: 100 },
        qc_species: { type: 'string', default: 'auto' },
        lr_expr_prop: { type: 'number', default: 0.1 },
        lr_min_cells: { type: 'integer', default: 5 },
        lr_n_perms: { type: 'integer', default: 100 },
        expected_doublet_rate: {
          type: 'number',
          default: 0.06,
          description: 'Expected doublet fraction for Scrublet-style methods.',
        },
        doublet_mode: {
          type: 'string',
          default: 'remove_doublets',
          enum: ['flag_only', 'remove_doublets'],
        },
        doublet_sample_key: { type: 'string' },
        doublet_method: {
          type: 'string',
          default: 'scrublet',
          enum: ['scrublet', 'solo'],
        },
        ambient_correction: { type: 'boolean', default: false },
        ambient_method: {
          type: 'string',
          default: 'off',
          enum: ['off', 'identity', 'soupx'],
        },
        batch_correction: { type: 'boolean', default: false },
        integration_mode: {
          type: 'string',
          default: 'harmony',
          enum: ['harmony', 'scvi'],
        },
        batch_method: {
          type: 'string',
          default: 'scvi',
          enum: ['harmony', 'scvi'],
          description:
            'Batch correction engine to use when integration is enabled. Harmony is usually much faster and lighter; scVI is slower and more resource intensive, but it can model complex batch structure more accurately.',
        },
        batch_key: { type: 'string' },
        target_sum: { type: 'number', default: 10000 },
        n_top_genes: { type: 'integer', default: 2000 },
        hvg_flavor: {
          type: 'string',
          default: 'seurat_v3',
          enum: ['seurat', 'seurat_v3', 'cell_ranger'],
        },
        hvg_batch_key: { type: 'string' },
        n_pcs: { type: 'integer', default: 50 },
        cluster_key: { type: 'string', default: 'leiden' },
        annotation_cluster_key: { type: 'string' },
        pathway_scoring: { type: 'boolean', default: false },
        pathway_database: {
          type: 'string',
          default: 'PROGENy',
          enum: ['PROGENy', 'Hallmark', 'Custom'],
        },
        pathway_method: {
          type: 'string',
          default: 'ulm',
          enum: ['ulm', 'mlm', 'aucell'],
        },
        pathway_net_path: { type: 'string' },
        ligand_receptor: { type: 'boolean', default: false },
        lr_resource_name: { type: 'string', default: 'consensus' },
        lr_communication_grouping: {
          type: 'string',
          default: 'auto',
          enum: ['auto', 'cci_major', 'cci_minor', 'cci_fine', 'cluster', 'lineage_subcluster'],
        },
        random_seed: { type: 'integer', default: 42 },
      },
      allOf: [
        {
          if: { properties: { ambient_correction: { const: true } } },
          then: { required: ['ambient_method'] },
        },
        {
          if: { properties: { batch_correction: { const: true } } },
          then: { required: ['batch_key'] },
        },
      ],
      required: [],
    },
  },
  is_active: true,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
  deprecated: false,
  visible_in_picker: true,
  recommended: true,
  template_family: 'standard',
  ...overrides,
});

const makeDataset = (overrides: Partial<Dataset> = {}): Dataset => ({
  id: 'ds-1',
  organization_id: 'org-1',
  name: 'PBMC 10k',
  description: null,
  metadata: {},
  created_at: '2025-01-01T00:00:00Z',
  versions: [
    {
      id: 'dv-1',
      version: '1',
      s3_path: 's3://bucket/ds-1/v1',
      cell_count: 10000,
      gene_count: 33538,
      file_format: 'h5ad',
      created_at: '2025-01-01T00:00:00Z',
    },
  ],
  ...overrides,
});

function createLocalStorageMock(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.has(key) ? store.get(key)! : null;
    },
    key(index: number) {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string) {
      store.delete(key);
    },
    setItem(key: string, value: string) {
      store.set(key, String(value));
    },
  };
}

function selectTemplate() {
  const select = screen.getByLabelText(/pipeline template/i);
  act(() => {
    fireEvent.change(select, { target: { value: 'tmpl-1' } });
  });
}

function expandRunFormAdvanced() {
  fireEvent.click(screen.getByTestId('run-form-advanced-summary'));
}

async function selectDataset() {
  const select = screen.getByLabelText(/dataset version/i);
  await act(async () => {
    fireEvent.change(select, { target: { value: 'dv-1' } });
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.stubGlobal('localStorage', createLocalStorageMock());
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          dataset_version_id: 'dv-1',
          obs_columns: ['orig.ident', 'cluster', 'CellType'],
          batch_candidates: ['orig.ident'],
          cluster_candidates: ['cluster', 'leiden', 'louvain'],
          source: 'metadata_file',
        }),
    })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('RunCreateForm', () => {
  it('renders dataset version and template selects', () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);
    expect(screen.getByLabelText(/dataset version/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/pipeline template/i)).toBeInTheDocument();
  });

  it('renders organized parameter sections after selecting a template', () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);

    selectTemplate();

    expect(screen.getByRole('heading', { name: 'Quality Control' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'HVG Selection' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Batch correction' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Optional analyses' })).toBeInTheDocument();
    expect(screen.getByTestId('run-form-main-section-doublets_main')).toBeInTheDocument();
    expect(screen.getByText('Advanced settings')).toBeInTheDocument();
    expect(screen.getByText(/Advanced settings for expert tuning/i)).toBeInTheDocument();
  });

  it('shows richer parameter descriptions with performance tradeoffs', () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);

    selectTemplate();
    expect(screen.getByText(/speeds later steps slightly/i)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/enable batch correction/i));
    expandRunFormAdvanced();

    expect(screen.getByText(/Harmony adjusts PCA/i)).toBeInTheDocument();
  });

  it('shows friendly DE mode labels on the main form', () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);
    selectTemplate();
    fireEvent.click(screen.getByRole('heading', { name: 'Differential expression' }));
    const deSelect = screen.getByLabelText(/differential expression mode/i);
    expect(deSelect).toBeInstanceOf(HTMLSelectElement);
    const opts = deSelect.querySelectorAll('option');
    const labels = Array.from(opts, (o) => o.textContent?.trim() ?? '');
    expect(labels).toContain('Marker ranking');
    expect(labels).toContain('Condition DE within cell type');
    expect(labels).toContain('Pseudobulk sample-level contrast');
  });

  it('shows field-level helper text for batch key, doublets, and ambient parameters', async () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);

    await selectDataset();
    selectTemplate();

    expect(
      screen.getByText(
        /Doublets are technical multiplets where two \(or more\) cells are captured/i
      )
    ).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/enable batch correction/i));
    expect(
      screen.getByText(
        /Select the metadata column that identifies which cells came from different samples/i
      )
    ).toBeInTheDocument();

    expandRunFormAdvanced();
    fireEvent.click(
      screen.getByRole('checkbox', { name: /ambient rna correction \(optional advanced\)/i })
    );
    expect(
      screen.getByText(/SoupX uses an R helper with the filtered counts matrix only/i)
    ).toBeInTheDocument();
  });

  it('omits gated ambient correction from the launch pipeline summary until enabled', async () => {
    const { container } = render(
      <RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />
    );
    await selectDataset();
    selectTemplate();
    const summary = screen.getByTestId('run-form-pipeline-steps');
    expect(within(summary).queryByText('Ambient RNA correction')).not.toBeInTheDocument();
    const list = container.querySelector('[data-testid="run-form-pipeline-steps-list"]');
    expect(list?.querySelectorAll('li').length).toBe(12);

    expandRunFormAdvanced();
    fireEvent.click(
      screen.getByRole('checkbox', { name: /ambient rna correction \(optional advanced\)/i })
    );
    expect(
      within(screen.getByTestId('run-form-pipeline-steps')).getByText('Ambient RNA correction')
    ).toBeInTheDocument();
    expect(
      container
        .querySelector('[data-testid="run-form-pipeline-steps-list"]')
        ?.querySelectorAll('li').length
    ).toBe(13);
  });

  it('defaults ambient mode to soupx when ambient correction is enabled and keeps it editable', async () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);

    await selectDataset();
    selectTemplate();
    expandRunFormAdvanced();

    fireEvent.click(
      screen.getByRole('checkbox', { name: /ambient rna correction \(optional advanced\)/i })
    );

    const ambientMode = screen.getByLabelText<HTMLSelectElement>(
      /ambient correction mode \(off \/ identity \/ soupx\)/i
    );
    expect(ambientMode.value).toBe('soupx');
    expect(ambientMode).not.toBeDisabled();
    expect(
      screen.queryByText(
        /some parameters were fixed automatically to keep this run configuration valid/i
      )
    ).not.toBeInTheDocument();
  });

  it('prefills serialized parameters from template defaults', () => {
    const { container } = render(
      <RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />
    );

    selectTemplate();

    const hiddenInput = container.querySelector('input[name="parameters"]') as HTMLInputElement;
    const parsed = JSON.parse(hiddenInput.value) as Record<string, unknown>;

    expect(parsed.min_genes).toBe(200);
    expect(parsed.batch_correction).toBe(false);
    expect(parsed.pathway_scoring).toBe(false);
    expect(parsed.pathway_database).toBe('PROGENy');
    expect(parsed.random_seed).toBe(42);
  });

  it('hides batch column until batch correction is on; integration method stays in advanced', async () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);

    await selectDataset();
    selectTemplate();

    expect(screen.queryByLabelText(/sample or batch id column/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/integration method/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/enable batch correction/i));
    expandRunFormAdvanced();
    await waitFor(() =>
      expect(screen.getByLabelText(/sample or batch id column/i).tagName).toBe('SELECT')
    );
    expect(screen.getByLabelText(/integration method/i)).toBeInTheDocument();
  });

  it('blocks run creation until conditional required parameters are provided', async () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);

    await selectDataset();
    selectTemplate();

    const submitButton = screen.getByRole('button', { name: /create run/i });
    expect(submitButton).toBeEnabled();

    fireEvent.click(screen.getByLabelText(/enable batch correction/i));

    expect(screen.getByText(/complete the required parameters/i)).toBeInTheDocument();
    expect(screen.getByText('Required')).toBeInTheDocument();
    expect(screen.getByText(/required for this run/i)).toBeInTheDocument();
    expect(submitButton).toBeDisabled();

    await waitFor(() =>
      expect(screen.getByLabelText(/sample or batch id column/i).tagName).toBe('SELECT')
    );
    fireEvent.change(screen.getByLabelText(/sample or batch id column/i), {
      target: { value: 'orig.ident' },
    });

    expect(screen.queryByText(/required for this run/i)).not.toBeInTheDocument();
    expect(submitButton).toBeEnabled();
  });

  it('renders dataset-aware column dropdowns when column metadata is available', async () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);

    await selectDataset();
    selectTemplate();
    fireEvent.click(screen.getByLabelText(/enable batch correction/i));

    await waitFor(() =>
      expect(screen.getByLabelText(/sample or batch id column/i).tagName).toBe('SELECT')
    );
    expect(screen.getAllByText(/uploaded metadata file/i).length).toBeGreaterThan(0);
  });

  it('replaces stale dataset-specific column values with detected candidates', async () => {
    render(
      <RunCreateForm
        templates={[makeTemplate()]}
        datasets={[makeDataset()]}
        initialTemplateId="tmpl-1"
        initialParameters={{
          batch_correction: true,
          batch_key: 'Batch',
          hvg_batch_key: 'Batch',
          cluster_key: 'seurat_clusters',
          annotation_cluster_key: 'seurat_clusters',
        }}
      />
    );

    await selectDataset();

    await waitFor(() =>
      expect(screen.getByLabelText(/sample or batch id column/i)).toHaveValue('orig.ident')
    );
    expandRunFormAdvanced();
    expect(screen.getByLabelText(/hvg batch column/i)).toHaveValue('orig.ident');
    expect(screen.getByLabelText(/^cluster key$/i)).toHaveValue('leiden');
    expect(screen.getByLabelText(/^annotation cluster key$/i)).toHaveValue('leiden');
  });

  it('shows lineage_subcluster as an advanced exploratory LR grouping option when annotation is on the launch path', async () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);

    await selectDataset();
    selectTemplate();
    fireEvent.click(screen.getByLabelText(/enable ligand-receptor analysis/i));
    expandRunFormAdvanced();

    const groupingSelect = screen.getByLabelText(/^LR communication grouping$/i);
    const lineageOpt = Array.from(groupingSelect.querySelectorAll('option')).find(
      (o) => o.getAttribute('value') === 'lineage_subcluster'
    );
    expect(lineageOpt).toBeTruthy();
    expect(lineageOpt?.textContent).toMatch(/advanced|exploratory/i);
  });

  it('shows optional analysis fields only when toggled on', () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);

    selectTemplate();

    expect(screen.queryByLabelText(/pathway resource/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/pathway network file/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/enable pathway activity scoring/i));
    expandRunFormAdvanced();
    expect(screen.getByLabelText(/pathway resource/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/pathway network file/i)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/pathway resource/i), { target: { value: 'Custom' } });
    expect(screen.getByLabelText(/pathway network file/i)).toBeInTheDocument();

    expect(screen.queryByLabelText(/liana resource/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/enable ligand-receptor analysis/i));
    expect(screen.getByLabelText(/liana resource/i)).toBeInTheDocument();
  });

  it('restores stored values for the selected template', () => {
    window.localStorage.setItem(
      'zerna.run-form.last-used.tmpl-1',
      JSON.stringify({
        updatedAt: '2026-03-20T08:45:00.000Z',
        parameters: {
          min_genes: 350,
          batch_correction: true,
          integration_mode: 'scvi',
          pathway_scoring: true,
          pathway_database: 'Hallmark',
          random_seed: 7,
        },
      })
    );

    const { container } = render(
      <RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />
    );

    selectTemplate();

    expect(
      screen.getByText(/restored your last-used parameters for this template/i)
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /use last run values/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/min genes per cell/i)).toHaveValue(350);
    expect(screen.getByLabelText(/enable batch correction/i)).toBeChecked();
    expect(screen.getByLabelText(/enable pathway activity scoring/i)).toBeChecked();
    expandRunFormAdvanced();
    expect(screen.getByLabelText(/integration method/i)).toHaveValue('scvi');
    expect(screen.getByLabelText(/pathway resource/i)).toHaveValue('Hallmark');
    expect(screen.getByLabelText(/random seed/i)).toHaveValue(7);

    const hiddenInput = container.querySelector('input[name="parameters"]') as HTMLInputElement;
    const parsed = JSON.parse(hiddenInput.value) as Record<string, unknown>;
    expect(parsed.min_genes).toBe(350);
    expect(parsed.batch_correction).toBe(true);
    expect(parsed.integration_mode).toBe('scvi');
    expect(parsed.pathway_database).toBe('Hallmark');
    expect(parsed.random_seed).toBe(7);
  });

  it('restores defaults for a single step and for the whole form', async () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);

    await selectDataset();
    selectTemplate();

    fireEvent.change(screen.getByLabelText(/min genes per cell/i), { target: { value: '450' } });
    fireEvent.click(screen.getByLabelText(/enable batch correction/i));
    expandRunFormAdvanced();
    fireEvent.change(screen.getByLabelText(/integration method/i), {
      target: { value: 'scvi' },
    });
    fireEvent.change(screen.getByLabelText(/sample or batch id column/i), {
      target: { value: 'orig.ident' },
    });

    const batchSection = screen
      .getByRole('heading', { name: 'Batch correction' })
      .closest('section');
    expect(batchSection).not.toBeNull();
    fireEvent.click(
      within(batchSection as HTMLElement).getByRole('button', { name: /restore step defaults/i })
    );

    expect(screen.getByLabelText(/enable batch correction/i)).not.toBeChecked();
    expect(screen.queryByLabelText(/integration method/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /restore all defaults/i }));
    expect(screen.getByLabelText(/min genes per cell/i)).toHaveValue(200);
  });

  it('stores parameters only when the form is submitted', async () => {
    const { container } = render(
      <RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />
    );

    await selectDataset();
    selectTemplate();

    fireEvent.change(screen.getByLabelText(/min genes per cell/i), { target: { value: '325' } });
    expect(window.localStorage.getItem('zerna.run-form.last-used.tmpl-1')).toBeNull();

    await act(async () => {
      fireEvent.submit(container.querySelector('form') as HTMLFormElement);
      await Promise.resolve();
    });

    const stored = JSON.parse(
      window.localStorage.getItem('zerna.run-form.last-used.tmpl-1') as string
    ) as {
      updatedAt: string;
      parameters: Record<string, unknown>;
    };

    expect(stored.parameters.min_genes).toBe(325);
    expect(stored.parameters.pathway_database).toBe('PROGENy');
    expect(stored.parameters.random_seed).toBe(42);
    expect(screen.getByRole('button', { name: /use last run values/i })).toBeInTheDocument();
  });

  it('renders empty state messages when no templates or datasets', () => {
    render(<RunCreateForm templates={[]} datasets={[]} />);
    const templateSelect = screen.getByLabelText(/pipeline template/i);
    expect(within(templateSelect).getAllByRole('option')).toHaveLength(1);
    const datasetSelect = screen.getByLabelText(/dataset version/i);
    expect(within(datasetSelect).getAllByRole('option')).toHaveLength(1);
  });

  it('shows dataset scale summary and heuristic complexity after selecting a version', async () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);
    await selectDataset();
    expect(screen.getByTestId('dataset-scale-summary')).toHaveTextContent(/PBMC 10k/);
    expect(screen.getByTestId('dataset-scale-summary')).toHaveTextContent(/10,000/);
    expect(screen.getByTestId('run-complexity-estimate')).toHaveTextContent(/Standard/);
  });

  it('shows large-run advisory with actionable suggestions for very large datasets', async () => {
    const huge = makeDataset({
      versions: [
        {
          id: 'dv-huge',
          version: 'big',
          s3_path: 's3://x',
          cell_count: 320_000,
          gene_count: 36_000,
          file_format: 'h5ad',
          metadata: { n_sources: 3 },
          created_at: '',
        },
      ],
    });
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[huge]} />);
    const ds = screen.getByLabelText(/dataset version/i);
    fireEvent.change(ds, { target: { value: 'dv-huge' } });
    await waitFor(() => {
      expect(screen.getByTestId('large-run-advisory')).toBeInTheDocument();
    });
    expect(screen.getByTestId('large-run-advisory')).toHaveTextContent(/memory/i);
    expect(screen.getByTestId('large-run-advisory')).toHaveTextContent(/Lightweight preset/i);
  });

  it('applies launch preset bundles without blocking manual overrides afterward', async () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);
    await selectDataset();
    selectTemplate();

    fireEvent.change(screen.getByLabelText(/launch preset/i), {
      target: { value: 'deep' },
    });
    expect(screen.getByLabelText(/enable pathway activity scoring/i)).toBeChecked();
    expect(screen.getByLabelText(/enable ligand/i)).toBeChecked();

    fireEvent.change(screen.getByLabelText(/launch preset/i), {
      target: { value: 'lightweight' },
    });
    expect(screen.getByLabelText(/enable pathway activity scoring/i)).not.toBeChecked();
    expect(screen.getByLabelText(/enable ligand/i)).not.toBeChecked();

    fireEvent.click(screen.getByLabelText(/enable pathway activity scoring/i));
    expect(screen.getByLabelText(/enable pathway activity scoring/i)).toBeChecked();
  });

  it('shows DE mode guidance when the differential expression section is expanded', async () => {
    render(<RunCreateForm templates={[makeTemplate()]} datasets={[makeDataset()]} />);
    selectTemplate();
    fireEvent.click(screen.getByRole('heading', { name: 'Differential expression' }));
    expect(await screen.findByTestId('de-mode-guidance')).toHaveTextContent(/Exploratory/i);
  });
});
