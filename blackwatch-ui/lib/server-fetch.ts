"use server";

import { cookies } from "next/headers";
import { API_BASE } from "./api";

// Shared server-side fetch helper for /api/* endpoints that require the
// bw_session cookie. Server actions can't rely on the browser to attach
// cookies — this reads the incoming request's cookie via next/headers
// and forwards it to the FastAPI backend.

const SESSION_COOKIE = "bw_session";

async function _sessionCookie(): Promise<string | undefined> {
  try {
    const store = await cookies();
    return store.get(SESSION_COOKIE)?.value;
  } catch {
    return undefined;
  }
}

/** Fetch the FastAPI backend from a server action, forwarding the current
 *  request's session cookie. Accepts either a path (leading `/api/…`)
 *  or an absolute URL. */
export async function apiFetch(
  pathOrUrl: string,
  init?: RequestInit,
): Promise<Response> {
  const sid = await _sessionCookie();
  const url = pathOrUrl.startsWith("http") ? pathOrUrl : `${API_BASE}${pathOrUrl}`;
  return fetch(url, {
    ...init,
    cache: init?.cache ?? "no-store",
    headers: {
      ...(init?.headers as Record<string, string> | undefined),
      ...(sid ? { Cookie: `${SESSION_COOKIE}=${sid}` } : {}),
    },
  });
}
