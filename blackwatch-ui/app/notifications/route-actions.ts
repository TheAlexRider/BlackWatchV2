"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { API_BASE } from "@/lib/api";

// Row-level quick actions on /notifications. Each returns via a redirect
// with a ?msg=… so the page can show a flash toast; the wizard route (for
// full edit / create) is a separate page and doesn't use these.

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
    return (await res.text()).slice(0, 200) || fallback;
  } catch {
    return fallback;
  }
}

function done(msg: string): never {
  redirect(`/notifications?msg=${encodeURIComponent(msg)}`);
}

export async function toggleRouteAction(fd: FormData): Promise<void> {
  const id = String(fd.get("id") ?? "").trim();
  const enabled = fd.get("target") === "on";
  if (!id) done("Missing route id");
  const res = await postJson(
    `/api/notifications/routes/${encodeURIComponent(id)}/toggle`,
    { enabled },
  );
  if (!res.ok) done(`Toggle failed (${res.status}) ${await bodyOr("", res)}`);
  revalidatePath("/notifications");
  done(enabled ? "Turned on" : "Turned off");
}

export async function silenceRouteAction(fd: FormData): Promise<void> {
  const id = String(fd.get("id") ?? "").trim();
  const hours = Number(fd.get("hours") ?? 0);
  if (!id) done("Missing route id");
  const res = await postJson(
    `/api/notifications/routes/${encodeURIComponent(id)}/silence`,
    { hours },
  );
  if (!res.ok) done(`Silence failed (${res.status}) ${await bodyOr("", res)}`);
  revalidatePath("/notifications");
  done(hours > 0 ? `Silenced for ${hours}h` : "Silence cleared");
}

export async function deleteRouteAction(fd: FormData): Promise<void> {
  const id = String(fd.get("id") ?? "").trim();
  if (!id) done("Missing route id");
  const res = await fetch(
    `${API_BASE}/api/notifications/routes/${encodeURIComponent(id)}`,
    { method: "DELETE", cache: "no-store" },
  );
  if (!res.ok) done(`Delete failed (${res.status}) ${await bodyOr("", res)}`);
  revalidatePath("/notifications");
  done("Route deleted");
}

export async function testRouteAction(fd: FormData): Promise<void> {
  const channel = String(fd.get("channel") ?? "").trim();
  if (!channel) done("No channel to test");
  const listRes = await fetch(`${API_BASE}/api/notifications/channels`, {
    cache: "no-store",
  });
  if (!listRes.ok) done("Could not load channels");
  const j = await listRes.json();
  const found = (j.channels || []).find(
    (c: { name: string }) => c.name === channel,
  );
  if (!found) done(`Channel ${channel} not found`);
  const res = await postJson(
    `/api/notifications/channels/${encodeURIComponent(found.id)}/test`,
    {},
  );
  if (!res.ok) done(`Test failed (${res.status}) ${await bodyOr("", res)}`);
  const data = (await res.json()) as { status?: string; detail?: string };
  const success = data.status === "sent";
  done(
    success
      ? `Sent to ${channel}${data.detail ? ` · ${data.detail}` : ""}`
      : `Test: ${data.status}${data.detail ? ` · ${data.detail}` : ""}`,
  );
}

// Wizard-related actions live in ./wizard-actions.ts so a redirect from
// there doesn't collide with any imports here.
