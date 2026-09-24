import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { Artifact } from '@zerna/sdk';
import RunResults from '@/components/runs/RunResults';

const mockArtifacts: Artifact[] = [
  {
    id: 'path-art-1',
    run_id: 'run-1',
    artifact_type: 'pathway_scores',
    s3_path: 's3://x',
    size_bytes: 100,
    metadata: {},
    download_url: null,
    created_at: '',
  },
  {
    id: 'lr-art-1',
    run_id: 'run-1',
    artifact_type: 'liana_results',
    s3_path: 's3://y',
    size_bytes: 100,
    metadata: {},
    download_url: null,
    created_at: '',
  },
];

describe('RunResults', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          run_id: 'run-1',
          status: 'completed',
          step_metrics: {
            cluster: {
              n_clusters: 3,
              cluster_key: 'leiden',
              cluster_sizes: [8, 30, 12],
              clusters: [
                { cluster_id: '10', label: 'Myeloid', n_cells: 8 },
                { cluster_id: '2', label: 'B cell', n_cells: 30 },
                { cluster_id: '1', label: 'T cell', n_cells: 12 },
              ],
            },
          },
          software_versions: {},
          artifact_id: null,
          artifact_size_bytes: null,
          download_url: null,
        }),
    } as Response);
  });

  it('renders biological summary when metrics support it', async () => {
    render(<RunResults runId="run-1" mode="details" />);

    await waitFor(() => {
      expect(screen.getByTestId('results-biological-summary')).toBeInTheDocument();
    });

    expect(screen.getByText(/Biological summary/i)).toBeInTheDocument();
    expect(screen.getByTestId('results-biological-summary')).toHaveTextContent(/clusters/i);
  });

  it('renders cluster labels when results include named clusters', async () => {
    render(<RunResults runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('results-clustering-details')).toBeInTheDocument();
    });

    expect(screen.getByTestId('results-clustering-collapsed-summary')).toHaveTextContent(
      '3 clusters identified • cluster key: leiden'
    );

    fireEvent.click(
      within(screen.getByTestId('results-clustering-details')).getByText('Clustering')
    );

    await waitFor(() => {
      expect(screen.getByText('Cluster key: leiden')).toBeInTheDocument();
    });
    expect(screen.getByText('T cell')).toBeInTheDocument();
    expect(screen.getByText('B cell')).toBeInTheDocument();
    expect(screen.getByText('Myeloid')).toBeInTheDocument();
  });

  it('allows sorting clusters by cell count', async () => {
    render(<RunResults runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('results-clustering-details')).toBeInTheDocument();
    });
    fireEvent.click(
      within(screen.getByTestId('results-clustering-details')).getByText('Clustering')
    );

    await waitFor(() => {
      expect(screen.getByLabelText(/sort clusters/i)).toBeInTheDocument();
    });

    const list = screen.getByRole('list');
    const idsBefore = within(list)
      .getAllByRole('listitem')
      .map((item) => item.textContent ?? '');
    expect(idsBefore[0]).toContain('Cluster 1');
    expect(idsBefore[1]).toContain('Cluster 2');
    expect(idsBefore[2]).toContain('Cluster 10');

    fireEvent.change(screen.getByLabelText(/sort clusters/i), {
      target: { value: 'cells_desc' },
    });

    const idsAfter = within(list)
      .getAllByRole('listitem')
      .map((item) => item.textContent ?? '');
    expect(idsAfter[0]).toContain('Cluster 2');
    expect(idsAfter[1]).toContain('Cluster 1');
    expect(idsAfter[2]).toContain('Cluster 10');
  });

  it('shows downstream analysis placeholders when pathway and LR were not run', async () => {
    render(<RunResults runId="run-1" mode="details" />);

    await waitFor(() => {
      expect(screen.getByTestId('results-clustering-details')).toBeInTheDocument();
    });

    expect(screen.getByText('Downstream analyses')).toBeInTheDocument();
    expect(screen.getByTestId('pathway-section')).toHaveTextContent(/Pathway activity scoring/i);
    expect(screen.getByTestId('liana-section')).toHaveTextContent(/Ligand/i);
    expect(screen.getByTestId('de-section')).toHaveTextContent(/Differential expression/i);
  });

  it('shows pathway and ligand–receptor sections with previews and full-result links', async () => {
    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (url.includes('/artifacts/path-art-1/preview')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              columns: ['cell_id', 'HALLMARK_INFLAMMATORY', 'HALLMARK_APOPTOSIS'],
              rows: [
                { cell_id: 'c1', HALLMARK_INFLAMMATORY: 0.5, HALLMARK_APOPTOSIS: 0.1 },
                { cell_id: 'c2', HALLMARK_INFLAMMATORY: 0.2, HALLMARK_APOPTOSIS: 0.3 },
              ],
              total_rows: 2,
              truncated: false,
              metadata: {},
            }),
        } as Response);
      }
      if (url.includes('/artifacts/lr-art-1/preview')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              columns: ['source', 'target', 'ligand', 'receptor', 'liana_rank'],
              rows: [
                { source: '0', target: '1', ligand: 'L1', receptor: 'R1', liana_rank: 0.05 },
                { source: '0', target: '1', ligand: 'L2', receptor: 'R2', liana_rank: 0.2 },
              ],
              total_rows: 2,
              truncated: false,
              metadata: {},
            }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            run_id: 'run-1',
            status: 'completed',
            step_metrics: {
              pathway_scoring: {
                n_pathways_scored: 50,
                n_cells: 100,
                pathway_database: 'Reactome',
                methods_used: ['wmean'],
                obsm_key: 'pathway_scores',
              },
              ligand_receptor_analysis: {
                n_interactions: 200,
                n_cluster_pairs: 12,
                n_clusters: 5,
                cluster_key: 'leiden',
                resource_name: 'OmniPath',
              },
            },
            software_versions: {},
            artifact_id: null,
            artifact_size_bytes: null,
            download_url: null,
          }),
      } as Response);
    });

    render(<RunResults runId="run-1" mode="details" artifacts={mockArtifacts} />);

    await waitFor(() => {
      expect(screen.getByTestId('pathway-section')).toBeInTheDocument();
    });

    expect(screen.getByText('Downstream analyses')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('pathway-preview-bars')).toBeInTheDocument();
    });
    expect(screen.getByTestId('pathway-view-full-link')).toHaveAttribute(
      'href',
      '/runs/run-1/artifacts/path-art-1'
    );

    await waitFor(() => {
      expect(screen.getByTestId('liana-preview-table')).toBeInTheDocument();
    });
    expect(screen.getByTestId('liana-view-full-link')).toHaveAttribute(
      'href',
      '/runs/run-1/artifacts/lr-art-1'
    );

    expect(screen.getByTestId('pathway-preview-interpretation')).toHaveTextContent(
      'Preview shows the strongest pathway activity signals in the scored cells'
    );
    expect(screen.getByTestId('liana-preview-interpretation')).toHaveTextContent(
      'Preview shows top inferred interactions by LIANA aggregate rank'
    );
  });

  it('shows downstream analyses with only differential expression when other steps absent', async () => {
    const withDe: Artifact[] = [
      {
        id: 'de-art-1',
        run_id: 'run-1',
        artifact_type: 'de_results',
        s3_path: 's3://de',
        size_bytes: 50,
        metadata: {},
        download_url: null,
        created_at: '',
      },
    ];

    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (url.includes('/artifacts/de-art-1/preview')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              columns: ['gene', 'cluster', 'log_fold_change', 'adjusted_p_value'],
              rows: [
                { gene: 'G1', cluster: '0', log_fold_change: 1.2, adjusted_p_value: 0.01 },
                { gene: 'G2', cluster: '1', log_fold_change: -0.5, adjusted_p_value: 0.05 },
              ],
              total_rows: 2,
              truncated: false,
              metadata: {},
            }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            run_id: 'run-1',
            status: 'completed',
            step_metrics: {
              differential_expression: {
                de_mode: 'marker_ranking',
                method_executed: 'wilcoxon',
                n_clusters: 3,
                n_comparisons: 6,
                n_genes_tested: 2000,
                cluster_key: 'leiden',
                statistical_warning:
                  'Exploratory marker ranking (Scanpy rank_genes_groups); not a replicate-aware inferential test at the sample level.',
              },
            },
            software_versions: {},
            artifact_id: null,
            artifact_size_bytes: null,
            download_url: null,
          }),
      } as Response);
    });

    render(<RunResults runId="run-1" mode="details" artifacts={withDe} />);

    await waitFor(() => {
      expect(screen.getByTestId('de-section')).toBeInTheDocument();
    });

    expect(screen.getByText('Downstream analyses')).toBeInTheDocument();
    expect(screen.getByText('Mode: Marker ranking')).toBeInTheDocument();
    expect(screen.getByTestId('de-view-full-link')).toHaveAttribute(
      'href',
      '/runs/run-1/artifacts/de-art-1'
    );
    expect(screen.getByTestId('de-preview-interpretation')).toHaveTextContent(
      /cell-level ranking/i
    );

    await waitFor(() => {
      expect(screen.getByTestId('de-preview-table')).toBeInTheDocument();
    });

    expect(screen.getByTestId('pathway-section')).toHaveTextContent(/not run|metrics/i);
    expect(screen.getByTestId('liana-section')).toHaveTextContent(/not run|metrics/i);
  });

  it('shows differential expression placeholder when DE was not run', async () => {
    render(<RunResults runId="run-1" mode="details" artifacts={mockArtifacts} />);

    await waitFor(() => {
      expect(screen.getByTestId('results-clustering-details')).toBeInTheDocument();
    });

    expect(screen.getByTestId('de-section')).toHaveTextContent(/Differential expression/i);
    expect(screen.getByTestId('de-section')).toHaveTextContent(/not run|metrics/i);
  });

  it('preprocessing cards are collapsed by default with compact summaries; expand on click', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          run_id: 'run-1',
          status: 'completed',
          step_metrics: {
            qc_filter: {
              n_cells_before: 4553,
              n_cells_after: 4530,
              n_genes_before: 20000,
              n_genes_after: 19464,
              median_genes_per_cell: 1200,
              median_counts_per_cell: 5000,
            },
            doublet_detection: {
              n_cells_before: 4530,
              n_cells_after: 4486,
              n_predicted_doublets: 44,
              doublet_rate: 0.01,
              mean_doublet_score: 0.05,
            },
            batch_correction_harmony: {
              batch_key: 'sample',
              n_batches: 3,
              kbet_score: 0.5,
              lisi_score: 0.6,
            },
            run_pca: {
              n_components_computed: 50,
              variance_ratio_top10: [0.2, 0.15, 0.1, 0.08, 0.08, 0.05, 0.04, 0.03, 0.02, 0.01],
            },
            normalize: {
              target_sum: 10000,
              log1p_applied: true,
              scale_applied: false,
            },
            select_hvg: {
              n_genes_total: 20000,
              n_hvgs_selected: 2000,
            },
            cluster: {
              n_clusters: 3,
              cluster_key: 'leiden',
              cluster_sizes: [8, 30, 12],
              clusters: [
                { cluster_id: '10', label: 'Myeloid', n_cells: 8 },
                { cluster_id: '2', label: 'B cell', n_cells: 30 },
                { cluster_id: '1', label: 'T cell', n_cells: 12 },
              ],
            },
            embed: {
              embedding_key: 'X_umap',
              method_executed: 'umap',
              n_components: 2,
              representation_used: 'X_pca',
            },
          },
          software_versions: {},
          artifact_id: null,
          artifact_size_bytes: null,
          download_url: null,
        }),
    } as Response);

    render(<RunResults runId="run-1" mode="details" />);

    await waitFor(() => {
      expect(screen.getByTestId('results-qc-details')).toBeInTheDocument();
    });

    const qc = screen.getByTestId('results-qc-details');
    const doublet = screen.getByTestId('results-doublet-details');
    const norm = screen.getByTestId('results-normalize-details');
    const hvg = screen.getByTestId('results-hvg-details');
    const batch = screen.getByTestId('results-batch-details');
    const pca = screen.getByTestId('results-pca-details');
    const clustering = screen.getByTestId('results-clustering-details');
    const embed = screen.getByTestId('results-embed-details');

    for (const el of [qc, doublet, norm, hvg, batch, pca, clustering, embed]) {
      expect(el).not.toHaveAttribute('open');
    }

    expect(screen.getByTestId('results-qc-collapsed-summary')).toHaveTextContent(
      '4,530 / 4,553 cells retained • 19,464 genes after filtering'
    );
    expect(screen.getByTestId('results-doublet-collapsed-summary')).toHaveTextContent(
      '44 predicted doublets • 1.0% flagged'
    );
    expect(screen.getByTestId('results-batch-collapsed-summary')).toHaveTextContent(
      'Harmony on 3 batches'
    );
    expect(screen.getByTestId('results-pca-collapsed-summary')).toHaveTextContent(
      '50 components • top 10 PCs explain 76% variance'
    );
    expect(screen.getByTestId('results-clustering-collapsed-summary')).toHaveTextContent(
      '3 clusters identified • cluster key: leiden'
    );
    expect(screen.getByTestId('results-normalize-collapsed-summary')).toHaveTextContent(
      /target sum/i
    );
    expect(screen.getByTestId('results-hvg-collapsed-summary')).toHaveTextContent(
      '2,000 HVGs from 20,000 genes'
    );
    expect(screen.getByTestId('results-embed-collapsed-summary')).toHaveTextContent(/UMAP/i);

    fireEvent.click(within(qc).getByText('Quality Control'));
    expect(await screen.findByText('Median genes/cell')).toBeInTheDocument();

    fireEvent.click(within(doublet).getByText('Doublet Detection'));
    expect(await screen.findByText('Mean score')).toBeInTheDocument();

    fireEvent.click(within(batch).getByRole('heading', { name: /Batch Correction \(Harmony\)/ }));
    expect(await screen.findByText('LISI proxy')).toBeInTheDocument();

    fireEvent.click(within(pca).getByText('PCA'));
    expect(await screen.findByText('Variance explained (top 10 PCs)')).toBeInTheDocument();

    fireEvent.click(within(clustering).getByText('Clustering'));
    expect(await screen.findByLabelText(/sort clusters/i)).toBeInTheDocument();

    fireEvent.click(within(norm).getByText('Normalization'));
    expect(await screen.findByText('Target sum')).toBeInTheDocument();

    fireEvent.click(within(hvg).getByText(/Highly variable genes/i));
    expect(await screen.findByText(/Selected.*HVGs from.*total genes/i)).toBeInTheDocument();

    fireEvent.click(within(embed).getByText('Embedding'));
    expect(await screen.findByText('Representation')).toBeInTheDocument();
  });

  it('shows standardized message when pathway preview returns no pathway columns', async () => {
    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (url.includes('/artifacts/path-art-1/preview')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              columns: [],
              rows: [],
              total_rows: 0,
              truncated: false,
              metadata: {},
            }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            run_id: 'run-1',
            status: 'completed',
            step_metrics: {
              pathway_scoring: {
                n_pathways_scored: 50,
                n_cells: 100,
                pathway_database: 'Reactome',
                methods_used: ['wmean'],
                obsm_key: 'pathway_scores',
              },
            },
            software_versions: {},
            artifact_id: null,
            artifact_size_bytes: null,
            download_url: null,
          }),
      } as Response);
    });

    render(<RunResults runId="run-1" mode="details" artifacts={mockArtifacts} />);

    await waitFor(() => {
      expect(screen.getByText(/no previewable rows were returned/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/You can still open the full results artifact/i)).toBeInTheDocument();
  });

  it('shows standardized message when pathway preview fetch fails', async () => {
    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (url.includes('/artifacts/path-art-1/preview')) {
        return Promise.resolve({
          ok: false,
          status: 500,
          text: () => Promise.resolve('err'),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            run_id: 'run-1',
            status: 'completed',
            step_metrics: {
              pathway_scoring: {
                n_pathways_scored: 50,
                n_cells: 100,
                pathway_database: 'Reactome',
                methods_used: ['wmean'],
                obsm_key: 'pathway_scores',
              },
            },
            software_versions: {},
            artifact_id: null,
            artifact_size_bytes: null,
            download_url: null,
          }),
      } as Response);
    });

    render(<RunResults runId="run-1" mode="details" artifacts={mockArtifacts} />);

    await waitFor(() => {
      expect(screen.getByTestId('downstream-preview-failure')).toHaveTextContent(
        /Preview could not be loaded right now/i
      );
    });
    expect(screen.getByText(/You can still open the full results artifact/i)).toBeInTheDocument();
  });
});
