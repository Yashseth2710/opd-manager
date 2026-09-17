import { NextResponse, type NextRequest } from "next/server";

/**
 * Keeps signed-out people off the clinic screens and signed-in people off the
 * sign-in screens.
 *
 * This is routing, not authorisation. It reads a marker cookie that carries
 * no token and proves nothing; every endpoint that touches clinic data checks
 * the caller for itself. The worst a forged marker achieves is an empty page
 * that immediately redirects back.
 */
const SESSION_MARKER = "opd_session";

const SIGNED_OUT_ONLY = ["/login", "/register", "/forgot-password", "/reset-password"];
const SIGNED_IN_ONLY = ["/dashboard", "/onboarding", "/patients", "/appointments", "/queue"];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const signedIn = request.cookies.has(SESSION_MARKER);

  // The front door is not a page of its own. Someone opening the app either
  // has a clinic to get back to or needs to sign in.
  if (pathname === "/") {
    return NextResponse.redirect(new URL(signedIn ? "/dashboard" : "/login", request.url));
  }

  if (!signedIn && SIGNED_IN_ONLY.some((path) => pathname.startsWith(path))) {
    const login = new URL("/login", request.url);
    // Remember where they were headed so the sign-in lands them there.
    login.searchParams.set("next", pathname + search);
    return NextResponse.redirect(login);
  }

  if (signedIn && SIGNED_OUT_ONLY.some((path) => pathname.startsWith(path))) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  // Everything except Next's own assets and the API, which guards itself.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
