"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { API_BASE } from "@/lib/api";

const COOKIE_NAME = "bw_session";

async function bodyOr(fallback: string, res: Response): Promise<string> {
  try {
    const t = (await res.text()).slice(0, 200);
    return t || fallback;
  } catch {
    return fallback;
  }
}

export async function changePasswordAction(fd: FormData): Promise<void> {
  const current = String(fd.get("current_password") ?? "");
  const next = String(fd.get("new_password") ?? "");
  const confirm = String(fd.get("confirm_password") ?? "");

  if (!current || !next) {
    redirect(
      `/settings?msg=${encodeURIComponent(
        "Enter your current and new password",
      )}`,
    );
  }
  if (next !== confirm) {
    redirect(
      `/settings?msg=${encodeURIComponent("New password and confirmation don't match")}`,
    );
  }
  if (next.length < 8) {
    redirect(
      `/settings?msg=${encodeURIComponent("New password must be at least 8 characters")}`,
    );
  }

  const sid = (await cookies()).get(COOKIE_NAME)?.value;
  const res = await fetch(`${API_BASE}/api/auth/change-password`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      // Server-side fetch doesn't automatically forward the browser's
      // cookie — we have to attach it explicitly. Backend uses this to
      // identify the current user.
      ...(sid ? { Cookie: `${COOKIE_NAME}=${sid}` } : {}),
    },
    body: JSON.stringify({ current_password: current, new_password: next }),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await bodyOr("", res);
    redirect(
      `/settings?msg=${encodeURIComponent(
        `Password change failed (${res.status}) ${detail}`,
      )}`,
    );
  }
  redirect(`/settings?msg=${encodeURIComponent("Password changed")}`);
}
