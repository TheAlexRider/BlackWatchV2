import clsx from "clsx";
import { StatusDot } from "@/components/ui/StatusDot";

type Counts = {
  critical: number;
  high: number;
  medium: number;
  lowAndInfo: number;
};

export function SeverityCounterGrid({ counts }: { counts: Counts }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Cell label="Critical" count={counts.critical} severity="critical" />
      <Cell label="High" count={counts.high} severity="high" />
      <Cell label="Medium" count={counts.medium} severity="medium" />
      <Cell label="Low / Info" count={counts.lowAndInfo} severity="low" />
    </div>
  );
}

function Cell({
  label,
  count,
  severity,
}: {
  label: string;
  count: number;
  severity: "critical" | "high" | "medium" | "low";
}) {
  const empty = count === 0;
  return (
    <div className="border border-line-soft bg-surface-1 px-4 py-3">
      <div className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
        {label}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <StatusDot
          severity={empty ? "resolved" : severity}
          className={clsx("translate-y-[-3px]")}
        />
        <span
          className={clsx(
            "font-mono text-3xl tabular-nums",
            empty ? "text-fg-disabled" : "text-fg",
          )}
        >
          {count}
        </span>
      </div>
    </div>
  );
}
