"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { API_BASE } from "@/lib/api";

async function postJson(path: string, body: Record<string, unknown>): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
}

function done(msg: string): never {
  redirect(`/notifications/perf-alerts/quick?msg=${encodeURIComponent(msg)}`);
}

export async function savePerfQuickAction(fd: FormData): Promise<void> {
  const metric = String(fd.get("metric") ?? "");
  if (!metric) return;
  const scope = String(fd.get("scope") ?? "all");
  const instance_id = scope === "instance" ? (String(fd.get("instance_id") ?? "").trim() || null) : null;
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
    const body = await res.text();
    throw new Error(`savePerfQuick failed: ${res.status} ${body}`);
  }
  revalidatePath("/notifications/perf-alerts/quick");
  revalidatePath("/notifications");
  done(payload.channel ? `${metric} saved` : `${metric} disabled`);
}
