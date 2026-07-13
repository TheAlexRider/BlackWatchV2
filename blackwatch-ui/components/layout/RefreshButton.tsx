"use client";

import { useState, useTransition, useEffect } from "react";
import { useRouter } from "next/navigation";
import clsx from "clsx";
import { RefreshCw } from "lucide-react";

import { refreshModules } from "@/lib/api";

// Small module-page action: click → immediately drain the named connector
// type(s), then re-fetch page data. Complements AutoRefresh (which polls on
// an interval) for when the operator wants freshness *now* rather than in
// 15s. If connectorTypes is empty, it just refreshes the page data without
// touching the backend — useful for pages whose data source has no BW
// connector (e.g. host agent-driven).
//
// State: idle → running (spinner) → flash "ingested N" for ~2s → idle.
// Errors: flash "failed" for ~4s.
export function RefreshButton({
  connectorTypes = [],
  label = "Refresh",
}: {
  connectorTypes?: string[];
  label?: string;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<
    { kind: "ok" | "err"; message: string } | null
  >(null);

  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(
      () => setFlash(null),
      flash.kind === "ok" ? 2000 : 4000,
    );
    return () => clearTimeout(t);
  }, [flash]);

  const active = busy || isPending;

  async function onClick() {
    if (active) return;
    setBusy(true);
    setFlash(null);
    try {
      if (connectorTypes.length > 0) {
        const result = await refreshModules(connectorTypes);
        const ingested = result.total_ingested;
        const errors = result.ran.filter((r) => r.status !== "ok");
        if (errors.length > 0) {
          setFlash({
            kind: "err",
            message:
              errors[0].error ??
              `${errors.length} connector${errors.length === 1 ? "" : "s"} errored`,
          });
        } else if (result.ran.length === 0) {
          setFlash({ kind: "ok", message: "no connectors matched" });
        } else {
          setFlash({
            kind: "ok",
            message:
              ingested === 0
                ? "already fresh"
                : `+${ingested} event${ingested === 1 ? "" : "s"}`,
          });
        }
      }
      startTransition(() => router.refresh());
    } catch (e) {
      setFlash({
        kind: "err",
        message: e instanceof Error ? e.message : "refresh failed",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="inline-flex items-center gap-2">
      <button
        type="button"
        onClick={onClick}
        disabled={active}
        aria-label={label}
        aria-busy={active}
        title={
          connectorTypes.length > 0
            ? `Run ${connectorTypes.join(", ")} now, then reload`
            : "Reload page data"
        }
        className={clsx(
          "inline-flex items-center gap-1.5 rounded border px-2 py-1 text-[11px] uppercase tracking-wider transition-colors",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-sig-teal",
          active
            ? "cursor-wait border-line-soft text-fg-subtle"
            : "border-line-soft text-fg-muted hover:border-sig-teal hover:text-sig-teal",
        )}
      >
        <RefreshCw
          size={12}
          strokeWidth={1.75}
          className={clsx(active && "animate-spin")}
        />
        <span>{active ? "Running" : label}</span>
      </button>
      {flash && (
        <span
          role="status"
          aria-live="polite"
          className={clsx(
            "font-mono text-[11px] transition-opacity",
            flash.kind === "ok" ? "text-sig-teal" : "text-sev-critical",
          )}
        >
          {flash.message}
        </span>
      )}
    </div>
  );
}
