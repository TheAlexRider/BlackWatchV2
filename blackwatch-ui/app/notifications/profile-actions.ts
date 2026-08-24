"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { apiFetch } from "@/lib/server-fetch";

const CONTENT_FIELDS = [
  "title",
  "what_happened",
  "why_it_matters",
  "evidence",
  "monitoring_method",
  "impact",
  "next_steps",
  "recovery",
  "runbook_url",
] as const;

async function postJson(path: string, body: Record<string, unknown>): Promise<Response> {
  return apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
}

async function responseDetail(res: Response): Promise<string> {
  try {
    const body = await res.json() as { detail?: string };
    return body.detail || "HTTP " + res.status;
  } catch {
    return "HTTP " + res.status;
  }
}

function go(profileId: string, message: string): never {
  redirect("/notifications/profiles/" + encodeURIComponent(profileId) + "?msg=" + encodeURIComponent(message));
}

export async function saveNotificationProfileAction(fd: FormData): Promise<void> {
  const profileId = String(fd.get("id") ?? "").trim();
  const content = Object.fromEntries(
    CONTENT_FIELDS.map((field) => [field, String(fd.get(field) ?? "").trim()]),
  );
  const payload = {
    id: profileId,
    module: String(fd.get("module") ?? ""),
    event_kind: String(fd.get("event_kind") ?? ""),
    enabled: fd.get("enabled") === "on",
    severities: fd.getAll("severity").map(String),
    channels: fd.getAll("channel").map(String),
    throttle_seconds: Number(fd.get("throttle_seconds") ?? 0),
    digest_window_seconds: Number(fd.get("digest_window_seconds") ?? 0),
    content,
    advanced_template: String(fd.get("advanced_template") ?? "").trim() || null,
  };
  const res = await postJson("/api/notifications/profiles/save", payload);
  if (!res.ok) go(profileId, "Save failed: " + await responseDetail(res));
  revalidatePath("/notifications/profiles");
  revalidatePath("/notifications/profiles/" + encodeURIComponent(profileId));
  go(profileId, "Notification profile saved");
}

export async function testNotificationProfileAction(fd: FormData): Promise<void> {
  const profileId = String(fd.get("id") ?? "").trim();
  const res = await postJson(
    "/api/notifications/profiles/" + encodeURIComponent(profileId) + "/test",
    {},
  );
  if (!res.ok) go(profileId, "Test failed: " + await responseDetail(res));
  const result = await res.json() as { status?: string; outcomes?: Array<{ channel?: string; status?: string }> };
  const suffix = result.outcomes?.map((item) => String(item.channel) + ": " + String(item.status)).join(", ");
  go(profileId, "Test " + (result.status ?? "finished") + (suffix ? " · " + suffix : ""));
}
