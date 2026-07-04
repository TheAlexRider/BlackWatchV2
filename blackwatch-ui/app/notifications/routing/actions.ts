"use server";

import { revalidatePath } from "next/cache";
import { API_BASE } from "@/lib/api";

// Shape returned to useActionState in the ModuleCard client component.
// Each action returns one of these instead of redirecting — that gives us
// inline per-card feedback and no full-page refresh.
export type ActionResult = {
  ok: boolean;
  message: string;
  // `at` is a monotonic tick so React re-fires the auto-hide timer even if
  // two consecutive calls happen to produce the same message text.
  at: number;
} | null;

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

const now = () => Date.now();

// The action signature that useActionState expects:
//   (prevState, formData) => Promise<newState>
// We ignore prevState — each call is independent.

export async function saveCardAction(
  _prev: ActionResult,
  fd: FormData,
): Promise<ActionResult> {
  const module = String(fd.get("module") ?? "");
  if (!module) return { ok: false, message: "missing module", at: now() };

  const payload = {
    enabled: fd.get("enabled") === "on",
    channel: String(fd.get("channel") ?? "").trim() || null,
    threshold: String(fd.get("threshold") ?? "high"),
  };
  const res = await postJson(
    `/api/notifications/cards/${encodeURIComponent(module)}/save`,
    payload,
  );
  if (!res.ok) {
    const body = await bodyOr("", res);
    return { ok: false, message: `Save failed (${res.status}) ${body}`, at: now() };
  }
  revalidatePath("/notifications/routing");
  revalidatePath("/notifications");
  return {
    ok: true,
    message: payload.channel ? `Saved · alerting to ${payload.channel}` : `Turned off`,
    at: now(),
  };
}

export async function toggleCardAction(
  _prev: ActionResult,
  fd: FormData,
): Promise<ActionResult> {
  const module = String(fd.get("module") ?? "");
  if (!module) return { ok: false, message: "missing module", at: now() };
  const channel = String(fd.get("channel") ?? "").trim() || null;
  const threshold = String(fd.get("threshold") ?? "high");
  const enabled = fd.get("target") === "on";
  const res = await postJson(
    `/api/notifications/cards/${encodeURIComponent(module)}/save`,
    { enabled, channel, threshold },
  );
  if (!res.ok) {
    const body = await bodyOr("", res);
    return { ok: false, message: `Toggle failed (${res.status}) ${body}`, at: now() };
  }
  revalidatePath("/notifications/routing");
  revalidatePath("/notifications");
  return { ok: true, message: enabled ? "Turned on" : "Turned off", at: now() };
}

export async function testCardAction(
  _prev: ActionResult,
  fd: FormData,
): Promise<ActionResult> {
  const module = String(fd.get("module") ?? "");
  if (!module) return { ok: false, message: "missing module", at: now() };
  const res = await postJson(
    `/api/notifications/cards/${encodeURIComponent(module)}/test`,
    {},
  );
  if (!res.ok) {
    const body = await bodyOr("", res);
    return { ok: false, message: `Test failed (${res.status}) ${body}`, at: now() };
  }
  const data = (await res.json()) as { status?: string; detail?: string; channel?: string };
  const success = data.status === "sent";
  const label = data.channel ? ` to ${data.channel}` : "";
  const detail = data.detail ? ` · ${data.detail}` : "";
  return {
    ok: success,
    message: success
      ? `Sent${label}${detail}`
      : `Test: ${data.status ?? "?"}${detail}`,
    at: now(),
  };
}

export async function silenceCardAction(
  _prev: ActionResult,
  fd: FormData,
): Promise<ActionResult> {
  const module = String(fd.get("module") ?? "");
  const hours = Number(fd.get("hours") ?? 0);
  if (!module) return { ok: false, message: "missing module", at: now() };
  const res = await postJson(
    `/api/notifications/cards/${encodeURIComponent(module)}/silence`,
    { hours },
  );
  if (!res.ok) {
    const body = await bodyOr("", res);
    return { ok: false, message: `Silence failed (${res.status}) ${body}`, at: now() };
  }
  revalidatePath("/notifications/routing");
  return {
    ok: true,
    message: hours > 0 ? `Silenced for ${hours}h` : "Silence cleared",
    at: now(),
  };
}
