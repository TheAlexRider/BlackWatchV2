"use client";

import { useEffect, useId, useState } from "react";
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
  open: controlledOpen,
  onOpenChange,
  children,
}: {
  storageKey: string;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  count?: number;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const [hydrated, setHydrated] = useState(false);
  const panelId = `collapsible-${useId().replace(/:/g, "")}`;
  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : internalOpen;

  useEffect(() => {
    if (isControlled) {
      setHydrated(true);
      return;
    }
    try {
      const v = window.localStorage.getItem(storageKey);
      if (v === "0") setInternalOpen(false);
      else if (v === "1") setInternalOpen(true);
    } catch {}
    setHydrated(true);
  }, [isControlled, storageKey]);

  useEffect(() => {
    if (!hydrated || isControlled) return;
    try {
      window.localStorage.setItem(storageKey, open ? "1" : "0");
    } catch {}
  }, [open, storageKey, hydrated, isControlled]);

  function toggle() {
    const next = !open;
    if (!isControlled) setInternalOpen(next);
    onOpenChange?.(next);
  }

  return (
    <div className="mb-3 border border-line-soft bg-surface-1">
      <button
        type="button"
        onClick={toggle}
        className="flex w-full items-center gap-2 border-b border-line-soft px-3 py-2 text-left transition-colors hover:bg-surface-2"
        aria-expanded={open}
        aria-controls={panelId}
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
      <div id={panelId} hidden={!open}>
        {children}
      </div>
    </div>
  );
}
