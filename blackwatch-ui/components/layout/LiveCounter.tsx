"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";

// Polls /api/live/ping every few seconds. The pulsing dot stops when polling
// fails — gives the operator a real "system is alive" cue, not theatre.
//
// Pause behavior: if the tab is in the background, polling stops to avoid
// burning backend calls for nobody.

type ConnState = "connecting" | "live" | "stale";

const POLL_MS = 5_000;
const STALE_AFTER_MS = 20_000;

export function LiveCounter() {
  const [eps, setEps] = useState<number | null>(null);
  const [state, setState] = useState<ConnState>("connecting");

  useEffect(() => {
    if (typeof document === "undefined") return;
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    let lastOkAt = 0;

    async function tick() {
      try {
        const res = await fetch("/api/live/ping", { cache: "no-store" });
        if (!res.ok) throw new Error(`http ${res.status}`);
        const data = (await res.json()) as { eps: number };
        if (cancelled) return;
        setEps(data.eps);
        setState("live");
        lastOkAt = Date.now();
      } catch {
        if (cancelled) return;
        if (Date.now() - lastOkAt > STALE_AFTER_MS) setState("stale");
      }
    }

    const start = () => {
      if (timer !== null) return;
      void tick();
      timer = setInterval(tick, POLL_MS);
    };
    const stop = () => {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };
    const onVisibility = () => {
      if (document.hidden) stop();
      else start();
    };

    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelled = true;
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  const display =
    eps === null
      ? "—"
      : eps < 10
        ? eps.toFixed(2)
        : Math.round(eps).toString();

  const dotClass =
    state === "live"
      ? "bg-signal animate-signal-pulse"
      : state === "connecting"
        ? "bg-fg-subtle animate-signal-pulse"
        : "bg-sev-critical";

  const title =
    state === "live"
      ? `${eps?.toFixed(2)} events/sec over last 60 s`
      : state === "stale"
        ? "Live ping failing — backend may be unreachable"
        : "Connecting…";

  return (
    <div
      className="flex items-center gap-2 font-mono text-[11px] text-fg-muted"
      title={title}
    >
      <span aria-hidden className={clsx("h-1.5 w-1.5 rounded-full", dotClass)} />
      <span className="tabular-nums">{display}/s</span>
    </div>
  );
}
