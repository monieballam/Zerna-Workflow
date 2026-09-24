import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createHmac } from 'node:crypto';

const getAuthToken = vi.fn();
const authMe = vi.fn();
const createServerClient = vi.fn(() => ({
  auth: {
    me: authMe,
  },
}));
const redirect = vi.fn((path: string) => {
  throw new Error(`REDIRECT:${path}`);
});

vi.mock('@/lib/auth', () => ({
  getAuthToken,
}));

vi.mock('@/lib/api', () => ({
  createServerClient,
}));

vi.mock('next/navigation', () => ({
  redirect,
}));

function base64UrlEncodeJson(value: unknown): string {
  return Buffer.from(JSON.stringify(value)).toString('base64url');
}

function makeHs256AccessToken(
  overrides?: Partial<{ sub: string; email: string; exp: number }>
): string {
  const header = base64UrlEncodeJson({ alg: 'HS256', typ: 'JWT' });
  const payload = base64UrlEncodeJson({
    sub: 'user-1',
    email: 'user@example.com',
    exp: Math.floor(Date.now() / 1000) + 3600,
    iat: Math.floor(Date.now() / 1000),
    type: 'access',
    ...overrides,
  });
  const secret = process.env.JWT_SECRET_KEY ?? 'test-secret';
  const signature = createHmac('sha256', secret).update(`${header}.${payload}`).digest('base64url');
  return `${header}.${payload}.${signature}`;
}

describe('requireAuthenticatedUser', () => {
  beforeEach(() => {
    vi.resetModules();
    getAuthToken.mockReset();
    authMe.mockReset();
    createServerClient.mockClear();
    redirect.mockClear();
    process.env.JWT_ALGORITHM = '';
    process.env.JWT_SECRET_KEY = 'test-secret';
  });

  it('redirects to login when there is no auth token', async () => {
    getAuthToken.mockReturnValue(undefined);
    const { requireAuthenticatedUser } = await import('@/lib/require-auth');

    await expect(requireAuthenticatedUser()).rejects.toThrow('REDIRECT:/login');
    expect(createServerClient).not.toHaveBeenCalled();
  });

  it('redirects to login when the token is stale or unauthorized', async () => {
    getAuthToken.mockReturnValue('stale-token');
    authMe.mockRejectedValue(new Error('Zerna API error 401'));
    const { requireAuthenticatedUser } = await import('@/lib/require-auth');

    await expect(requireAuthenticatedUser()).rejects.toThrow('REDIRECT:/login');
    expect(createServerClient).toHaveBeenCalledTimes(1);
  });

  it('returns the user profile when the session is valid', async () => {
    const user = {
      id: 'user-1',
      email: 'user@example.com',
      created_at: '2026-03-19T00:00:00Z',
    };
    getAuthToken.mockReturnValue('valid-token');
    authMe.mockResolvedValue(user);
    const { requireAuthenticatedUser } = await import('@/lib/require-auth');

    await expect(requireAuthenticatedUser()).resolves.toEqual(user);
    expect(redirect).not.toHaveBeenCalled();
  });

  it('accepts a locally verifiable HS256 token without calling auth.me', async () => {
    getAuthToken.mockReturnValue(makeHs256AccessToken());
    process.env.JWT_ALGORITHM = 'HS256';
    const { requireAuthenticatedSession } = await import('@/lib/require-auth');

    await expect(requireAuthenticatedSession()).resolves.toBeUndefined();
    expect(createServerClient).not.toHaveBeenCalled();
  });

  it('redirects to login for an expired locally verified token', async () => {
    getAuthToken.mockReturnValue(makeHs256AccessToken({ exp: Math.floor(Date.now() / 1000) - 60 }));
    process.env.JWT_ALGORITHM = 'HS256';
    const { requireAuthenticatedSession } = await import('@/lib/require-auth');

    await expect(requireAuthenticatedSession()).rejects.toThrow('REDIRECT:/login');
    expect(createServerClient).not.toHaveBeenCalled();
  });

  it('falls back to auth.me when local verification is unsupported', async () => {
    getAuthToken.mockReturnValue('opaque-token');
    process.env.JWT_ALGORITHM = 'RS256';
    authMe.mockResolvedValue({
      id: 'user-1',
      email: 'user@example.com',
      created_at: '2026-03-19T00:00:00Z',
    });
    const { requireAuthenticatedSession } = await import('@/lib/require-auth');

    await expect(requireAuthenticatedSession()).resolves.toBeUndefined();
    expect(createServerClient).toHaveBeenCalledTimes(1);
  });
});
