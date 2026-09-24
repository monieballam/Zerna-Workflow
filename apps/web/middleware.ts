import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const PUBLIC_PATHS = ['/login', '/signup'];

function isAuthDisabled(): boolean {
  const value =
    process.env.AUTH_DISABLED ?? process.env.NEXT_PUBLIC_AUTH_DISABLED ?? '';
  return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase());
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const authDisabled = isAuthDisabled();

  // With auth disabled, skip the login wall and send auth pages to the app.
  if (authDisabled) {
    if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
      return NextResponse.redirect(new URL('/dashboard', request.url));
    }
    return NextResponse.next();
  }

  // Allow public paths through
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const token = request.cookies.get('zerna_token')?.value;

  if (!token) {
    const loginUrl = new URL('/login', request.url);
    loginUrl.searchParams.set('redirect', pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - _next/static (static files)
     * - _next/image (image optimization)
     * - favicon.ico
     * - api routes
     */
    '/((?!_next/static|_next/image|favicon.ico|api/).*)',
  ],
};
