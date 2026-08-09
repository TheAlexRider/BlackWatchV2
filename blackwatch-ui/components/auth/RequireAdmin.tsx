"use client";

// Render children only if the current user's role === 'admin'.
// Wrap every mutation button / form / edit-delete control with this.
// Backend enforces the actual gate; this just hides UI a viewer can't use.

import { useAuth } from "./AuthProvider";

export function RequireAdmin({
  children,
  fallback = null,
}: {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const { role, loading } = useAuth();
  if (loading) return null;
  if (role !== "admin") return <>{fallback}</>;
  return <>{children}</>;
}
