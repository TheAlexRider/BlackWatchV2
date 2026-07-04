"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";
import { CheckCircle2, AlertTriangle, XCircle, Info, X } from "lucide-react";

type Kind = "success" | "error" | "warning" | "info";

// Classify by string smell. Server actions redirect with human-written msgs
// so we sniff obvious keywords instead of piping a structured kind through
// the URL.
function classify(msg: string): Kind {
  const m = msg.toLowerCase();
  if (/\btest:\s*sent\b/.test(m)) return "success";
  if (
    /\b(error|failed|unknown|invalid|no[_-]channel|no channel|denied)\b/.test(m)
  )
    return "error";
  if (/\b(warn|silenced|throttled|rate[_-]limited)\b/.test(m)) return "warning";
  if (
    /\b(saved|created|deleted|cleared|enabled|disabled|updated|off|on|test:)\b/.test(
      m,
    )
  )
    return "success";
  return "info";
}

const STYLES: Record<Kind, { bar: string; icon: React.ComponentType<{ size?: number; className?: string }>; iconClass: string }> = {
  success: {
    bar: "border-sev-resolved/40 bg-sev-resolved/10",
    icon: CheckCircle2,
    iconClass: "text-sev-resolved",
  },
  error: {
    bar: "border-sev-critical/50 bg-sev-critical/10",
    icon: XCircle,
    iconClass: "text-sev-critical",
  },
  warning: {
    bar: "border-sev-medium/50 bg-sev-medium/10",
    icon: AlertTriangle,
    iconClass: "text-sev-medium",
  },
  info: {
    bar: "border-signal/40 bg-signal/10",
    icon: Info,
    iconClass: "text-signal",
  },
};

// Prominent flash toast fed by ?msg=... URL params.
//
// Why client + auto-hide: the message stays in the URL until the user
// navigates or refreshes. Without auto-hide, stale banners linger. 4s is
// long enough to read, short enough not to feel sticky.
export function FlashToast({
  message,
  ttlMs = 4500,
}: {
  message: string;
  ttlMs?: number;
}) {
  const [visible, setVisible] = useState(true);
  const kind = classify(message);
  const style = STYLES[kind];
  const Icon = style.icon;

  useEffect(() => {
    const t = setTimeout(() => setVisible(false), ttlMs);
    return () => clearTimeout(t);
  }, [ttlMs]);

  if (!visible) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className={clsx(
        "mb-4 flex items-start justify-between gap-3 border-l-4 border px-4 py-3 text-sm",
        style.bar,
      )}
    >
      <div className="flex items-start gap-2.5">
        <Icon
          size={16}
          className={clsx("mt-0.5 shrink-0", style.iconClass)}
          aria-hidden
        />
        <span className="text-fg">{message}</span>
      </div>
      <button
        type="button"
        onClick={() => setVisible(false)}
        className="shrink-0 text-fg-subtle transition-colors hover:text-fg"
        aria-label="Dismiss"
      >
        <X size={14} />
      </button>
    </div>
  );
}
