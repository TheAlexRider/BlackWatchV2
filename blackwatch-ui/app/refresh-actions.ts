"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/server-fetch";
import type { ModulesRefreshResponse } from "@/lib/types";

// Server-action mirror of what the /connectors page's Run-Now button does:
// runs on the server, uses apiFetch (which forwards the bw_session cookie
// to the FastAPI backend), then revalidates the caller's path so the
// next-fetched server-rendered data reflects any newly-drained events.
export async function refreshModulesAction(
  connectorTypes: string[],
  revalidateOfPath: string,
): Promise<ModulesRefreshResponse> {
  const types = connectorTypes.filter(
    (t): t is string => typeof t === "string" && t.length > 0,
  );
  if (types.length === 0) {
    if (revalidateOfPath) revalidatePath(revalidateOfPath);
    return { ran: [], total_ingested: 0 };
  }
  const res = await apiFetch(`/api/modules/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ connector_types: types }),
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = "";
    try {
      detail = await res.text();
    } catch {
      /* ignore */
    }
    throw new Error(
      `refresh failed: ${res.status}${detail ? ` — ${detail.slice(0, 160)}` : ""}`,
    );
  }
  const body = (await res.json()) as ModulesRefreshResponse;
  if (revalidateOfPath) revalidatePath(revalidateOfPath);
  return body;
}
