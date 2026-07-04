"use server";

import { revalidatePath } from "next/cache";
import { API_BASE } from "@/lib/api";

// Shared shape for all inline lane actions. Returned to useActionState so
// each lane can render its own inline status without a page refresh.
export type LaneResult = {
  ok: boolean;
  message: string;
  at: number;
} | null;

const now = () => Date.now();

async function postJson(path: string, body: Record<string, unknown>): Promise<Response> {
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

// ---- Custom-rule inline actions ------------------------------------------
// Inline lanes only edit "which channel" and "on/off" — the condition
// tree is never touched here. The full-form editor at /rules/[id] handles
// condition changes.

export async function setCustomRuleChannelAction(
  _prev: LaneResult,
  fd: FormData,
): Promise<LaneResult> {
  const id = String(fd.get("id") ?? "");
  const channel = String(fd.get("channel") ?? "").trim();
  if (!id) return { ok: false, message: "missing rule id", at: now() };

  // GET current rule then re-save it with just channels changed — the
  // /rules/save endpoint is upsert with full payload, so we merge locally.
  const getRes = await fetch(
    `${API_BASE}/api/notifications/rules/${encodeURIComponent(id)}`,
    { cache: "no-store" },
  );
  if (!getRes.ok) {
    return { ok: false, message: `Load failed (${getRes.status})`, at: now() };
  }
  const rule = await getRes.json();
  const payload = {
    id: rule.id,
    name: rule.name,
    enabled: rule.enabled,
    match: rule.match ?? {},
    channels: channel ? [channel] : [],
    throttle_seconds: rule.throttle_seconds ?? 0,
    priority: rule.priority ?? 100,
  };
  const res = await postJson("/api/notifications/rules/save", payload);
  if (!res.ok) {
    const body = await bodyOr("", res);
    return { ok: false, message: `Save failed (${res.status}) ${body}`, at: now() };
  }
  revalidatePath("/notifications");
  return {
    ok: true,
    message: channel ? `Now routing to ${channel}` : "Channel cleared",
    at: now(),
  };
}

export async function toggleCustomRuleAction(
  _prev: LaneResult,
  fd: FormData,
): Promise<LaneResult> {
  const id = String(fd.get("id") ?? "");
  const enabled = fd.get("target") === "on";
  if (!id) return { ok: false, message: "missing rule id", at: now() };
  const res = await postJson(
    `/api/notifications/rules/${encodeURIComponent(id)}/toggle`,
    { enabled },
  );
  if (!res.ok) {
    const body = await bodyOr("", res);
    return { ok: false, message: `Toggle failed (${res.status}) ${body}`, at: now() };
  }
  revalidatePath("/notifications");
  return { ok: true, message: enabled ? "Turned on" : "Turned off", at: now() };
}

export async function silenceCustomRuleAction(
  _prev: LaneResult,
  fd: FormData,
): Promise<LaneResult> {
  const id = String(fd.get("id") ?? "");
  const hours = Number(fd.get("hours") ?? 0);
  if (!id) return { ok: false, message: "missing rule id", at: now() };
  const res = await postJson(
    `/api/notifications/rules/${encodeURIComponent(id)}/silence`,
    { hours },
  );
  if (!res.ok) {
    const body = await bodyOr("", res);
    return { ok: false, message: `Silence failed (${res.status}) ${body}`, at: now() };
  }
  revalidatePath("/notifications");
  return {
    ok: true,
    message: hours > 0 ? `Silenced for ${hours}h` : "Silence cleared",
    at: now(),
  };
}

export async function deleteCustomRuleAction(
  _prev: LaneResult,
  fd: FormData,
): Promise<LaneResult> {
  const id = String(fd.get("id") ?? "");
  if (!id) return { ok: false, message: "missing rule id", at: now() };
  const res = await fetch(
    `${API_BASE}/api/notifications/rules/${encodeURIComponent(id)}`,
    { method: "DELETE", cache: "no-store" },
  );
  if (!res.ok) {
    const body = await bodyOr("", res);
    return { ok: false, message: `Delete failed (${res.status}) ${body}`, at: now() };
  }
  revalidatePath("/notifications");
  return { ok: true, message: "Rule deleted", at: now() };
}

export async function testChannelByNameAction(
  _prev: LaneResult,
  fd: FormData,
): Promise<LaneResult> {
  const channel = String(fd.get("channel") ?? "").trim();
  if (!channel) return { ok: false, message: "no channel to test", at: now() };
  // Look up the channel id — the /test endpoint takes id, not name.
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
    return { ok: false, message: `Test failed (${res.status}) ${body}`, at: now() };
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
