import { ZernaClient } from '@zerna/sdk';
import { getAuthToken, getRefreshToken } from './auth';

const SERVER_API_BASE_URL =
  process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

function getBrowserApiBaseUrl(): string {
  if (typeof window !== 'undefined') {
    return window.location.origin;
  }
  return process.env.NEXT_PUBLIC_API_URL ?? 'https://localhost:8000';
}

/**
 * Create a server-side ZernaClient instance with the token from cookies.
 * Use this in Server Components and Server Actions.
 */
export function createServerClient(): ZernaClient {
  const token = getAuthToken();
  const refresh = getRefreshToken();
  return new ZernaClient({
    baseUrl: SERVER_API_BASE_URL,
    accessToken: token,
    refreshToken: refresh,
  });
}

/**
 * Client-side singleton. The token is injected at login time via a
 * non-httpOnly cookie so the browser JS can read it.
 *
 * Only import this in Client Components ("use client").
 */
let _clientInstance: ZernaClient | null = null;

export function getClientSideClient(): ZernaClient {
  if (!_clientInstance) {
    // Read the public token cookie (set alongside the httpOnly one at login)
    const token =
      typeof document !== 'undefined'
        ? document.cookie
            .split('; ')
            .find((row) => row.startsWith('zerna_token_pub='))
            ?.split('=')[1]
        : undefined;

    _clientInstance = new ZernaClient({
      baseUrl: getBrowserApiBaseUrl(),
      accessToken: token,
    });
  }
  return _clientInstance;
}

/** Reset the client-side singleton (call after logout). */
export function resetClientSideClient(): void {
  _clientInstance = null;
}
