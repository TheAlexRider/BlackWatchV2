"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { API_BASE } from "@/lib/api";
import { apiFetch } from "@/lib/server-fetch";

// The existing FastAPI Jinja-era endpoints accept form-urlencoded bodies and
// return 303 redirects. We POST to them server-side, ignore the redirect, and
// drive our own UI revalidation + flash message.

async function postForm(path: string, body: Record<string, string>): Promise<void> {
  const form = new URLSearchParams(body);
  const res = await apiFetch(`${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
    redirect: "manual",
    cache: "no-store",
  });
  // FastAPI's redirect responses come back as 3xx; treat them as success.
  if (res.status >= 400) {
    throw new Error(`${path} failed: ${res.status} ${await res.text()}`);
  }
}

function connectorsRedirect(msg: string): never {
  redirect(`/connectors?msg=${encodeURIComponent(msg)}`);
}

// --- per-connector actions ------------------------------------------------

export async function testConnectorAction(formData: FormData): Promise<void> {
  const id = String(formData.get("connector_id") ?? "");
  if (!id) return;
  await postForm(`/ui/connectors/${encodeURIComponent(id)}/test`, {});
  revalidatePath("/connectors");
  connectorsRedirect(`tested ${id}`);
}

export async function runConnectorAction(formData: FormData): Promise<void> {
  const id = String(formData.get("connector_id") ?? "");
  if (!id) return;
  await postForm(`/ui/connectors/${encodeURIComponent(id)}/run`, {});
  revalidatePath("/connectors");
  connectorsRedirect(`ran ${id}`);
}

export async function toggleConnectorAction(formData: FormData): Promise<void> {
  const id = String(formData.get("connector_id") ?? "");
  const enabled = formData.get("enabled") === "on";
  if (!id) return;
  await postForm(`/ui/connectors/${encodeURIComponent(id)}/toggle`, {
    enabled: enabled ? "on" : "off",
  });
  revalidatePath("/connectors");
  connectorsRedirect(`${id} ${enabled ? "enabled" : "disabled"}`);
}

export async function deleteConnectorAction(formData: FormData): Promise<void> {
  const id = String(formData.get("connector_id") ?? "");
  if (!id) return;
  await postForm(`/ui/connectors/${encodeURIComponent(id)}/delete`, {});
  revalidatePath("/connectors");
  connectorsRedirect(`deleted ${id}`);
}

// --- save (4 connector types) ---------------------------------------------

function formToBody(formData: FormData): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of formData.entries()) {
    out[k] = String(v);
  }
  return out;
}

export async function saveCloudTrailSqsAction(formData: FormData): Promise<void> {
  await postForm("/ui/connectors/save_aws", formToBody(formData));
  revalidatePath("/connectors");
  connectorsRedirect("saved (test to verify, then enable)");
}

export async function saveEcsHealthAction(formData: FormData): Promise<void> {
  await postForm("/ui/connectors/save_aws_ecs", formToBody(formData));
  revalidatePath("/connectors");
  connectorsRedirect("saved (test to verify, then enable)");
}

export async function saveS3DriftAction(formData: FormData): Promise<void> {
  await postForm("/ui/connectors/save_aws_s3", formToBody(formData));
  revalidatePath("/connectors");
  connectorsRedirect("saved (test to verify, then enable)");
}

export async function savePostureDriftAction(formData: FormData): Promise<void> {
  await postForm("/ui/connectors/save_aws_posture", formToBody(formData));
  revalidatePath("/connectors");
  connectorsRedirect("saved (test to verify, then enable)");
}

export async function saveCertProbeAction(formData: FormData): Promise<void> {
  await postForm("/ui/connectors/save_cert_probe", formToBody(formData));
  revalidatePath("/connectors");
  connectorsRedirect("saved (test to verify, then enable)");
}
