"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { API_BASE } from "@/lib/api";
import { apiFetch } from "@/lib/server-fetch";

// ---------- shared helpers (kept local — actions file is the boundary) -------

async function jsonReq(
  method: "POST" | "PUT",
  path: string,
  body: Record<string, unknown>,
): Promise<Response> {
  return apiFetch(`${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
}

function notifRedirect(msg: string): never {
  redirect(`/notifications?msg=${encodeURIComponent(msg)}`);
}

// ---------- form → payload ---------------------------------------------------

function buildPayload(fd: FormData): Record<string, unknown> {
  const scope = String(fd.get("scope") ?? "instance");
  const tagSpec = String(fd.get("tag_spec") ?? "").trim();
  // Tag scope arrives as one string "k=v"; split here so the API gets the
  // pair separately. Keeps the UI single-field-simple.
  let tag_key: string | null = null;
  let tag_value: string | null = null;
  if (scope === "tag" && tagSpec.includes("=")) {
    const [k, ...vparts] = tagSpec.split("=");
    tag_key = k.trim() || null;
    tag_value = vparts.join("=").trim();
  }
  // Channels arrive as multiple FormData entries with the same key.
  const channels = fd.getAll("channels").map((c) => String(c)).filter(Boolean);

  const windowMinutes = Number(fd.get("window_minutes") ?? 5);
  const throttleMinutes = Number(fd.get("throttle_minutes") ?? 30);

  const template = String(fd.get("message_template") ?? "").trim();

  return {
    name: String(fd.get("name") ?? "").trim(),
    enabled: fd.get("enabled") !== "off",
    module: String(fd.get("module") ?? "ec2.host"),
    instance_id:
      scope === "instance" ? (String(fd.get("instance_id") ?? "").trim() || null) : null,
    tag_key,
    tag_value,
    metric: String(fd.get("metric") ?? "memory_pct"),
    comparison: String(fd.get("comparison") ?? "gte"),
    threshold: Number(fd.get("threshold") ?? 80),
    window_seconds: Math.max(60, Math.round(windowMinutes * 60)),
    min_breach_ratio: Number(fd.get("min_breach_ratio") ?? 0.6),
    severity: String(fd.get("severity") ?? "high"),
    channels,
    throttle_seconds: Math.max(0, Math.round(throttleMinutes * 60)),
    message_template: template || null,
  };
}

// ---------- create -----------------------------------------------------------

export async function createPerfAlertAction(fd: FormData): Promise<void> {
  const payload = buildPayload(fd);
  const res = await jsonReq("POST", "/api/perf-alerts", payload);
  if (!res.ok) {
    const body = await res.text();
    notifRedirect(`Create failed: ${res.status} ${body.slice(0, 200)}`);
  }
  revalidatePath("/notifications");
  notifRedirect(`Performance alert created: ${payload.name}`);
}

// ---------- update -----------------------------------------------------------

export async function updatePerfAlertAction(
  ruleId: string,
  fd: FormData,
): Promise<void> {
  const payload = buildPayload(fd);
  const res = await jsonReq("PUT", `/api/perf-alerts/${encodeURIComponent(ruleId)}`, payload);
  if (!res.ok) {
    const body = await res.text();
    notifRedirect(`Update failed: ${res.status} ${body.slice(0, 200)}`);
  }
  revalidatePath("/notifications");
  notifRedirect(`Performance alert updated: ${payload.name}`);
}

// ---------- toggle / delete --------------------------------------------------

export async function togglePerfAlertAction(fd: FormData): Promise<void> {
  const ruleId = String(fd.get("id") ?? "").trim();
  const target = String(fd.get("target") ?? "").trim();
  if (!ruleId) notifRedirect("Missing rule id");
  // Get-then-PUT — no partial update endpoint; PUT wants the full shape.
  const res = await apiFetch(`/api/perf-alerts/${encodeURIComponent(ruleId)}`, {
    cache: "no-store",
  });
  if (!res.ok) notifRedirect("Toggle failed: rule not found");
  const rule = await res.json();
  rule.enabled = target === "on";
  await jsonReq("PUT", `/api/perf-alerts/${encodeURIComponent(ruleId)}`, rule);
  revalidatePath("/notifications");
  notifRedirect(`Performance alert ${rule.enabled ? "enabled" : "disabled"}: ${rule.name}`);
}

export async function deletePerfAlertAction(fd: FormData): Promise<void> {
  const ruleId = String(fd.get("id") ?? "").trim();
  const ruleName = String(fd.get("name") ?? "").trim() || ruleId;
  if (!ruleId) notifRedirect("Missing rule id");
  const res = await apiFetch(`/api/perf-alerts/${encodeURIComponent(ruleId)}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!res.ok) notifRedirect(`Delete failed: ${res.status}`);
  revalidatePath("/notifications");
  notifRedirect(`Performance alert deleted: ${ruleName}`);
}
