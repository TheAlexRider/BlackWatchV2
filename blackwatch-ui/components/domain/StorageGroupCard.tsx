import clsx from "clsx";
import Link from "next/link";
import type { StorageGroup, StorageGroupCounts } from "@/lib/types";

// One tile per storage domain (S3 / EBS / RDS / EFS / Backup / Secrets).
// Shows total activity in the window plus critical/high counters that go
// red when non-zero. Clickable — deep-links to a pre-filtered /events view
// so the user can drill in.
export function StorageGroupCard({
  group,
  label,
  counts,
  hours,
  href,
}: {
  group: StorageGroup;
  label: string;
  counts: StorageGroupCounts;
  hours: number;
  href?: string;
}) {
  const hasCritical = counts.critical > 0;
  const hasHigh = counts.high > 0;
  const Wrapper = href ? Link : ("div" as const);
  const wrapperProps = href ? { href } : {};
  return (
    <Wrapper
      {...(wrapperProps as { href: string })}
      className={clsx(
        "block border border-line-soft bg-surface-1 px-4 py-3 transition-colors",
        href && "hover:border-line hover:bg-surface-2",
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          {label}
        </span>
        <span className="font-mono text-[10px] uppercase text-fg-disabled">
          {group}
        </span>
      </div>
      <div className="mt-2 flex items-baseline gap-3">
        <span className="font-mono text-3xl tabular-nums text-fg">
          {counts.total}
        </span>
        <span className="text-[11px] text-fg-subtle">events / {hours}h</span>
      </div>
      <div className="mt-2 flex gap-3 text-[11px]">
        <span className={clsx(hasCritical ? "text-sev-critical" : "text-fg-subtle")}>
          critical {counts.critical}
        </span>
        <span className={clsx(hasHigh ? "text-sev-high" : "text-fg-subtle")}>
          high {counts.high}
        </span>
      </div>
    </Wrapper>
  );
}
