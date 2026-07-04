"use server";

import { revalidatePath } from "next/cache";
import { API_BASE } from "@/lib/api";

// Server actions for the ALERT ROUTES table on /notifications.
// Every action returns {ok, message, at} for inline useActionState feedback.

export type RouteResult = {
  ok: boolean;
  message: string;
  at: number;
} | null;

const now = () => Date.now();

async function postJson(
  path: string,
  body: Record<string, unknown>,
): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
}

async function bodyOr(fallback: string, res: Response): Promise<string> {
  try {
    const t = (await res.text()).slice(0, 200);
    return t || fallback;
  } catch {
    return fallback;
  }
}

// Save (create or edit) a simple route. Payload:
//   id?         — omit to create a new route, set to update an existing one
//   module      — required
//   severities  — array of severity keys
//   channel     — required (empty string = delete via the delete endpoint instead)
//   enabled     — bool, defaults true
export async function saveRouteAction(
  _prev: RouteResult,
  fd: FormData,
): Promise<RouteResult> {
  const module = String(fd.get("module") ?? "").trim();
  const channel = String(fd.get("channel") ?? "").trim();
  const severities = fd.getAll("severity").map((s) => String(s));
  const id = String(fd.get("id") ?? "").trim() || undefined;
  const enabled = fd.get("enabled") !== "off";

  if (!module) return { ok: false, message: "Pick a module first", at: now() };
  if (!channel) return { ok: false, message: "Pick a channel first", at: now() };
  if (severities.length === 0)
    return { ok: false, message: "Pick at least one severity", at: now() };

  const res = await postJson("/api/notifications/routes/save", {
    id,
    module,
    severities,
    channel,
    enabled,
  });
  if (!res.ok) {
    const body = await bodyOr("", res);
    return {
      ok: false,
      message: `Save failed (${res.status}) ${body}`,
      at: now(),
    };
  }
  revalidatePath("/notifications");
  return {
    ok: true,
    message: id
      ? `Updated — routing ${severities.join(" + ")} to ${channel}`
      : `Route added — ${severities.join(" + ")} → ${channel}`,
    at: now(),
  };
}

export async function toggleRouteAction(
  _prev: RouteResult,
  fd: FormData,
): Promise<RouteResult> {
  const id = String(fd.get("id") ?? "").trim();
  const enabled = fd.get("target") === "on";
  if (!id) return { ok: false, message: "missing route id", at: now() };
  const res = await postJson(
    `/api/notifications/routes/${encodeURIComponent(id)}/toggle`,
    { enabled },
  );
  if (!res.ok) {
    const body = await bodyOr("", res);
    return {
      ok: false,
      message: `Toggle failed (${res.status}) ${body}`,
      at: now(),
    };
  }
  revalidatePath("/notifications");
  return { ok: true, message: enabled ? "Turned on" : "Turned off", at: now() };
}

export async function silenceRouteAction(
  _prev: RouteResult,
  fd: FormData,
): Promise<RouteResult> {
  const id = String(fd.get("id") ?? "").trim();
  const hours = Number(fd.get("hours") ?? 0);
  if (!id) return { ok: false, message: "missing route id", at: now() };
  const res = await postJson(
    `/api/notifications/routes/${encodeURIComponent(id)}/silence`,
    { hours },
  );
  if (!res.ok) {
    const body = await bodyOr("", res);
    return {
      ok: false,
      message: `Silence failed (${res.status}) ${body}`,
      at: now(),
    };
  }
  revalidatePath("/notifications");
  return {
    ok: true,
    message: hours > 0 ? `Silenced for ${hours}h` : "Silence cleared",
    at: now(),
  };
}

export async function deleteRouteAction(
  _prev: RouteResult,
  fd: FormData,
): Promise<RouteResult> {
  const id = String(fd.get("id") ?? "").trim();
  if (!id) return { ok: false, message: "missing route id", at: now() };
  const res = await fetch(
    `${API_BASE}/api/notifications/routes/${encodeURIComponent(id)}`,
    { method: "DELETE", cache: "no-store" },
  );
  if (!res.ok) {
    const body = await bodyOr("", res);
    return {
      ok: false,
      message: `Delete failed (${res.status}) ${body}`,
      at: now(),
    };
  }
  revalidatePath("/notifications");
  return { ok: true, message: "Route deleted", at: now() };
}

export async function testRouteAction(
  _prev: RouteResult,
  fd: FormData,
): Promise<RouteResult> {
  const channel = String(fd.get("channel") ?? "").trim();
  if (!channel)
    return { ok: false, message: "no channel to test", at: now() };
  // Look up channel id then hit the /test endpoint.
  const listRes = await fetch(`${API_BASE}/api/notifications/channels`, {
    cache: "no-store",
  });
  if (!listRes.ok) {
    return { ok: false, message: "Could not load channels", at: now() };
  }
  const j = await listRes.json();
  const found = (j.channels || []).find(
    (c: { name: string }) => c.name === channel,
  );
  if (!found) {
    return { ok: false, message: `Channel ${channel} not found`, at: now() };
  }
  const res = await postJson(
    `/api/notifications/channels/${encodeURIComponent(found.id)}/test`,
    {},
  );
  if (!res.ok) {
    const body = await bodyOr("", res);
    return {
      ok: false,
      message: `Test failed (${res.status}) ${body}`,
      at: now(),
    };
  }
  const data = (await res.json()) as { status?: string; detail?: string };
  const success = data.status === "sent";
  return {
    ok: success,
    message: success
      ? `Sent to ${channel}${data.detail ? ` · ${data.detail}` : ""}`
      : `Test: ${data.status}${data.detail ? ` · ${data.detail}` : ""}`,
    at: now(),
  };
}
