"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { API_BASE } from "@/lib/api";
import { apiFetch } from "@/lib/server-fetch";
import type { ChannelType } from "@/lib/types";

// =========================================================================
// shared HTTP helpers
// =========================================================================

async function postJson(path: string, body: Record<string, unknown>): Promise<Response> {
  return apiFetch(`${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
}

async function deleteReq(path: string): Promise<Response> {
  return apiFetch(`${path}`, { method: "DELETE", cache: "no-store" });
}

function notifRedirect(msg: string): never {
  redirect(`/notifications?msg=${encodeURIComponent(msg)}`);
}

// =========================================================================
// channels
// =========================================================================

// Translate the per-type form fields into the `config` dict that the backend
// stores. Secrets are NEVER inlined — for email/pagerduty we capture only the
// env-var name (e.g. `password_env`, `routing_key_env`).
function buildChannelConfig(type: ChannelType, fd: FormData): Record<string, unknown> {
  switch (type) {
    case "slack":
    case "teams":
    case "discord":
    case "webhook":
      return { url: String(fd.get("url") ?? "").trim() };
    case "email":
      return {
        smtp_host: String(fd.get("smtp_host") ?? "").trim(),
        smtp_port: Number(fd.get("smtp_port") ?? 587),
        use_tls: fd.get("use_tls") === "on",
        smtp_user: String(fd.get("smtp_user") ?? "").trim(),
        password_env: String(fd.get("password_env") ?? "").trim(),
        from_addr: String(fd.get("from_addr") ?? "").trim(),
        to_addrs: String(fd.get("to_addrs") ?? "")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      };
    case "pagerduty":
      return {
        routing_key_env: String(fd.get("routing_key_env") ?? "").trim(),
      };
  }
}

export async function saveChannelAction(fd: FormData): Promise<void> {
  const type = String(fd.get("type") ?? "") as ChannelType;
  const id = String(fd.get("id") ?? "");
  const payload = {
    id: id || undefined,
    name: String(fd.get("name") ?? "").trim(),
    type,
    enabled: fd.get("enabled") === "on",
    config: buildChannelConfig(type, fd),
    message_template: String(fd.get("message_template") ?? "").trim() || null,
    retries: Number(fd.get("retries") ?? 3),
    retry_backoff_seconds: Number(fd.get("retry_backoff_seconds") ?? 5),
    rate_limit_per_min: Number(fd.get("rate_limit_per_min") ?? 0),
    dedup_window_seconds: Number(fd.get("dedup_window_seconds") ?? 300),
    digest_window_seconds: Number(fd.get("digest_window_seconds") ?? 0),
  };
  const res = await postJson("/api/notifications/channels/save", payload);
  if (!res.ok) throw new Error(`saveChannel failed: ${res.status} ${await res.text()}`);
  revalidatePath("/notifications");
  notifRedirect(`saved channel ${payload.name}`);
}

export async function toggleChannelAction(fd: FormData): Promise<void> {
  const id = String(fd.get("id") ?? "");
  const enabled = fd.get("enabled") === "on";
  if (!id) return;
  const res = await postJson(
    `/api/notifications/channels/${encodeURIComponent(id)}/toggle`,
    { enabled },
  );
  if (!res.ok) throw new Error(`toggleChannel failed: ${res.status}`);
  revalidatePath("/notifications");
  notifRedirect(`channel ${enabled ? "enabled" : "disabled"}`);
}

export async function testChannelAction(fd: FormData): Promise<void> {
  const id = String(fd.get("id") ?? "");
  if (!id) return;
  const res = await postJson(
    `/api/notifications/channels/${encodeURIComponent(id)}/test`,
    {},
  );
  if (!res.ok) throw new Error(`testChannel failed: ${res.status}`);
  const data = (await res.json()) as { status?: string; detail?: string };
  revalidatePath("/notifications");
  notifRedirect(`channel test: ${data.status ?? "?"}${data.detail ? ` · ${data.detail}` : ""}`);
}

export async function deleteChannelAction(fd: FormData): Promise<void> {
  const id = String(fd.get("id") ?? "");
  if (!id) return;
  const res = await deleteReq(`/api/notifications/channels/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`deleteChannel failed: ${res.status}`);
  revalidatePath("/notifications");
  notifRedirect("channel deleted");
}

// =========================================================================
// rules
// =========================================================================

const SEVERITY_LADDER = ["informational", "low", "medium", "high", "critical"];

