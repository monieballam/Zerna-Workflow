import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import FeedbackForm from '@/components/feedback/FeedbackForm';

const refreshMock = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    refresh: refreshMock,
  }),
}));

describe('FeedbackForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', vi.fn());
  });

  it('requires a run selection for run-scoped feedback', async () => {
    render(<FeedbackForm runs={[]} />);

    fireEvent.change(screen.getByLabelText(/feedback scope/i), { target: { value: 'run' } });
    fireEvent.change(screen.getByLabelText(/details/i), { target: { value: 'Needs review.' } });
    fireEvent.submit(screen.getByRole('button', { name: /submit feedback/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/choose a run/i);
    });
  });

  it('posts run-scoped feedback through the proxy api', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ id: 'fb-1' }),
    } as Response);

    render(
      <FeedbackForm
        runs={[{ id: 'run-1', status: 'completed', datasetName: 'PBMC', createdAt: '2026-04-07' }]}
        defaultRunId="run-1"
      />
    );

    fireEvent.change(screen.getByLabelText(/category/i), { target: { value: 'science' } });
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Subtype issue' } });
    fireEvent.change(screen.getByLabelText(/details/i), {
      target: { value: 'Fine labels look off.' },
    });
    fireEvent.submit(screen.getByRole('button', { name: /submit feedback/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/proxy/v1/feedback', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          scope: 'run',
          category: 'science',
          run_id: 'run-1',
          title: 'Subtype issue',
          message: 'Fine labels look off.',
        }),
      });
    });
    expect(refreshMock).toHaveBeenCalled();
  });
});
