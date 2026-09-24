import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import RunDetail from '@/components/runs/RunDetail';
import type { Run, Artifact } from '@zerna/sdk';

vi.mock('@/lib/useRunUpdates', () => ({
  useRunUpdates: (runs: Run[]) => runs,
  useSingleRunUpdates: (run: Run) => run,
}));

vi.mock('@/lib/run-actions', () => ({
  cancelRunAction: vi.fn().mockResolvedValue({}),
}));

const makeRun = (overrides: Partial<Run> = {}): Run => ({
  id: 'run-abc',
  organization_id: 'org-1',
  dataset_version_id: 'dv-1',
  source_dataset_id: 'ds-1',
  source_dataset_version_id: 'dv-1',
  dataset_name: 'PBMC 10k',
  dataset_version_label: 'v1',
  dataset_deleted: false,
  template_id: 'tmpl-1',
  status: 'completed',
  parameters: { resolution: 0.5, clustering_method: 'leiden', n_components: 50 },
  software_versions: { scanpy: '1.9.3', 'scvi-tools': '0.20.0' },
  random_seed: 42,
  started_at: '2025-01-15T10:00:00Z',
  completed_at: '2025-01-15T10:30:00Z',
  error_message: null,
  created_at: '2025-01-15T09:55:00Z',
  ...overrides,
});

const makeArtifact = (overrides: Partial<Artifact> = {}): Artifact => ({
  id: 'art-1',
  run_id: 'run-abc',
  artifact_type: 'h5ad',
  s3_path: 's3://bucket/run-abc/output.h5ad',
  size_bytes: 1024 * 1024 * 50,
  metadata: {},
  download_url: 'https://s3.example.com/presigned-url',
  created_at: '2025-01-15T10:30:00Z',
  ...overrides,
});

