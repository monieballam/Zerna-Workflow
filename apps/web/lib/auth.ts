import { cookies, headers } from 'next/headers';

const TOKEN_COOKIE = 'zerna_token';
const REFRESH_COOKIE = 'zerna_refresh_token';

function parseBooleanEnv(value: string | undefined): boolean | undefined {
  if (!value) return undefined;
  const normalized = value.trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(normalized)) return true;
  if (['0', 'false', 'no', 'off'].includes(normalized)) return false;
  return undefined;
}

function extractSchemeFromUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    return new URL(value).protocol.replace(':', '').toLowerCase();
  } catch {
    return null;
  }
}

export function shouldUseSecureCookies(): boolean {
  const forced = parseBooleanEnv(process.env.AUTH_COOKIE_SECURE);
  if (forced !== undefined) return forced;

  const headerStore = headers();
  const forwardedProto = headerStore.get('x-forwarded-proto')?.split(',')[0]?.trim().toLowerCase();
  if (forwardedProto) {
    return forwardedProto === 'https';
  }

  const forwardedProtocol = headerStore.get('x-forwarded-protocol')?.trim().toLowerCase();
  if (forwardedProtocol) {
    return forwardedProtocol === 'https';
  }

  const forwardedSsl = headerStore.get('x-forwarded-ssl')?.trim().toLowerCase();
  if (forwardedSsl) {
    return forwardedSsl === 'on';
  }

  const originScheme =
    extractSchemeFromUrl(headerStore.get('origin')) ??
    extractSchemeFromUrl(headerStore.get('referer'));
  if (originScheme) {
    return originScheme === 'https';
  }

  return false;
}

function baseCookieOptions() {
  return {
    httpOnly: true,
    secure: shouldUseSecureCookies(),
    sameSite: 'lax' as const,
    path: '/',
  };
}

/** Set the access token in an httpOnly cookie (server-side only). */
export function setAuthToken(token: string): void {
  const cookieStore = cookies();
  cookieStore.set(TOKEN_COOKIE, token, {
    ...baseCookieOptions(),
    maxAge: 60 * 60 * 24 * 7, // 7 days
  });
}

/** Set the refresh token in an httpOnly cookie (server-side only). */
export function setRefreshToken(token: string): void {
  const cookieStore = cookies();
  cookieStore.set(REFRESH_COOKIE, token, {
    ...baseCookieOptions(),
    maxAge: 60 * 60 * 24 * 30, // 30 days
  });
}

/** Read the access token from cookies (server-side only). */
export function getAuthToken(): string | undefined {
  const cookieStore = cookies();
  return cookieStore.get(TOKEN_COOKIE)?.value;
}

/** Read the refresh token from cookies (server-side only). */
export function getRefreshToken(): string | undefined {
  const cookieStore = cookies();
  return cookieStore.get(REFRESH_COOKIE)?.value;
}

/** Clear both auth cookies (server-side only). */
export function clearAuthCookies(): void {
  const cookieStore = cookies();
  cookieStore.delete(TOKEN_COOKIE);
  cookieStore.delete(REFRESH_COOKIE);
}