// Translate the wizard's flat inputs into the Condition tree the backend
// expects. Single-criterion rules become a single condition; multi-criterion
// rules become an `all:` group. The user can override entirely via the
// "advanced YAML" textarea — we only build a tree if no advanced YAML was set.
function buildMatchFromSimpleForm(fd: FormData): Record<string, unknown> {
  const advancedYaml = String(fd.get("advanced_yaml") ?? "").trim();
  if (advancedYaml) {
    try {
      // We do JSON only here. Operators who want full YAML use the advanced
      // path which is JSON-shaped in our UI (the backend still accepts both).
      return JSON.parse(advancedYaml);
    } catch {
      // Fall back to "raw" string so the backend can yell about it.
      throw new Error("Advanced criteria must be valid JSON");
    }
  }

  // The rule engine's Condition model expects {field, op, value} — NOT the
  // shortcut {field, in: [...]} / {field, icontains: "..."} shape this form
  // used to emit. Pydantic silently drops the shortcut keys; cond.op stays
  // None; eval_condition returns False for every clause; the rule never
  // matches. That's why notifications looked configured but never fired.
  const parts: Array<Record<string, unknown>> = [];

  const sevAtLeast = String(fd.get("severity_at_least") ?? "any");
  if (sevAtLeast !== "any") {
    const idx = SEVERITY_LADDER.indexOf(sevAtLeast);
    if (idx >= 0) {
      parts.push({
        field: "severity",
        op: "in",
        value: SEVERITY_LADDER.slice(idx),
      });
    }
  }

  const categories = (fd.getAll("category") as string[]).filter(Boolean);
  if (categories.length > 0) {
    parts.push({ field: "category", op: "in", value: categories });
  }

  const modules = (fd.getAll("module") as string[]).filter(Boolean);
  if (modules.length > 0) {
    parts.push({ field: "source.module", op: "in", value: modules });
  }

  const actionContains = String(fd.get("action_contains") ?? "").trim();
  if (actionContains) {
    parts.push({ field: "action", op: "icontains", value: actionContains });
  }

  if (parts.length === 0) {
    // Match-all is allowed but unusual. Use a no-op true.
    return { all: [] };
  }
  if (parts.length === 1) return parts[0];
  return { all: parts };
}

export async function saveRuleAction(fd: FormData): Promise<void> {
  const id = String(fd.get("id") ?? "");
  const match = buildMatchFromSimpleForm(fd);
  const channels = (fd.getAll("channel") as string[]).filter(Boolean);
  const payload = {
    id: id || undefined,
    name: String(fd.get("name") ?? "").trim(),
    enabled: fd.get("enabled") === "on",
    match,
    channels,
    throttle_seconds: Number(fd.get("throttle_seconds") ?? 0),
    priority: Number(fd.get("priority") ?? 100),
  };
  const res = await postJson("/api/notifications/rules/save", payload);
  if (!res.ok) throw new Error(`saveRule failed: ${res.status} ${await res.text()}`);
  revalidatePath("/notifications");
  notifRedirect(`saved rule ${payload.name}`);
}

export async function toggleRuleAction(fd: FormData): Promise<void> {
  const id = String(fd.get("id") ?? "");
  const enabled = fd.get("enabled") === "on";
  if (!id) return;
  const res = await postJson(
    `/api/notifications/rules/${encodeURIComponent(id)}/toggle`,
    { enabled },
  );
  if (!res.ok) throw new Error(`toggleRule failed: ${res.status}`);
  revalidatePath("/notifications");
  notifRedirect(`rule ${enabled ? "enabled" : "disabled"}`);
}

export async function silenceRuleAction(fd: FormData): Promise<void> {
  const id = String(fd.get("id") ?? "");
  const hours = Number(fd.get("hours") ?? 0);
  if (!id) return;
  const res = await postJson(
    `/api/notifications/rules/${encodeURIComponent(id)}/silence`,
    { hours },
  );
  if (!res.ok) throw new Error(`silenceRule failed: ${res.status}`);
  revalidatePath("/notifications");
  notifRedirect(hours > 0 ? `silenced for ${hours}h` : "silence cleared");
}

export async function deleteRuleAction(fd: FormData): Promise<void> {
  const id = String(fd.get("id") ?? "");
  if (!id) return;
  const res = await deleteReq(`/api/notifications/rules/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`deleteRule failed: ${res.status}`);
  revalidatePath("/notifications");
  notifRedirect("rule deleted");
}

// =========================================================================
// acks
// =========================================================================

export async function clearAckAction(fd: FormData): Promise<void> {
  const fp = String(fd.get("fingerprint") ?? "");
  if (!fp) return;
  const res = await deleteReq(`/api/notifications/acks/${encodeURIComponent(fp)}`);
  if (!res.ok) throw new Error(`clearAck failed: ${res.status}`);
  revalidatePath("/notifications");
  notifRedirect("ack cleared");
}
