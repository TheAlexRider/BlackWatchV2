"use client";

import { Lock } from "lucide-react";
import { useAuth } from "./AuthProvider";

// Drop this at the top of any page that has mutation controls. Renders
// nothing for admins; shows a compact strip for viewers so they understand
// why the buttons are disabled.
export function ReadOnlyBanner({ message }: { message?: string }) {
  const { role, loading } = useAuth();
  if (loading || role === "admin") return null;
  return (
    <div
      role="status"
      className="mb-3 flex items-center gap-2 border border-line-soft bg-surface-1 px-3 py-1.5 text-xs text-fg-muted"
    >
      <Lock size={12} className="text-fg-subtle" />
      <span>
        {message ?? "Read-only view — mutating actions are disabled for the viewer role."}
      </span>
    </div>
  );
}
