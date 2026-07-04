import { NextResponse, type NextRequest } from "next/server";

// Every UI route requires a bw_session cookie. Missing → bounce to /login
// with a ?next= param so the login flow can return them where they were.
//
// /api/* is proxied to FastAPI, which enforces its own auth middleware, so
// we don't need to re-check the cookie here for API calls. Static assets
// (_next, favicon) are excluded via the config.matcher below.

const COOKIE_NAME = "bw_session";
const PUBLIC_PATHS = ["/login"];

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  // Explicit passthroughs — /login itself must not force a redirect loop.
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    return NextResponse.next();
  }

  const cookie = request.cookies.get(COOKIE_NAME);
  if (!cookie || !cookie.value) {
    const loginUrl = new URL("/login", request.url);
    // Preserve the original path (+ query) so we can send the user back
    // after they authenticate. Login page reads ?next=.
    loginUrl.searchParams.set("next", pathname + (search || ""));
    return NextResponse.redirect(loginUrl);
  }
  return NextResponse.next();
}

// Run on every request except static assets and the API proxy. Backend
// authenticates /api/* itself, so we don't need to duplicate the check.
export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\.png$|.*\\.svg$|.*\\.jpg$).*)",
  ],
};
