"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Calls router.refresh() on a fixed interval. Drop one of these into any
// page that should auto-update. Server components re-fetch transparently;
// the user sees no flicker because React reconciles the new tree.
//
// Pick the interval based on how fresh the surface needs to feel:
//   - /events, /notifications activity tail:        5_000
//   - /hosts heartbeats, /services probe results:  15_000
//   - /aws-posture findings:                        30_000
//
// All polling is over normal HTTP — works behind any reverse proxy. No SSE,
// no WebSocket, no nginx tweak needed.
export function AutoRefresh({ intervalMs = 5000 }: { intervalMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (typeof document === "undefined") return;

    let timer: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (timer !== null) return;
      timer = setInterval(() => router.refresh(), intervalMs);
    };
    const stop = () => {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };
    const onVisibility = () => {
      // Pause polling when the tab is in the background — saves a bunch of
      // backend calls when the operator has the dashboard open in a tab.
      if (document.hidden) stop();
      else start();
    };

    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [router, intervalMs]);

  return null;
}
