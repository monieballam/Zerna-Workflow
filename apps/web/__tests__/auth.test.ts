import { beforeEach, describe, expect, it, vi } from 'vitest';

const cookieStore = {
  set: vi.fn(),
  get: vi.fn(),
  delete: vi.fn(),
};

const headerStore = {
  get: vi.fn(),
};

vi.mock('next/headers', () => ({
  cookies: () => cookieStore,
  headers: () => headerStore,
}));

describe('auth cookie security', () => {
  beforeEach(() => {
    vi.resetModules();
    cookieStore.set.mockReset();
    cookieStore.get.mockReset();
    cookieStore.delete.mockReset();
    headerStore.get.mockReset();
    delete process.env.AUTH_COOKIE_SECURE;
  });

  it('disables secure cookies on plain http when no override is set', async () => {
    headerStore.get.mockImplementation((name: string) => {
      if (name === 'x-forwarded-proto') return 'http';
      return null;
    });

    const { setAuthToken } = await import('@/lib/auth');
    setAuthToken('token-http');

    expect(cookieStore.set).toHaveBeenCalledWith(
      'zerna_token',
      'token-http',
      expect.objectContaining({ secure: false })
    );
  });

  it('enables secure cookies when the forwarded scheme is https', async () => {
    headerStore.get.mockImplementation((name: string) => {
      if (name === 'x-forwarded-proto') return 'https';
      return null;
    });

    const { shouldUseSecureCookies } = await import('@/lib/auth');
    expect(shouldUseSecureCookies()).toBe(true);
  });

  it('honors explicit AUTH_COOKIE_SECURE overrides', async () => {
    process.env.AUTH_COOKIE_SECURE = 'true';
    headerStore.get.mockReturnValue('http');

    const { shouldUseSecureCookies } = await import('@/lib/auth');
    expect(shouldUseSecureCookies()).toBe(true);
  });
});
