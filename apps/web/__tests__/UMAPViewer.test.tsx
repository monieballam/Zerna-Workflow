import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import UMAPViewer from '@/components/runs/UMAPViewer';

describe('UMAPViewer', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          embedding_key: 'X_tsne',
          cells: [
            { id: 'cell-1', x: 0.1, y: 0.2 },
            { id: 'cell-2', x: -0.4, y: 0.3 },
          ],
          metadata: [
            { cellId: 'cell-1', cluster: '0', cellType: 'T cell' },
            { cellId: 'cell-2', cluster: '1', cellType: 'B cell' },
          ],
          cluster_labels: {
            '0': 'T cell',
            '1': 'B cell',
          },
          bounds: { minX: -0.4, maxX: 0.1, minY: 0.2, maxY: 0.3 },
          available_fields: ['cluster', 'cellType'],
          total_cells: 2,
          sampled: false,
        }),
    } as Response);

    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
      () =>
        ({
          scale: vi.fn(),
          fillRect: vi.fn(),
          beginPath: vi.fn(),
          arc: vi.fn(),
          fill: vi.fn(),
          save: vi.fn(),
          translate: vi.fn(),
          rotate: vi.fn(),
          restore: vi.fn(),
          fillText: vi.fn(),
          globalAlpha: 1,
          fillStyle: '#000',
          font: '12px sans-serif',
          textAlign: 'left',
        }) as unknown as CanvasRenderingContext2D
    );
  });

  it('renders saved snapshot copy and t-SNE kind when the embedding response uses X_tsne', async () => {
    render(<UMAPViewer runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByText('Saved Embedding Snapshot')).toBeInTheDocument();
    });

    expect(screen.getByText(/Static t-SNE preview/i)).toBeInTheDocument();
    expect(screen.getByTestId('results-embedding-snapshot-collapsed-summary')).toHaveTextContent(
      /2 cells/
    );
    expect(screen.getByText('Cluster 0 · T cell')).toBeInTheDocument();
    expect(screen.getByText('Cluster 1 · B cell')).toBeInTheDocument();
  });
});
