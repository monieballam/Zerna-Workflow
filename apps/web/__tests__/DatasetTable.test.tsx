import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import DatasetTable from '@/components/datasets/DatasetTable';
import type { Dataset } from '@zerna/sdk';

// next/link renders as <a> in tests
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

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    refresh: vi.fn(),
  }),
}));

const makeDataset = (overrides: Partial<Dataset> = {}): Dataset => ({
  id: 'ds-1',
  organization_id: 'org-1',
  name: 'PBMC 10k',
  description: null,
  metadata: {},
  created_at: '2025-01-15T10:00:00Z',
  versions: [
    {
      id: 'v-1',
      version: '1',
      s3_path: 's3://bucket/ds-1/v1',
      cell_count: 10000,
      gene_count: 33538,
      file_format: 'h5ad',
      created_at: '2025-01-15T10:00:00Z',
    },
  ],
  ...overrides,
});

describe('DatasetTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', vi.fn());
  });

  it('renders dataset name and stats', () => {
    render(<DatasetTable datasets={[makeDataset()]} sortBy="created_at" sortOrder="desc" />);

    expect(screen.getByText('PBMC 10k')).toBeInTheDocument();
    expect(screen.getByText('10,000')).toBeInTheDocument();
    expect(screen.getByText('33,538')).toBeInTheDocument();
  });

  it('renders empty state when no datasets', () => {
    render(<DatasetTable datasets={[]} sortBy="created_at" sortOrder="desc" />);

    expect(screen.getByText(/no datasets found/i)).toBeInTheDocument();
  });

  it('renders multiple datasets', () => {
    const datasets = [
      makeDataset({ id: 'ds-1', name: 'Dataset A' }),
      makeDataset({ id: 'ds-2', name: 'Dataset B' }),
    ];

    render(<DatasetTable datasets={datasets} sortBy="name" sortOrder="asc" />);

    expect(screen.getByText('Dataset A')).toBeInTheDocument();
    expect(screen.getByText('Dataset B')).toBeInTheDocument();
  });

  it('links to dataset detail page', () => {
    render(
      <DatasetTable
        datasets={[makeDataset({ id: 'ds-abc' })]}
        sortBy="created_at"
        sortOrder="desc"
      />
    );

    const links = screen.getAllByRole('link', { name: /PBMC 10k/i });
    expect(links[0]).toHaveAttribute('href', '/datasets/ds-abc');
  });

  it('renders dataset delete action', () => {
    render(<DatasetTable datasets={[makeDataset()]} sortBy="created_at" sortOrder="desc" />);
    expect(screen.getByRole('button', { name: /^delete$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /delete selected datasets/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /delete all datasets/i })).toBeInTheDocument();
  });

  it('shows dash for missing cell/gene counts', () => {
    const ds = makeDataset({
      versions: [
        {
          id: 'v-1',
          version: '1',
          s3_path: 's3://bucket/ds-1/v1',
          cell_count: null,
          gene_count: null,
          file_format: null,
          created_at: '2025-01-15T10:00:00Z',
        },
      ],
    });

    render(<DatasetTable datasets={[ds]} sortBy="created_at" sortOrder="desc" />);

    // Two dashes for cell_count and gene_count
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThanOrEqual(2);
  });

  it('renders sort links for column headers', () => {
    render(<DatasetTable datasets={[makeDataset()]} sortBy="name" sortOrder="asc" />);

    const nameLink = screen.getByRole('link', { name: /name/i });
    // Clicking name again (currently asc) should produce desc
    expect(nameLink).toHaveAttribute('href', expect.stringContaining('sort_by=name'));
    expect(nameLink).toHaveAttribute('href', expect.stringContaining('sort_order=desc'));
  });

  it('bulk deletes selected datasets through the proxy api', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ deleted_dataset_ids: ['ds-1'] }),
    } as Response);

    render(
      <DatasetTable
        datasets={[
          makeDataset({ id: 'ds-1', name: 'Dataset A' }),
          makeDataset({ id: 'ds-2', name: 'Dataset B' }),
        ]}
        sortBy="created_at"
        sortOrder="desc"
      />
    );

    fireEvent.click(screen.getByRole('checkbox', { name: /select dataset dataset a/i }));
    fireEvent.click(screen.getByRole('button', { name: /delete selected datasets/i }));
    fireEvent.click(screen.getByRole('button', { name: /delete datasets/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/proxy/v1/datasets/bulk-delete', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
        },
        body: JSON.stringify({
          scope: 'selected',
          dataset_ids: ['ds-1'],
          run_delete_mode: 'preserve',
        }),
      });
    });
  });
});
