import { cookies } from 'next/headers';
import { ZernaClient } from '@zerna/sdk';
import {
  getAuthToken,
  getRefreshToken,
  setAuthToken,
  setRefreshToken,
  shouldUseSecureCookies,
} from './auth';
import { isAuthDisabled } from './auth-mode';

const SERVER_API_BASE_URL =
  process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

/** Read JWT ``exp`` (seconds since epoch); null if missing or unparsable. */
function jwtExpSeconds(accessToken: string): number | null {
  try {
    const part = accessToken.split('.')[1];
    if (!part) return null;
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/');
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
    let jsonStr: string;
    if (typeof Buffer !== 'undefined') {
      jsonStr = Buffer.from(padded, 'base64').toString('utf8');
    } else if (typeof atob === 'function') {
      jsonStr = atob(padded);
    } else {
      return null;
    }
    const json = JSON.parse(jsonStr) as { exp?: unknown };
    return typeof json.exp === 'number' ? json.exp : null;
  } catch {
    return null;
  }
}

function syncPublicAccessCookie(accessToken: string): void {
  const cookieStore = cookies();
  cookieStore.set('zerna_token_pub', accessToken, {
    httpOnly: false,
    secure: shouldUseSecureCookies(),
    sameSite: 'lax',
    path: '/',
    maxAge: 60 * 60 * 24 * 7,
  });
}

/**
 * Returns an API client with a usable access token. Refreshes using the httpOnly
 * refresh cookie when the access token is missing or expires within ``slackSeconds``.
 *
 * Prevents "Invalid or expired token" on long-lived upload pages (e.g. large folder picks).
 */
export async function getAuthenticatedApiClientForServerAction(
  slackSeconds: number = 120
): Promise<{ client: ZernaClient } | { error: string }> {
  if (isAuthDisabled()) {
    return {
      client: new ZernaClient({
        baseUrl: SERVER_API_BASE_URL,
      }),
    };
  }

  const access = getAuthToken();
  const refresh = getRefreshToken();

  if (!access && !refresh) {
    return { error: 'You are not signed in. Please log in and try again.' };
  }

  const exp = access ? jwtExpSeconds(access) : null;
  const nowMs = Date.now();
  const slackMs = slackSeconds * 1000;
  const needsRefresh =
    Boolean(refresh) && (!access || (exp !== null && exp * 1000 < nowMs + slackMs));

  if (needsRefresh) {
    const client = new ZernaClient({
      baseUrl: SERVER_API_BASE_URL,
      accessToken: access,
      refreshToken: refresh,
    });
    try {
      const r = await client.auth.refresh();
      setAuthToken(r.access_token);
      setRefreshToken(r.refresh_token);
      syncPublicAccessCookie(r.access_token);
      return {
        client: new ZernaClient({
          baseUrl: SERVER_API_BASE_URL,
          accessToken: r.access_token,
          refreshToken: r.refresh_token,
        }),
      };
    } catch {
      return {
        error: 'Your session expired. Please log in again, then retry the upload.',
      };
    }
  }

  if (!access) {
    return { error: 'You are not signed in. Please log in and try again.' };
  }

  return {
    client: new ZernaClient({
      baseUrl: SERVER_API_BASE_URL,
      accessToken: access,
      refreshToken: refresh ?? undefined,
    }),
  };
}
