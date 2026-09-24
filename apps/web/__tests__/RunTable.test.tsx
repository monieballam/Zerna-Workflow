import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import RunTable from '@/components/runs/RunTable';
import type { Run } from '@zerna/sdk';

// Mock next/link
vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const refreshMock = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    refresh: refreshMock,
  }),
}));

// Mock WebSocket hook — return initial runs unchanged
vi.mock('@/lib/useRunUpdates', () => ({
  useRunUpdates: (runs: Run[]) => runs,
  useSingleRunUpdates: (run: Run) => run,
}));

const makeRun = (overrides: Partial<Run> = {}): Run => ({
  id: 'run-00000000-0000-0000-0000-000000000001',
  organization_id: 'org-1',
  dataset_version_id: 'dv-1',
  source_dataset_id: 'ds-1',
  source_dataset_version_id: 'dv-1',
  dataset_name: 'PBMC 10k',
  dataset_version_label: 'v1',
  dataset_deleted: false,
  template_id: 'tmpl-1',
  status: 'completed',
  parameters: { resolution: 0.5 },
  software_versions: { scanpy: '1.9.3' },
  random_seed: 42,
  started_at: '2025-01-15T10:00:00Z',
  completed_at: '2025-01-15T10:30:00Z',
  error_message: null,
  created_at: '2025-01-15T09:55:00Z',
  ...overrides,
});

const makeDataset = () => ({
  id: 'ds-1',
  organization_id: 'org-1',
  name: 'PBMC 10k',
  description: null,
  metadata: {},
  created_at: '2025-01-15T10:00:00Z',
  versions: [],
});

describe('RunTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', vi.fn());
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true)
    );
  });

  it('renders empty state when no runs', () => {
    render(<RunTable initialRuns={[]} datasets={[]} />);
    expect(screen.getByText(/no runs found/i)).toBeInTheDocument();
  });

  it('renders run rows with status badges', () => {
    render(
      <RunTable
        initialRuns={[makeRun(), makeRun({ id: 'run-2', status: 'running' })]}
        datasets={[makeDataset()]}
      />
    );
    expect(screen.getByText('completed')).toBeInTheDocument();
    expect(screen.getByText('running')).toBeInTheDocument();
  });

  it('links to run detail page', () => {
    const run = makeRun({ id: 'run-00000000-0000-0000-0000-000000000001' });
    render(<RunTable initialRuns={[run]} datasets={[makeDataset()]} />);
    const links = screen.getAllByRole('link');
    const detailLinks = links.filter((l) => l.getAttribute('href')?.includes('/runs/run-00000000'));
    expect(detailLinks.length).toBeGreaterThan(0);
  });

  it('renders multiple runs', () => {
    const runs = [
      makeRun({ id: 'run-a', status: 'queued' }),
      makeRun({ id: 'run-b', status: 'failed' }),
      makeRun({ id: 'run-c', status: 'cancelled' }),
    ];
    render(<RunTable initialRuns={runs} datasets={[makeDataset()]} />);
    expect(screen.getByText('queued')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.getByText('cancelled')).toBeInTheDocument();
  });

  it('renders cleanup actions', () => {
    render(<RunTable initialRuns={[makeRun({ status: 'failed' })]} datasets={[makeDataset()]} />);
    expect(screen.getByRole('button', { name: /delete selected runs/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /delete failed runs/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /delete all runs/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^delete$/i })).toBeInTheDocument();
  });

  it('deletes a single run through the proxy api', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ run_id: 'run-00000000-0000-0000-0000-000000000001' }),
    } as Response);

    render(<RunTable initialRuns={[makeRun()]} datasets={[makeDataset()]} />);
    fireEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/proxy/v1/runs/run-00000000-0000-0000-0000-000000000001',
        {
          method: 'DELETE',
        }
      );
    });
    expect(refreshMock).toHaveBeenCalled();
  });

  it('scopes cleanup requests to a selected dataset', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ deleted_run_ids: [] }),
    } as Response);

    render(<RunTable initialRuns={[makeRun({ status: 'failed' })]} datasets={[makeDataset()]} />);

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'ds-1' } });
    fireEvent.click(screen.getByRole('button', { name: /delete runs for dataset/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/proxy/v1/runs/cleanup', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
        },
        body: JSON.stringify({ scope: 'all', dataset_id: 'ds-1', run_ids: [] }),
      });
    });
  });

  it('deletes selected runs through the cleanup endpoint', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({ deleted_run_ids: ['run-00000000-0000-0000-0000-000000000001'] }),
    } as Response);

    render(<RunTable initialRuns={[makeRun()]} datasets={[makeDataset()]} />);

    fireEvent.click(
      screen.getByRole('checkbox', {
        name: /select run run-00000000-0000-0000-0000-000000000001/i,
      })
    );
    fireEvent.click(screen.getByRole('button', { name: /delete selected runs/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/proxy/v1/runs/cleanup', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
        },
        body: JSON.stringify({
          scope: 'selected',
          dataset_id: undefined,
          run_ids: ['run-00000000-0000-0000-0000-000000000001'],
        }),
      });
    });
  });
});
