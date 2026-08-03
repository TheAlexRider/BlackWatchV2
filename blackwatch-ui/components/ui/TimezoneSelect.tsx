"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Check } from "lucide-react";

export type TzKey = "UTC" | "PST" | "IST";

// IANA zone per label — Intl uses these for actual TZ math (handles DST for PST).
export const TZ_ZONE: Record<TzKey, string> = {
  UTC: "UTC",
  PST: "America/Los_Angeles",
  IST: "Asia/Kolkata",
};

const TZ_OPTIONS: TzKey[] = ["UTC", "PST", "IST"];

// Compact BW-styled dropdown. Persists selection in localStorage so the
// operator's TZ preference sticks across page loads.
export function TimezoneSelect({
  value,
  onChange,
  storageKey,
}: {
  value: TzKey;
  onChange: (v: TzKey) => void;
  storageKey?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    window.addEventListener("mousedown", handler);
    return () => window.removeEventListener("mousedown", handler);
  }, [open]);

  function select(v: TzKey) {
    onChange(v);
    setOpen(false);
    if (storageKey) {
      try {
        window.localStorage.setItem(storageKey, v);
      } catch {}
    }
  }

  return (
    <div ref={rootRef} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 border border-line-soft bg-canvas px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-fg-subtle hover:text-fg"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {value}
        <ChevronDown size={10} />
      </button>
      {open && (
        <ul
          role="listbox"
          className="absolute right-0 z-10 mt-1 min-w-[80px] border border-line-soft bg-surface-1 shadow-lg"
        >
          {TZ_OPTIONS.map((tz) => (
            <li key={tz} role="option" aria-selected={value === tz}>
              <button
                type="button"
                onClick={() => select(tz)}
                className={
                  "flex w-full items-center gap-1.5 px-2 py-1 text-left text-[10px] uppercase tracking-[0.08em] hover:bg-surface-2 " +
                  (value === tz ? "text-fg" : "text-fg-subtle")
                }
              >
                {value === tz ? (
                  <Check size={10} className="text-signal" />
                ) : (
                  <span className="inline-block w-[10px]" />
                )}
                {tz}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Format helpers ------------------------------------------------------------

/** "Nov 12, 14:00" style — for axis ticks. Long ranges add the date; ≤24h
 * hides it to keep ticks readable. */
export function formatAxisTick(ts: number, tz: TzKey, showDate: boolean): string {
  const d = new Date(ts * 1000);
  const zone = TZ_ZONE[tz];
  const time = d.toLocaleTimeString("en-US", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  if (!showDate) return time;
  const date = d.toLocaleDateString("en-US", {
    timeZone: zone,
    month: "short",
    day: "numeric",
  });
  return `${date} ${time}`;
}

/** Full "Mon Nov 12 · 14:00 PST" for tooltip header. */
export function formatTooltipStamp(ts: number, tz: TzKey): string {
  const d = new Date(ts * 1000);
  const zone = TZ_ZONE[tz];
  const date = d.toLocaleDateString("en-US", {
    timeZone: zone,
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  const time = d.toLocaleTimeString("en-US", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return `${date} · ${time} ${tz}`;
}
