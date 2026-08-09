"use client";

// Client-side auth context. Reads /api/whoami on mount so pages/components
// can hide mutating controls when the current user is a viewer.
//
// Fail-closed: any error resolves to role='viewer'. The backend is the
// authority — this context only decides what to render.

import { createContext, useContext, useEffect, useState } from "react";

export type Role = "admin" | "viewer";

export interface AuthState {
  user: string | null;
  role: Role;
  loading: boolean;
}

const defaultState: AuthState = { user: null, role: "viewer", loading: true };

const AuthContext = createContext<AuthState>(defaultState);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>(defaultState);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/whoami", { cache: "no-store", credentials: "include" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((j: { user: string; role: Role }) => {
        if (cancelled) return;
        setState({
          user: j.user ?? null,
          role: j.role === "admin" ? "admin" : "viewer",
          loading: false,
        });
      })
      .catch(() => {
        if (!cancelled) setState({ user: null, role: "viewer", loading: false });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  return useContext(AuthContext);
}
