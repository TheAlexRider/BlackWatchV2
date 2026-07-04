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
  redirect(`/notifications/routing?msg=${encodeURIComponent(msg)}`);
}

export async function saveCardAction(fd: FormData): Promise<void> {
  const module = String(fd.get("module") ?? "");
  if (!module) return;
  const payload = {
    enabled: fd.get("enabled") === "on",
    channel: String(fd.get("channel") ?? "").trim() || null,
    threshold: String(fd.get("threshold") ?? "high"),
  };
  const res = await postJson(
    `/api/notifications/cards/${encodeURIComponent(module)}/save`,
    payload,
  );
  if (!res.ok) throw new Error(`saveCard failed: ${res.status} ${await res.text()}`);
  revalidatePath("/notifications/routing");
  revalidatePath("/notifications");
  done(payload.channel ? `saved ${module}` : `${module} turned off`);
}

export async function toggleCardAction(fd: FormData): Promise<void> {
  const module = String(fd.get("module") ?? "");
  const channel = String(fd.get("channel") ?? "").trim() || null;
  const threshold = String(fd.get("threshold") ?? "high");
  const enabled = fd.get("target") === "on";
  if (!module) return;
  const res = await postJson(
    `/api/notifications/cards/${encodeURIComponent(module)}/save`,
    { enabled, channel, threshold },
  );
  if (!res.ok) throw new Error(`toggleCard failed: ${res.status}`);
  revalidatePath("/notifications/routing");
  revalidatePath("/notifications");
  done(`${module} ${enabled ? "on" : "off"}`);
}

export async function testCardAction(fd: FormData): Promise<void> {
  const module = String(fd.get("module") ?? "");
  if (!module) return;
  const res = await postJson(
    `/api/notifications/cards/${encodeURIComponent(module)}/test`,
    {},
  );
  if (!res.ok) throw new Error(`testCard failed: ${res.status}`);
  const data = (await res.json()) as { status?: string; detail?: string };
  revalidatePath("/notifications/routing");
  done(
    `${module} test: ${data.status ?? "?"}${data.detail ? ` · ${data.detail}` : ""}`,
  );
}

export async function silenceCardAction(fd: FormData): Promise<void> {
  const module = String(fd.get("module") ?? "");
  const hours = Number(fd.get("hours") ?? 0);
  if (!module) return;
  const res = await postJson(
    `/api/notifications/cards/${encodeURIComponent(module)}/silence`,
    { hours },
  );
  if (!res.ok) throw new Error(`silenceCard failed: ${res.status}`);
  revalidatePath("/notifications/routing");
  done(hours > 0 ? `${module} silenced ${hours}h` : `${module} silence cleared`);
}
