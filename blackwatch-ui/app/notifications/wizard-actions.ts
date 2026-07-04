"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { API_BASE } from "@/lib/api";
import { apiFetch } from "@/lib/server-fetch";

async function bodyOr(fallback: string, res: Response): Promise<string> {
  try {
    return (await res.text()).slice(0, 200) || fallback;
  } catch {
    return fallback;
  }
}

// The wizard submits everything the operator picked in one shot:
//   { id?, module, severities:[], channel, message_template, enabled }
export async function saveAlertRouteAction(fd: FormData): Promise<void> {
  const id = String(fd.get("id") ?? "").trim() || undefined;
  const module = String(fd.get("module") ?? "").trim();
  const channel = String(fd.get("channel") ?? "").trim();
  const severities = fd.getAll("severity").map((s) => String(s));
  const message_template = String(fd.get("message_template") ?? "").trim() || null;
  const enabled = fd.get("enabled") !== "off";

  if (!module) redirect("/notifications?msg=Pick a module first");
  if (!channel) redirect("/notifications?msg=Pick a channel first");
  if (severities.length === 0) {
    redirect("/notifications?msg=Pick at least one severity");
  }

  const res = await apiFetch(`/api/notifications/routes/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id,
      module,
      severities,
      channel,
      message_template,
      enabled,
    }),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await bodyOr("", res);
    redirect(
      `/notifications?msg=${encodeURIComponent(
        `Save failed (${res.status}) ${detail}`,
      )}`,
    );
  }
  revalidatePath("/notifications");
  const label = id ? "Updated" : "Created";
  redirect(
    `/notifications?msg=${encodeURIComponent(
      `${label} — ${severities.join(" + ")} → ${channel}`,
    )}`,
  );
}
