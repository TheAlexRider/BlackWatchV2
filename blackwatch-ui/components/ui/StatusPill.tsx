import clsx from "clsx";
import { StatusDot, type Severity } from "./StatusDot";

/** Inline status label used in tables and compact summaries. */
export function StatusPill({
  label,
  severity = "neutral",
  title,
  className,
}: {
  label: React.ReactNode;
  severity?: Severity;
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={clsx("inline-flex items-center gap-1.5 text-xs", className)}
    >
      <StatusDot severity={severity} />
      <span className="text-fg-muted">{label}</span>
    </span>
  );
}
