import { createHmac, timingSafeEqual } from 'node:crypto';
import type { UserProfile } from '@zerna/sdk';
import { redirect } from 'next/navigation';
import { cache } from 'react';
import { createServerClient } from './api';
import { getAuthToken } from './auth';
import { isAuthDisabled } from './auth-mode';

function isAuthFailure(error: unknown): boolean {
  const message = error instanceof Error ? error.message : typeof error === 'string' ? error : '';
  return message.includes('401') || message.includes('403');
}

type LocalTokenValidation = 'valid' | 'invalid' | 'unsupported';

function decodeBase64UrlJson<T>(value: string): T | null {
  try {
    return JSON.parse(Buffer.from(value, 'base64url').toString('utf-8')) as T;
  } catch {
    return null;
  }
}

function verifyHs256Token(token: string, secret: string): LocalTokenValidation {
  const parts = token.split('.');
  if (parts.length !== 3) return 'invalid';

  const [encodedHeader, encodedPayload, encodedSignature] = parts;
  const header = decodeBase64UrlJson<{ alg?: string; typ?: string }>(encodedHeader);
  const payload = decodeBase64UrlJson<{
    sub?: string;
    email?: string;
    exp?: number;
    type?: string;
  }>(encodedPayload);

  if (!header || !payload || header.alg !== 'HS256' || payload.type !== 'access') {
    return 'invalid';
  }

  const expectedSignature = createHmac('sha256', secret)
    .update(`${encodedHeader}.${encodedPayload}`)
    .digest();

  let providedSignature: Buffer;
  try {
    providedSignature = Buffer.from(encodedSignature, 'base64url');
  } catch {
    return 'invalid';
  }

  if (
    expectedSignature.length !== providedSignature.length ||
    !timingSafeEqual(expectedSignature, providedSignature)
  ) {
    return 'invalid';
  }

  if (
    typeof payload.sub !== 'string' ||
    typeof payload.email !== 'string' ||
    typeof payload.exp !== 'number' ||
    payload.exp <= Math.floor(Date.now() / 1000)
  ) {
    return 'invalid';
  }

  return 'valid';
}

function validateAccessTokenLocally(token: string): LocalTokenValidation {
  const algorithm = (process.env.JWT_ALGORITHM ?? '').trim().toUpperCase();
  const secret = process.env.JWT_SECRET_KEY?.trim();

  if (algorithm !== 'HS256' || !secret) {
    return 'unsupported';
  }

  return verifyHs256Token(token, secret);
}

const fetchAuthenticatedUser = cache(async (): Promise<UserProfile> => {
  return createServerClient().auth.me();
});

export async function requireAuthenticatedSession(): Promise<void> {
  if (isAuthDisabled()) {
    return;
  }

  const token = getAuthToken();
  if (!token) {
    redirect('/login');
  }

  const localValidation = validateAccessTokenLocally(token);
  if (localValidation === 'valid') {
    return;
  }
  if (localValidation === 'invalid') {
    redirect('/login');
  }

  try {
    await fetchAuthenticatedUser();
  } catch (error) {
    if (isAuthFailure(error)) {
      redirect('/login');
    }
    throw error;
  }
}

export async function requireAuthenticatedUser(): Promise<UserProfile> {
  if (isAuthDisabled()) {
    return fetchAuthenticatedUser();
  }

  if (!getAuthToken()) {
    redirect('/login');
  }

  try {
    const user = await fetchAuthenticatedUser();
    return user;
  } catch (error) {
    if (isAuthFailure(error)) {
      redirect('/login');
    }
    throw error;
  }
}
