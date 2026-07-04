"use server";

import { revalidatePath } from "next/cache";
import { API_BASE } from "@/lib/api";

export type ActionResult = {
  ok: boolean;
  message: string;
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

export async function savePerfQuickAction(
  _prev: ActionResult,
  fd: FormData,
): Promise<ActionResult> {
  const metric = String(fd.get("metric") ?? "");
  if (!metric) return { ok: false, message: "missing metric", at: now() };
  const scope = String(fd.get("scope") ?? "all");
  const instance_id =
    scope === "instance" ? String(fd.get("instance_id") ?? "").trim() || null : null;
  const payload = {
    metric,
    scope,
    instance_id,
    channel: String(fd.get("channel") ?? "").trim() || null,
    threshold: Number(fd.get("threshold") ?? 0),
    window_minutes: Number(fd.get("window_minutes") ?? 5),
    severity: String(fd.get("severity") ?? "high"),
    enabled: fd.get("enabled") !== "off",
  };
  const res = await postJson("/api/notifications/perf-alerts/quick", payload);
  if (!res.ok) {
    const body = await bodyOr("", res);
    return { ok: false, message: `Save failed (${res.status}) ${body}`, at: now() };
  }
  revalidatePath("/notifications/perf-alerts/quick");
  revalidatePath("/notifications");
  return {
    ok: true,
    message: payload.channel
      ? `Saved · alerting on ${metric} ≥ ${payload.threshold}% for ${payload.window_minutes}m`
      : `${metric} turned off`,
    at: now(),
  };
}
