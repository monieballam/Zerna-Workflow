import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import AdminMembersPanel from '@/components/admin/AdminMembersPanel';

const refreshMock = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    refresh: refreshMock,
  }),
}));

const members = [
  {
    user_id: 'user-1',
    email: 'admin@zerna.local',
    role: 'admin' as const,
    joined_at: '2026-04-07T10:00:00Z',
    created_at: '2026-04-07T10:00:00Z',
  },
  {
    user_id: 'user-2',
    email: 'member@example.com',
    role: 'member' as const,
    joined_at: '2026-04-07T11:00:00Z',
    created_at: '2026-04-07T11:00:00Z',
  },
];

describe('AdminMembersPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', vi.fn());
  });

  it('creates a new admin through the proxy api', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    } as Response);

    render(<AdminMembersPanel members={members} />);

    fireEvent.change(screen.getByLabelText(/^email$/i), {
      target: { value: 'new.admin@example.com' },
    });
    fireEvent.change(screen.getByLabelText(/^password$/i), {
      target: { value: 'SuperSecure123!' },
    });
    fireEvent.change(screen.getAllByLabelText(/role/i)[0], {
      target: { value: 'admin' },
    });
    fireEvent.submit(screen.getByRole('button', { name: /save user/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/proxy/v1/admin/members', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          email: 'new.admin@example.com',
          password: 'SuperSecure123!',
          role: 'admin',
        }),
      });
    });
    expect(refreshMock).toHaveBeenCalled();
  });

  it('updates a member role through the proxy api', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    } as Response);

    render(<AdminMembersPanel members={members} />);

    const memberRow = screen.getByText('member@example.com').closest('tr');
    expect(memberRow).not.toBeNull();

    fireEvent.change(within(memberRow as HTMLElement).getByRole('combobox'), {
      target: { value: 'admin' },
    });
    fireEvent.click(screen.getAllByRole('button', { name: /update role/i })[1]);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/proxy/v1/admin/members/user-2', {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ role: 'admin' }),
      });
    });
  });
});
