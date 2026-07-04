"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";
import { CheckCircle2, Loader2, X, XCircle } from "lucide-react";

import type { LaneResult } from "./lane-actions";

// A LANE is one row in the /notifications dashboard. Every alert source —
// module, metric, custom rule, channel — renders as the same visual shape:
//
//   ▎ NAME              → channel    state   meta          ⋮
//
// where the left border is a 2px color-encoded status bar. Clicking the
// row expands an inline editor in place. The visual vocabulary reads like
// signal channels on an oscilloscope — narrow, dense, one-line-of-focus.

export type LaneState = "on" | "off" | "silenced" | "error";

const BORDER: Record<LaneState, string> = {
  on: "border-signal",
  off: "border-line-soft",
  silenced: "border-sev-medium",
  error: "border-sev-critical",
};

const STATE_LABEL: Record<LaneState, { text: string; className: string }> = {
  on: { text: "on", className: "text-signal" },
  off: { text: "off", className: "text-fg-subtle" },
  silenced: { text: "silenced", className: "text-sev-medium" },
  error: { text: "error", className: "text-sev-critical" },
};

export function LaneShell({
  state,
  children,
  className,
}: {
  state: LaneState;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={clsx(
        "border-l-2 border-b border-b-line-soft bg-canvas transition-colors last:border-b-0",
        BORDER[state],
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CollapsedRow({
  open,
  onToggle,
  name,
  hint,
  channel,
  state,
  meta,
  disabled,
}: {
  open: boolean;
  onToggle: () => void;
  name: React.ReactNode;
  hint?: string;
  channel: string | null;
  state: LaneState;
  meta?: React.ReactNode;
  disabled?: boolean;
}) {
  const stateInfo = STATE_LABEL[state];
  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-expanded={open}
      onClick={disabled ? undefined : onToggle}
      onKeyDown={(e) => {
        if (disabled) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onToggle();
        }
      }}
      className={clsx(
        "grid cursor-pointer items-center gap-3 px-3 py-2.5 text-sm transition-colors",
        // Column pattern: name (flex) · arrow-channel (auto) · state (auto)
        // · meta (min 160) · actions (auto). Consistent across every lane so
        // the eye can scan a column top-to-bottom.
        "grid-cols-[1fr_minmax(180px,auto)_60px_minmax(140px,1fr)_28px]",
        "hover:bg-surface-1",
        open && "bg-surface-1",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      {/* NAME */}
      <div className="min-w-0 truncate">
        <span className="text-fg">{name}</span>
        {hint && (
          <span className="ml-2 font-mono text-[10px] text-fg-subtle">
            {hint}
          </span>
        )}
      </div>

      {/* ARROW + CHANNEL */}
      <div className="min-w-0 truncate font-mono text-xs text-fg-muted">
        {channel ? (
          <>
            <span className="text-fg-subtle">→ </span>
            <span>{channel}</span>
          </>
        ) : (
          <span className="text-fg-subtle">not set up</span>
        )}
      </div>

      {/* STATE */}
      <div className={clsx("text-xs", stateInfo.className)}>{stateInfo.text}</div>

      {/* META (condition/threshold summary) */}
      <div className="min-w-0 truncate text-xs text-fg-muted">{meta}</div>

      {/* TOGGLE INDICATOR — no icon, just a subtle marker so the whole row
          reads as the interactive surface. Keeps the visual language flat. */}
      <div className="flex justify-end text-fg-subtle">
        {open ? <X size={12} /> : <span className="text-[16px] leading-none">⋮</span>}
      </div>
    </div>
  );
}

export function ExpandedBody({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="border-t border-line-soft bg-surface-1 px-4 pb-3 pt-3">
      {children}
    </div>
  );
}

// Inline status block for the expanded lane. Auto-clears after 5s.
export function LaneStatus({ status }: { status: NonNullable<LaneResult> }) {
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    setVisible(true);
    const t = setTimeout(() => setVisible(false), 5000);
    return () => clearTimeout(t);
  }, [status.at]);
  if (!visible) return null;
  const Icon = status.ok ? CheckCircle2 : XCircle;
  return (
    <div
      className={clsx(
        "mt-3 flex items-start gap-2 border-l-2 px-3 py-2 text-xs",
        status.ok
          ? "border-sev-resolved/60 bg-sev-resolved/5"
          : "border-sev-critical/60 bg-sev-critical/5",
      )}
    >
      <Icon
        size={13}
        className={clsx(
          "mt-0.5 shrink-0",
          status.ok ? "text-sev-resolved" : "text-sev-critical",
        )}
        aria-hidden
      />
      <span className="text-fg">{status.message}</span>
    </div>
  );
}

// Small mono spinner label — for pending buttons inside expanded editors.
export function Spinner({ label }: { label: string }) {
  return (
    <>
      <Loader2 size={12} className="animate-spin" />
      <span>{label}</span>
    </>
  );
}

// Pick the "latest" of several action results by their .at timestamp — used
// to render one inline status when a lane has multiple action forms.
export function latestResult(
  ...results: (LaneResult | null)[]
): NonNullable<LaneResult> | null {
  let best: NonNullable<LaneResult> | null = null;
  for (const r of results) {
    if (!r) continue;
    if (!best || r.at > best.at) best = r;
  }
  return best;
}

// Compute the display state for a lane given raw fields. Shared so all
// three lane types (module / metric / custom) map to the same LaneState.
export function computeLaneState({
  hasChannel,
  enabled,
  silenceUntilIso,
}: {
  hasChannel: boolean;
  enabled: boolean;
  silenceUntilIso?: string | null;
}): LaneState {
  if (!hasChannel) return "off";
  if (silenceUntilIso) {
    const until = new Date(silenceUntilIso).getTime();
    if (until > Date.now()) return "silenced";
  }
  if (!enabled) return "off";
  return "on";
}
