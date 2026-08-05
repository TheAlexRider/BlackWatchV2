"use client";

import { useState, useId } from "react";
import clsx from "clsx";
import { ChevronRight } from "lucide-react";

// Collapsible section with a caret + label trigger. Used anywhere a form
// has an optional-detail area (advanced settings, custom message template,
// per-rule overrides). Consistent with the rest of BW: text-fg-subtle
// uppercase micro-label, focus ring in signal color, no motion beyond a
// 150ms caret rotate — matches the "forensic minimalism" aesthetic.
//
// State (8): default · hover · focus-visible · active (press) · open
//            · closed · disabled — collapse never has loading/error/success,
//            those live on the children.
export function Disclosure({
  label,
  defaultOpen = false,
  disabled = false,
  children,
}: {
  label: string;
  defaultOpen?: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState<boolean>(defaultOpen);
  const panelId = useId();

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => !disabled && setOpen((s) => !s)}
        aria-expanded={open}
        aria-controls={panelId}
        disabled={disabled}
        className={clsx(
          "group inline-flex items-center gap-1.5 rounded text-[11px] uppercase tracking-[0.08em] transition-colors",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-sig-teal focus-visible:ring-offset-2 focus-visible:ring-offset-canvas",
          disabled
            ? "cursor-not-allowed text-fg-disabled"
            : "text-fg-subtle hover:text-fg active:text-fg",
        )}
      >
        <ChevronRight
          size={12}
          strokeWidth={2}
          className={clsx(
            "transition-transform duration-150",
            open && "rotate-90",
          )}
        />
        <span>{label}</span>
      </button>
      {/* Keep children mounted when collapsed so form fields inside them
          still contribute to FormData on submit — hide visually via
          `hidden`. Screen readers get correct aria-expanded semantics. */}
      <div id={panelId} className="pl-4" hidden={!open}>
        {children}
      </div>
    </div>
  );
}
