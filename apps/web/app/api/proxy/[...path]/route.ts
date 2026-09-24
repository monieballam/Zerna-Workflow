/**
 * Catch-all API proxy route.
 *
 * Forwards requests from the browser to the backend API at localhost:8000,
 * injecting the httpOnly auth token from cookies. This avoids CORS issues
 * and means client components never need direct access to the JWT.
 *
 * Usage:  fetch("/api/proxy/v1/runs/xxx/embedding")
 *    →    GET http://localhost:8000/v1/runs/xxx/embedding  (with Bearer token)
 */
import { cookies } from 'next/headers';
import { NextRequest, NextResponse } from 'next/server';

const API_BASE =
  process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function proxyRequest(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const target = `${API_BASE}/${path.join('/')}`;

  // Preserve query string
  const url = new URL(target);
  req.nextUrl.searchParams.forEach((v, k) => url.searchParams.set(k, v));

  // Read httpOnly auth cookie
  const cookieStore = cookies();
  const token = cookieStore.get('zerna_token')?.value;

  const headers = new Headers();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  // Forward content-type if present
  const ct = req.headers.get('content-type');
  if (ct) headers.set('content-type', ct);

  const upstream = await fetch(url.toString(), {
    method: req.method,
    headers,
    body: req.method !== 'GET' && req.method !== 'HEAD' ? req.body : undefined,
    // @ts-expect-error -- duplex needed for streaming body in Node 18+
    duplex: req.method !== 'GET' && req.method !== 'HEAD' ? 'half' : undefined,
  });

  // Stream the response back
  return new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: {
      'content-type': upstream.headers.get('content-type') ?? 'application/octet-stream',
      ...(upstream.headers.get('content-disposition')
        ? { 'content-disposition': upstream.headers.get('content-disposition')! }
        : {}),
      ...(upstream.headers.get('content-length')
        ? { 'content-length': upstream.headers.get('content-length')! }
        : {}),
    },
  });
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const DELETE = proxyRequest;
export const PATCH = proxyRequest;
