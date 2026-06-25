"use server";

import { revalidatePath } from "next/cache";
import { API_BASE } from "@/lib/api";

export async function deleteVpnServerAction(formData: FormData): Promise<void> {
  const server = String(formData.get("server") ?? "").trim();
  if (!server) return;
  const res = await fetch(
    `${API_BASE}/api/vpn/servers/${encodeURIComponent(server)}`,
    { method: "DELETE", cache: "no-store" },
  );
  if (!res.ok) {
    throw new Error(`delete VPN server failed: ${res.status} ${await res.text()}`);
  }
  revalidatePath("/vpn");
}
