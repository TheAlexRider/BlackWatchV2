"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { API_BASE } from "@/lib/api";
import { apiFetch } from "@/lib/server-fetch";

// Helpers --------------------------------------------------------------------

async function postJSON(path: string, body: unknown): Promise<void> {
  const res = await apiFetch(`${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${path} failed: ${res.status} ${text}`);
  }
}

function rulesRedirect(msg: string): never {
  redirect(`/rules?msg=${encodeURIComponent(msg)}`);
}

// Actions --------------------------------------------------------------------

export async function toggleRuleAction(formData: FormData): Promise<void> {
  const ruleId = String(formData.get("rule_id") ?? "");
  const enabled = formData.get("enabled") === "on";
  if (!ruleId) return;
  await postJSON(`/api/rules/${encodeURIComponent(ruleId)}/toggle`, { enabled });
  revalidatePath("/rules");
  rulesRedirect(`${ruleId} ${enabled ? "enabled" : "disabled"}`);
}

export async function muteAction(formData: FormData): Promise<void> {
  const action = String(formData.get("action") ?? "").trim();
  if (!action) return;
  await postJSON("/api/noise/mute", { action });
  revalidatePath("/rules");
  rulesRedirect(`muting ${action}`);
}

export async function unmuteAction(formData: FormData): Promise<void> {
  const action = String(formData.get("action") ?? "").trim();
  if (!action) return;
  await postJSON("/api/noise/unmute", { action });
  revalidatePath("/rules");
  rulesRedirect(`unmuted ${action}`);
}

const ALLOWED_SEVERITIES = new Set([
  "informational",
  "low",
  "medium",
  "high",
  "critical",
]);

export async function setSeverityAction(formData: FormData): Promise<void> {
  const ruleId = String(formData.get("rule_id") ?? "").trim();
  const raw = String(formData.get("severity") ?? "").trim();
  if (!ruleId) return;
  // Empty string / "default" from the <select> clears the override.
  const severity =
    raw && raw !== "default" && ALLOWED_SEVERITIES.has(raw) ? raw : null;
  await postJSON(`/api/rules/${encodeURIComponent(ruleId)}/severity`, {
    severity,
  });
  revalidatePath("/rules");
  rulesRedirect(
    severity
      ? `${ruleId} severity → ${severity}`
      : `${ruleId} severity reset to YAML default`,
  );
}
