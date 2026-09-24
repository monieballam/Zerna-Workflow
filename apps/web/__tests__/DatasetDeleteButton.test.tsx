import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import DatasetDeleteButton from '@/components/datasets/DatasetDeleteButton';

const refresh = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    refresh,
  }),
}));

describe('DatasetDeleteButton', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    refresh.mockReset();
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [],
          total: 0,
          page: 1,
          page_size: 1000,
          total_pages: 0,
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }
      )
    ) as typeof fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('loads associated runs from the dataset-scoped endpoint', async () => {
    render(<DatasetDeleteButton datasetId="ds-123" datasetName="PBMC" />);

    fireEvent.click(screen.getByRole('button', { name: /delete/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/proxy/v1/datasets/ds-123/runs?page=1&page_size=1000'
      );
    });
  });
});
