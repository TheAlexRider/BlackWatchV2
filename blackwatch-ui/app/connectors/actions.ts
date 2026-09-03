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

async function postJson(path: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
  const res = await apiFetch(`${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`${path} failed: ${res.status} ${await res.text()}`);
  }
  return (await res.json()) as Record<string, unknown>;
}

function connectorsRedirect(msg: string): never {
  redirect(`/connectors?msg=${encodeURIComponent(msg)}`);
}

// --- per-connector actions ------------------------------------------------

export async function testConnectorAction(formData: FormData): Promise<void> {
  const id = String(formData.get("connector_id") ?? "");
  if (!id) return;
  await postJson(`/api/connectors/${encodeURIComponent(id)}/test`, {});
  revalidatePath("/connectors");
  connectorsRedirect(`tested ${id}`);
}

export async function runConnectorAction(formData: FormData): Promise<void> {
  const id = String(formData.get("connector_id") ?? "");
  if (!id) return;
  await postJson(`/api/connectors/${encodeURIComponent(id)}/run`, {});
  revalidatePath("/connectors");
  connectorsRedirect(`ran ${id}`);
}

export async function startConnectorOperationAction(
  connectorId: string,
  kind: "manual" | "test" = "manual",
): Promise<Record<string, unknown>> {
  try {
    return await postJson(`/api/connectors/${encodeURIComponent(connectorId)}/run`, { kind });
  } catch (error) {
    return {
      accepted: false,
      status: "rejected",
      error: error instanceof Error ? error.message : "operation could not be queued",
    };
  }
}

export async function getConnectorOperationAction(
  operationId: string,
): Promise<Record<string, unknown> | null> {
  const res = await apiFetch(`/api/connector-operations/${encodeURIComponent(operationId)}`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) return null;
  return (await res.json()) as Record<string, unknown>;
}

export async function retryAllConnectorsAction(
  scope: "eligible" | "all" = "eligible",
): Promise<Record<string, unknown>> {
  try {
    return await postJson("/api/connectors/retry-all", { scope });
  } catch (error) {
    return {
      accepted: false,
      status: "rejected",
      error: error instanceof Error ? error.message : "Retry All could not be queued",
    };
  }
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

export async function saveS3AccessLogsAction(formData: FormData): Promise<void> {
  await postForm("/ui/connectors/save_aws_s3_access", formToBody(formData));
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
