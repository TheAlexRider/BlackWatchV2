"use client";

import clsx from "clsx";

// Radio-as-card and checkbox-as-card in one primitive. Used anywhere a
// form asks "pick one of these things" (metric, scope, channel) — the
// visible target is a titled card, but the underlying input is a real
// <input type="radio"> or <input type="checkbox"> so FormData + keyboard
// nav + a11y announcements work unmodified.
//
// Consistent visual grammar with the rest of BW: line-soft border,
// surface-2 fill when active, signal color on hover and focus, no
// motion beyond a 150ms color transition.
//
// State (8): default · hover · focus-visible · active (press) · selected
//            · disabled · loading (parent-controlled aria-busy on form) ·
//            error (parent sets `error`). No self-owned loading; the
//            card is passive — its parent form drives async work.
export function SelectableCard({
  type,
  name,
  value,
  checked,
  onChange,
  title,
  description,
  disabled = false,
  error = false,
}: {
  type: "radio" | "checkbox";
  name: string;
  value: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  disabled?: boolean;
  error?: boolean;
}) {
  return (
    <label
      className={clsx(
        "group relative block cursor-pointer rounded border p-3 transition-colors",
        "focus-within:outline-none focus-within:ring-1 focus-within:ring-signal focus-within:ring-offset-2 focus-within:ring-offset-canvas",
        disabled && "cursor-not-allowed opacity-50",
        error
          ? "border-sev-critical"
          : checked
            ? "border-signal bg-surface-2"
            : "border-line-soft bg-canvas hover:border-fg-subtle",
      )}
    >
      <input
        type={type}
        name={name}
        value={value}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="sr-only"
      />
      <div className="flex items-start gap-2">
        <span
          aria-hidden
          className={clsx(
            "mt-1 inline-block h-2 w-2 shrink-0 rounded-full border transition-colors",
            type === "radio" ? "rounded-full" : "rounded-sm",
            checked
              ? "border-signal bg-signal"
              : "border-fg-subtle bg-transparent group-hover:border-fg",
          )}
        />
        <div className="min-w-0 flex-1">
          <div
            className={clsx(
              "text-sm leading-tight",
              checked ? "text-fg" : "text-fg-muted",
            )}
          >
            {title}
          </div>
          {description && (
            <div className="mt-1 text-[11px] leading-snug text-fg-subtle">
              {description}
            </div>
          )}
        </div>
      </div>
    </label>
  );
}
