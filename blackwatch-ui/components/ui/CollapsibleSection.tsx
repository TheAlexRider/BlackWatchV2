"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

// Collapsible group wrapper. Persists open/closed per `storageKey` in
// localStorage so operator's grouping state survives navigations.
// Defaults to open on first visit.
export function CollapsibleSection({
  storageKey,
  title,
  subtitle,
  count,
  defaultOpen = true,
  children,
}: {
  storageKey: string;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  count?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const v = window.localStorage.getItem(storageKey);
      if (v === "0") setOpen(false);
      else if (v === "1") setOpen(true);
    } catch {}
    setHydrated(true);
  }, [storageKey]);

  useEffect(() => {
    if (!hydrated) return;
    try {
      window.localStorage.setItem(storageKey, open ? "1" : "0");
    } catch {}
  }, [open, storageKey, hydrated]);

  return (
    <div className="mb-3 border border-line-soft bg-surface-1">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 border-b border-line-soft px-3 py-2 text-left transition-colors hover:bg-surface-2"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown size={12} className="text-fg-subtle" />
        ) : (
          <ChevronRight size={12} className="text-fg-subtle" />
        )}
        <span className="text-xs uppercase tracking-[0.1em] text-fg">
          {title}
        </span>
        {typeof count === "number" && (
          <span className="font-mono text-[10px] text-fg-subtle">
            [{count}]
          </span>
        )}
        {subtitle && (
          <span className="ml-2 text-[11px] text-fg-subtle">{subtitle}</span>
        )}
      </button>
      {open && <div>{children}</div>}
    </div>
  );
}
