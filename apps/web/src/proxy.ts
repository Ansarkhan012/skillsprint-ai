import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function proxy(request: NextRequest) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return NextResponse.next({ request });

  let response = NextResponse.next({ request });
  const supabase = createServerClient(url, key, {
    cookies: {
      getAll() { return request.cookies.getAll(); },
      setAll(values: { name: string; value: string; options: CookieOptions }[]) {
        values.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        values.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });
  const { data: { user }, error } = await supabase.auth.getUser();
  // An auth service outage is not evidence that the session is invalid.
  if (error && error.name !== "AuthSessionMissingError" && ![400, 401, 403].includes(error.status ?? 0)) {
    const unavailable = new NextResponse("Authentication service temporarily unavailable. Please retry.", { status: 503 });
    response.cookies.getAll().forEach((cookie) => unavailable.cookies.set(cookie));
    return unavailable;
  }
  if (!user && request.nextUrl.pathname.startsWith("/app")) {
    const target = request.nextUrl.clone();
    target.pathname = "/login";
    target.searchParams.set("next", request.nextUrl.pathname);
    const redirectResponse = NextResponse.redirect(target);
    response.cookies.getAll().forEach((cookie) => redirectResponse.cookies.set(cookie));
    return redirectResponse;
  }
  if (user && request.nextUrl.pathname === "/login") {
    const redirectResponse = NextResponse.redirect(new URL("/app/dashboard", request.url));
    response.cookies.getAll().forEach((cookie) => redirectResponse.cookies.set(cookie));
    return redirectResponse;
  }
  return response;
}

export const config = { matcher: ["/app/:path*", "/login"] };
