"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { apiFetch } from "@/lib/server-fetch";

// Server actions for /rds allowlist management. Returns via redirect(?msg=…)
// so the page can show a flash toast on the next render.

function done(msg: string): never {
  redirect(`/rds?msg=${encodeURIComponent(msg)}`);
}

async function bodyOr(fallback: string, res: Response): Promise<string> {
  try {
    return (await res.text()).slice(0, 200) || fallback;
  } catch {
    return fallback;
  }
}

export async function addAllowlistUserAction(fd: FormData): Promise<void> {
  const username = String(fd.get("username") ?? "").trim();
  const kind = String(fd.get("kind") ?? "").trim();
  const note = String(fd.get("note") ?? "").trim() || null;

  if (!username) done("Enter a username");
  if (kind !== "human" && kind !== "service") done("Pick human or service");

  const res = await apiFetch(`/api/rds/allowlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, kind, note }),
    cache: "no-store",
  });
  if (!res.ok) done(`Add failed (${res.status}) ${await bodyOr("", res)}`);
  revalidatePath("/rds");
  done(`Added ${username} · ${kind}`);
}

export async function removeAllowlistUserAction(fd: FormData): Promise<void> {
  const username = String(fd.get("username") ?? "").trim();
  if (!username) done("Missing username");
  const res = await apiFetch(
    `/api/rds/allowlist/${encodeURIComponent(username)}`,
    { method: "DELETE", cache: "no-store" },
  );
  if (!res.ok) done(`Remove failed (${res.status}) ${await bodyOr("", res)}`);
  revalidatePath("/rds");
  done(`Removed ${username}`);
}