describe('RunDetail', () => {
  it('renders run status badge', () => {
    render(<RunDetail initialRun={makeRun()} artifacts={[]} />);
    expect(screen.getByText('completed')).toBeInTheDocument();
  });

  it('renders pipeline steps at the top when progress is available', () => {
    render(
      <RunDetail
        initialRun={makeRun({
          parameters: {
            resolution: 0.5,
            clustering_method: 'leiden',
            n_components: 50,
            progress: {
              total_steps: 12,
              progress_percent: 100,
              completed_steps: [
                'qc_filter',
                'doublet_detection',
                'normalize',
                'select_hvg',
                'run_pca',
                'batch_correction_harmony',
                'cluster',
                'embed',
                'annotate',
                'differential_expression',
                'pathway_scoring',
                'ligand_receptor_analysis',
              ],
              step_summaries: [
                {
                  step_name: 'qc_filter',
                  label: 'QC & Filtering',
                  status: 'completed',
                  summary: 'Retained 9,500/10,000 cells after QC.',
                },
              ],
            },
          },
        })}
        artifacts={[]}
      />
    );
    expect(screen.getByText('Pipeline steps')).toBeInTheDocument();
    expect(screen.getByText('12 of 12 steps finished')).toBeInTheDocument();
    expect(screen.getByText('Stage overview')).toBeInTheDocument();
    expect(screen.getByTestId('stage-overview-qc')).toHaveTextContent('Quality Control');
  });

  it('renders grouped pipeline configuration', () => {
    render(<RunDetail initialRun={makeRun()} artifacts={[]} />);
    expect(screen.getByText('Pipeline configuration')).toBeInTheDocument();
    expect(screen.getByText('Clustering & Embedding')).toBeInTheDocument();
    expect(screen.getByText('Clustering resolution')).toBeInTheDocument();
    expect(screen.getByText('0.5')).toBeInTheDocument();
    expect(screen.queryByText('Parameters')).not.toBeInTheDocument();
  });

  it('renders live execution progress merged with stage settings', () => {
    render(
      <RunDetail
        initialRun={makeRun({
          status: 'running',
          parameters: {
            resolution: 0.5,
            min_genes: 200,
            progress: {
              current_step: 'normalize',
              current_step_label: 'Normalization',
              current_step_started_at: '2025-01-15T10:05:00Z',
              total_steps: 4,
              progress_percent: 50,
              completed_steps: ['qc_filter', 'doublet_detection'],
              updated_at: '2025-01-15T10:06:00Z',
              step_summaries: [
                {
                  step_name: 'qc_filter',
                  label: 'QC & Filtering',
                  status: 'completed',
                  summary: 'Retained 9,500/10,000 cells after QC.',
                  started_at: '2025-01-15T10:00:00Z',
                  completed_at: '2025-01-15T10:02:00Z',
                  duration_seconds: 120,
                },
              ],
            },
          },
        })}
        artifacts={[]}
      />
    );

    expect(screen.getByText('Pipeline steps')).toBeInTheDocument();
    expect(screen.getByText('Currently running')).toBeInTheDocument();
    expect(screen.getByText('Normalization')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Quality Control' })).toBeInTheDocument();
    expect(screen.getByText('Min genes per cell')).toBeInTheDocument();
    expect(screen.getByText('Retained 9,500/10,000 cells after QC.')).toBeInTheDocument();
    expect(screen.getByText('50%')).toBeInTheDocument();
    expect(screen.getByTestId('stage-overview-qc')).toHaveAttribute(
      'aria-label',
      'Quality Control: done'
    );
  });

  it('allows collapsing and expanding the execution progress area', () => {
    render(
      <RunDetail
        initialRun={makeRun({
          status: 'running',
          parameters: {
            progress: {
              current_step: 'normalize',
              current_step_label: 'Normalization',
              total_steps: 4,
              progress_percent: 50,
              completed_steps: ['qc_filter'],
              step_summaries: [
                {
                  step_name: 'qc_filter',
                  label: 'QC & Filtering',
                  status: 'completed',
                  summary: 'Retained 9,500/10,000 cells after QC.',
                  started_at: '2025-01-15T10:00:00Z',
                  completed_at: '2025-01-15T10:02:00Z',
                  duration_seconds: 120,
                },
              ],
            },
          },
        })}
        artifacts={[]}
      />
    );

    const toggle = screen.getByRole('button', { name: 'Collapse' });
    expect(screen.getByText('Currently running')).toBeInTheDocument();

    fireEvent.click(toggle);

    expect(screen.queryByText('Currently running')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Expand' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Expand' }));
    expect(screen.getByText('Currently running')).toBeInTheDocument();
  });

  it('allows expanding and collapsing individual progress steps', () => {
    render(
      <RunDetail
        initialRun={makeRun({
          status: 'running',
          parameters: {
            progress: {
              total_steps: 2,
              progress_percent: 50,
              completed_steps: ['qc_filter'],
              step_summaries: [
                {
                  step_name: 'qc_filter',
                  label: 'QC & Filtering',
                  status: 'completed',
                  summary: 'Retained 9,500/10,000 cells after QC.',
                  started_at: '2025-01-15T10:00:00Z',
                  completed_at: '2025-01-15T10:02:00Z',
                  duration_seconds: 120,
                },
              ],
            },
          },
        })}
        artifacts={[]}
      />
    );

    expect(screen.queryByText(/Started Jan/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Show details' }));

    expect(screen.getByText(/Started Jan/i)).toBeInTheDocument();
    expect(screen.getByText(/Duration 120.0s/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Hide details' }));
    expect(screen.queryByText(/Duration 120.0s/i)).not.toBeInTheDocument();
  });

  it('renders software versions', () => {
    render(<RunDetail initialRun={makeRun()} artifacts={[]} />);
    expect(screen.getByText('scanpy')).toBeInTheDocument();
    expect(screen.getByText('1.9.3')).toBeInTheDocument();
  });

  it('links completed runs to the explorer workspace', () => {
    render(<RunDetail initialRun={makeRun()} artifacts={[makeArtifact()]} />);
    const exploreLinks = screen.getAllByRole('link', { name: /explore/i });
    expect(exploreLinks.some((link) => link.getAttribute('href') === '/runs/run-abc/explore')).toBe(
      true
    );
  });

  it('links to feedback scoped to the current run', () => {
    render(<RunDetail initialRun={makeRun()} artifacts={[]} />);
    expect(screen.getByRole('link', { name: /send feedback/i })).toHaveAttribute(
      'href',
      '/feedback?runId=run-abc'
    );
  });

  it('does not render explorer artifact messaging for running runs', () => {
    render(<RunDetail initialRun={makeRun({ status: 'running' })} artifacts={[]} />);
    expect(screen.queryByText(/completed run outputs/i)).not.toBeInTheDocument();
  });

  it('shows cancel button for running runs', () => {
    render(<RunDetail initialRun={makeRun({ status: 'running' })} artifacts={[]} />);
    expect(screen.getByRole('button', { name: /cancel run/i })).toBeInTheDocument();
  });

  it('does not show cancel button for completed runs', () => {
    render(<RunDetail initialRun={makeRun({ status: 'completed' })} artifacts={[]} />);
    expect(screen.queryByRole('button', { name: /cancel run/i })).not.toBeInTheDocument();
  });

  it('shows error message for failed runs', () => {
    render(
      <RunDetail
        initialRun={makeRun({
          status: 'failed',
          error_message: 'Method QCFilter failed: ValueError: no cells passed filter',
        })}
        artifacts={[]}
      />
    );
    expect(screen.getByText(/run failed/i)).toBeInTheDocument();
    expect(screen.getByText(/no cells passed filter/i)).toBeInTheDocument();
  });

  it('renders random seed when present', () => {
    render(<RunDetail initialRun={makeRun({ random_seed: 42 })} artifacts={[]} />);
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('summarizes artifact availability in the completed outputs card', () => {
    const artifacts = [makeArtifact({ id: 'a1', artifact_type: 'h5ad' })];
    render(<RunDetail initialRun={makeRun()} artifacts={artifacts} />);
    expect(screen.getByText(/1 persisted artifact is available there/i)).toBeInTheDocument();
  });
});
