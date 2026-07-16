import clsx from "clsx";

type SeverityKey =
  | "critical"
  | "high"
  | "medium"
  | "low"
  | "informational"
  | string;

const CHIP_CLASS: Record<string, string> = {
  critical: "bg-sev-critical/15 text-sev-critical border-sev-critical/40",
  high: "bg-sev-high/15 text-sev-high border-sev-high/40",
  medium: "bg-sev-medium/15 text-sev-medium border-sev-medium/40",
  low: "bg-sev-low/15 text-sev-low border-sev-low/40",
  informational: "bg-fg-subtle/15 text-fg-muted border-fg-subtle/40",
};

const SHORT_LABEL: Record<string, string> = {
  informational: "info",
};

export function severityChipClass(severity: string): string {
  return CHIP_CLASS[severity] ?? CHIP_CLASS.informational;
}

export function SeverityChip({
  severity,
  className,
}: {
  severity: SeverityKey;
  className?: string;
}) {
  const label = SHORT_LABEL[severity] ?? severity;
  return (
    <span
      className={clsx(
        "border px-1.5 py-0.5 font-mono text-[10px]",
        severityChipClass(severity),
        className,
      )}
    >
      {label}
    </span>
  );
}
