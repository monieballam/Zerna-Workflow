'use server';

import { redirect } from 'next/navigation';
import { ApiResponseError, ZernaClient } from '@zerna/sdk';
import { setAuthToken, setRefreshToken, clearAuthCookies, shouldUseSecureCookies } from './auth';
import { cookies } from 'next/headers';

const API_BASE_URL =
  process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const LOCAL_INFRA_DOWN_MESSAGE =
  'PostgreSQL or Redis is not running. Start Docker Desktop, then from the repo run `./scripts/setup-dev-env.sh` or `docker compose up -d`, then `uv run --directory apps/api alembic upgrade head`, and restart the API.';

function messageFromApiErrorBody(body: unknown): string | undefined {
  if (body && typeof body === 'object' && 'message' in body) {
    const m = (body as { message: unknown }).message;
    return typeof m === 'string' ? m : undefined;
  }
  return undefined;
}

export interface LoginState {
  error?: string;
}

export interface SignupState {
  error?: string;
}

/**
 * Server action: authenticate the user and store tokens in httpOnly cookies.
 */
export async function loginAction(_prevState: LoginState, formData: FormData): Promise<LoginState> {
  const email = formData.get('email') as string;
  const password = formData.get('password') as string;

  if (!email || !password) {
    return { error: 'Email and password are required.' };
  }

  try {
    const client = new ZernaClient({ baseUrl: API_BASE_URL });
    const response = await client.auth.login({ email, password });

    setAuthToken(response.access_token);
    setRefreshToken(response.refresh_token);

    // Also set a non-httpOnly cookie for client-side SDK usage
    const cookieStore = cookies();
    cookieStore.set('zerna_token_pub', response.access_token, {
      httpOnly: false,
      secure: shouldUseSecureCookies(),
      sameSite: 'lax',
      path: '/',
      maxAge: 60 * 60 * 24 * 7,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Login failed. Please try again.';
    const normalized = message.toLowerCase();
    if (
      normalized.includes('fetch failed') ||
      normalized.includes('networkerror') ||
      normalized.includes('econnrefused')
    ) {
      return {
        error: `Cannot reach the Zerna API at ${API_BASE_URL}. Make sure the API server is running.`,
      };
    }
    if (message.includes('401') || message.includes('403')) {
      return { error: 'Invalid email or password.' };
    }
    if (message.includes('429')) {
      return {
        error:
          'Too many login attempts. Wait a few minutes, or ask your admin to clear Redis keys auth_lockout:* / auth_attempts:*. In local dev you can set AUTH_LOGIN_LOCKOUT_ENABLED=false in the API .env.',
      };
    }
    if (err instanceof ApiResponseError && err.status === 503) {
      return { error: messageFromApiErrorBody(err.body) ?? LOCAL_INFRA_DOWN_MESSAGE };
    }
    if (message.includes('500')) {
      return {
        error:
          'The API returned an internal error. Check the API terminal: connection refused to Postgres (5432) or Redis (6379) usually means Docker is not running — run `./scripts/setup-dev-env.sh` or `docker compose up -d`, then migrations. If logs show a JWT signing error, set JWT_ALGORITHM=HS256 and a long JWT_SECRET_KEY in `.env`.',
      };
    }
    return { error: message };
  }

  redirect('/dashboard');
}

/**
 * Server action: create a new account, provision a default organization, and store tokens.
 */
export async function signupAction(
  _prevState: SignupState,
  formData: FormData
): Promise<SignupState> {
  const email = (formData.get('email') as string | null)?.trim() ?? '';
  const password = (formData.get('password') as string | null) ?? '';
  const confirmPassword = (formData.get('confirmPassword') as string | null) ?? '';
  const organizationName = (formData.get('organizationName') as string | null)?.trim() ?? '';

  if (!email || !password) {
    return { error: 'Email and password are required.' };
  }

  if (password.length < 8) {
    return { error: 'Password must be at least 8 characters long.' };
  }

  if (password !== confirmPassword) {
    return { error: 'Passwords do not match.' };
  }

  try {
    const client = new ZernaClient({ baseUrl: API_BASE_URL });
    const response = await client.auth.signup({
      email,
      password,
      organization_name: organizationName || undefined,
    });

    setAuthToken(response.access_token);
    setRefreshToken(response.refresh_token);

    const cookieStore = cookies();
    cookieStore.set('zerna_token_pub', response.access_token, {
      httpOnly: false,
      secure: shouldUseSecureCookies(),
      sameSite: 'lax',
      path: '/',
      maxAge: 60 * 60 * 24 * 7,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Signup failed. Please try again.';
    const normalized = message.toLowerCase();
    if (
      normalized.includes('fetch failed') ||
      normalized.includes('networkerror') ||
      normalized.includes('econnrefused')
    ) {
      return {
        error: `Cannot reach the Zerna API at ${API_BASE_URL}. Make sure the API server is running.`,
      };
    }
    if (message.includes('409')) {
      return { error: 'An account with this email already exists.' };
    }
    if (message.includes('429')) {
      return {
        error:
          'Too many requests to the API. Wait a minute and try again. If this persists, increase RATE_LIMIT_PER_MINUTE or exempt /v1/auth in local dev.',
      };
    }
    if (err instanceof ApiResponseError && err.status === 503) {
      return { error: messageFromApiErrorBody(err.body) ?? LOCAL_INFRA_DOWN_MESSAGE };
    }
    return { error: message };
  }

  redirect('/dashboard');
}

/**
 * Server action: clear auth cookies and redirect to login.
 */
export async function logoutAction(): Promise<void> {
  clearAuthCookies();

  const cookieStore = cookies();
  cookieStore.delete('zerna_token_pub');

  await Promise.resolve();
  redirect('/login');
}
