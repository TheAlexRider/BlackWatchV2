import clsx from "clsx";

export type Severity = "critical" | "high" | "medium" | "low" | "resolved" | "neutral";

const COLOR_MAP: Record<Severity, string> = {
  critical: "bg-sev-critical",
  high: "bg-sev-high",
  medium: "bg-sev-medium",
  low: "bg-sev-low",
  resolved: "bg-sev-resolved",
  neutral: "bg-fg-subtle",
};

export function StatusDot({
  severity = "neutral",
  className,
}: {
  severity?: Severity;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={clsx(
        "inline-block h-1.5 w-1.5 shrink-0 rounded-full",
        COLOR_MAP[severity],
        className,
      )}
    />
  );
}
