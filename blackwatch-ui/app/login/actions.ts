"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { API_BASE } from "@/lib/api";

// Login server action.
//
// Flow:
//   1. Post credentials to FastAPI /api/auth/login
//   2. FastAPI sets a Set-Cookie header on its response — but that cookie
//      is bound to the *server-side* fetch's cookie jar. To actually put
//      it in the browser we parse the Set-Cookie header and re-emit it
//      via next/headers cookies() on the outgoing response.
//   3. Redirect to `next` (from ?next=) or `/`.
//
// If backend returns non-2xx we bounce back to /login with an error msg.

const COOKIE_NAME = "bw_session";

// Cheap Set-Cookie parser. Handles the shape FastAPI produces:
//   "bw_session=<value>; HttpOnly; Path=/; SameSite=lax; Max-Age=1800"
function parseSessionCookie(
  header: string | null,
): { value: string; maxAge: number } | null {
  if (!header) return null;
  const nameMatch = header.match(new RegExp(`${COOKIE_NAME}=([^;]+)`));
  if (!nameMatch) return null;
  const maxAgeMatch = header.match(/Max-Age=(\d+)/i);
  return {
    value: nameMatch[1],
    maxAge: maxAgeMatch ? Number(maxAgeMatch[1]) : 1800,
  };
}

export async function loginAction(fd: FormData): Promise<void> {
  const username = String(fd.get("username") ?? "").trim();
  const password = String(fd.get("password") ?? "");
  const nextPath = String(fd.get("next") ?? "/");

  if (!username || !password) {
    redirect(`/login?err=${encodeURIComponent("Enter username and password")}`);
  }

  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    cache: "no-store",
  });

  if (!res.ok) {
    redirect(`/login?err=${encodeURIComponent("Invalid credentials")}`);
  }

  const parsed = parseSessionCookie(res.headers.get("set-cookie"));
  if (!parsed) {
    redirect(
      `/login?err=${encodeURIComponent(
        "Login succeeded but no session cookie was set. Check backend logs.",
      )}`,
    );
  }

  const store = await cookies();
  store.set(COOKIE_NAME, parsed.value, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: parsed.maxAge,
  });

  // Only allow relative redirect targets to avoid open-redirect abuse.
  const safeNext = nextPath.startsWith("/") && !nextPath.startsWith("//")
    ? nextPath
    : "/";
  redirect(safeNext);
}

export async function logoutAction(): Promise<void> {
  const store = await cookies();
  const sid = store.get(COOKIE_NAME)?.value;
  // Best-effort: tell the backend to delete the session. Even if this
  // fails we still clear the local cookie so the user is logged out on
  // their machine.
  if (sid) {
    try {
      await fetch(`${API_BASE}/api/auth/logout`, {
        method: "POST",
        headers: { Cookie: `${COOKIE_NAME}=${sid}` },
        cache: "no-store",
      });
    } catch {
      // Ignore — we still nuke the cookie below.
    }
  }
  store.delete(COOKIE_NAME);
  redirect("/login");
}
