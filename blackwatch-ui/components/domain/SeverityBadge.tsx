import clsx from "clsx";

type SeverityKey =
  | "critical"
  | "high"
  | "medium"
  | "low"
  | "informational"
  | "unscored"
  | "resolved"
  | string;

const DOT_CLASS: Record<string, string> = {
  critical: "bg-sev-critical",
  high: "bg-sev-high",
  medium: "bg-sev-medium",
  low: "bg-sev-low",
  informational: "bg-sev-low",
  resolved: "bg-sev-resolved",
  unscored: "bg-fg-subtle",
};

const LABEL: Record<string, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  informational: "Info",
  resolved: "Resolved",
  unscored: "Unscored",
};

export function SeverityBadge({
  severity,
}: {
  severity: SeverityKey | null | undefined;
}) {
  const key = severity ?? "unscored";
  const dot = DOT_CLASS[key] ?? "bg-fg-subtle";
  const label = LABEL[key] ?? key;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", dot)} aria-hidden />
      <span className="text-fg-muted">{label}</span>
    </span>
  );
}

/** Tailwind class for severity left-border on rows. */
export function severityBorderBg(severity: SeverityKey | null | undefined): string {
  const key = severity ?? "unscored";
  switch (key) {
    case "critical":
      return "bg-sev-critical";
    case "high":
      return "bg-sev-high";
    case "medium":
      return "bg-sev-medium";
    case "low":
    case "informational":
      return "bg-sev-low";
    case "resolved":
      return "bg-sev-resolved";
    default:
      return "bg-transparent";
  }
}
