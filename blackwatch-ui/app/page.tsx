import Link from "next/link";
import clsx from "clsx";

import { fetchOverview } from "@/lib/api";
import type { EventEnvelope } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  SeverityBadge,
  severityBorderBg,
} from "@/components/domain/SeverityBadge";

export default async function Home() {
  const data = await fetchOverview();

  return (
    <>
      <AutoRefresh intervalMs={10_000} />
      <PageHeader
        title="Overview"
        subtitle="Live state across detection, posture, and host telemetry."
      />

      {/* Top-level KPI strip */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi
          label="Events · 24h"
          value={fmtCount(data.volume_24h)}
          accent={data.volume_24h > 0 ? "neutral" : "neutral"}
          href="/events"
        />
        <Kpi
          label="Posture findings"
          value={String(data.posture.total_open)}
          accent={
            data.posture.by_severity.critical > 0
              ? "critical"
              : data.posture.by_severity.high > 0
                ? "high"
                : data.posture.total_open > 0
                  ? "medium"
                  : "ok"
          }
          href="/aws-posture"
        />
        <Kpi
          label="Hosts reporting"
          value={`${data.hosts.reporting}/${data.hosts.total}`}
          accent={
            data.hosts.stale > 0 && data.hosts.total > 0
              ? "medium"
              : data.hosts.total > 0
                ? "ok"
                : "neutral"
          }
          href="/hosts"
        />
        <Kpi
          label="High / critical · last 200"
          value={String(data.notable.length)}
          accent={data.notable.length > 0 ? "high" : "ok"}
          href="/events?severity=high"
        />
      </div>

      {/* Posture severity breakdown */}
      <section className="mt-6 space-y-2">
        <div className="flex items-baseline justify-between">
          <SectionLabel>posture · open findings by severity</SectionLabel>
          <Link href="/aws-posture" className="text-[11px] text-fg-subtle hover:text-fg">
            see all →
          </Link>
        </div>
        <DataPanel className="grid gap-4 p-4 md:grid-cols-[minmax(170px,0.7fr)_minmax(0,2fr)] md:items-center">
          <div className="border-b border-line-soft pb-4 md:border-b-0 md:border-r md:pb-0 md:pr-5">
            <div className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              Total open findings
            </div>
            <div className="mt-1 font-mono text-4xl tabular-nums text-fg">
              {data.posture.total_open}
            </div>
            <p className="mt-1 text-xs text-fg-muted">
              Prioritized by severity for the next response step.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            <PostureCell label="Critical" count={data.posture.by_severity.critical} accent="critical" total={data.posture.total_open} />
            <PostureCell label="High" count={data.posture.by_severity.high} accent="high" total={data.posture.total_open} />
            <PostureCell label="Medium" count={data.posture.by_severity.medium} accent="medium" total={data.posture.total_open} />
            <PostureCell label="Low" count={data.posture.by_severity.low} accent="low" total={data.posture.total_open} />
            <PostureCell label="Info" count={data.posture.by_severity.informational} accent="low" total={data.posture.total_open} />
          </div>
        </DataPanel>
      </section>

      {/* Notable events */}
      <section className="mt-6 space-y-2">
        <div className="flex items-baseline justify-between">
          <SectionLabel>notable · high / critical</SectionLabel>
          <Link
            href="/events?severity=high"
            className="text-[11px] text-fg-subtle hover:text-fg"
          >
            see all →
          </Link>
        </div>
        <DataPanel className="overflow-hidden">
          {data.notable.length === 0 ? (
            <EmptyState>No high or critical events in the recent window. Quiet.</EmptyState>
          ) : (
            <CompactEventsTable events={data.notable} />
          )}
        </DataPanel>
      </section>

      {/* Recent events tail */}
      <section className="mt-6 space-y-2">
        <div className="flex items-baseline justify-between">
          <SectionLabel>recent · last 10</SectionLabel>
          <Link href="/events" className="text-[11px] text-fg-subtle hover:text-fg">
            see all →
          </Link>
        </div>
        <DataPanel className="overflow-hidden">
          {data.recent.length === 0 ? (
            <EmptyState>
              No events yet — has an agent or connector reported?
            </EmptyState>
          ) : (
            <CompactEventsTable events={data.recent} />
          )}
        </DataPanel>
      </section>
    </>
  );
}

// =========================================================================
// pieces
// =========================================================================

type KpiAccent = "ok" | "neutral" | "critical" | "high" | "medium";

function Kpi({
  label,
  value,
  accent,
  href,
}: {
  label: string;
  value: string;
  accent: KpiAccent;
  href: string;
}) {
  const dot =
    accent === "critical"
      ? "bg-sev-critical"
      : accent === "high"
        ? "bg-sev-high"
        : accent === "medium"
          ? "bg-sev-medium"
          : accent === "ok"
            ? "bg-sev-resolved"
            : "bg-fg-subtle";
  return (
    <Link
      href={href}
      className="group block border border-line-soft bg-surface-1 px-4 py-3 transition-colors hover:bg-surface-2"
    >
      <div className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
        {label}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span
          aria-hidden
          className={clsx("h-1.5 w-1.5 translate-y-[-3px] rounded-full", dot)}
        />
        <span className="font-mono text-3xl tabular-nums text-fg">{value}</span>
      </div>
    </Link>
  );
}

function PostureCell({
  label,
  count,
  accent,
  total,
}: {
  label: string;
  count: number;
  accent: "critical" | "high" | "medium" | "low";
  total: number;
}) {
  const empty = count === 0;
  const dot = empty
    ? "bg-sev-resolved"
    : accent === "critical"
      ? "bg-sev-critical"
      : accent === "high"
        ? "bg-sev-high"
        : accent === "medium"
          ? "bg-sev-medium"
          : "bg-sev-low";
  const percentage = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div className="border border-line-soft bg-canvas/30 px-3 py-2.5">
      <div className="flex items-center justify-between gap-2 text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
        {label}
        <span className="font-mono text-[10px] text-fg-disabled">{percentage}%</span>
      </div>
      <div className="mt-1.5 flex items-baseline gap-2">
        <span
          aria-hidden
          className={clsx("h-1.5 w-1.5 translate-y-[-3px] rounded-full", dot)}
        />
        <span
          className={clsx(
            "font-mono text-2xl tabular-nums",
            empty ? "text-fg-disabled" : "text-fg",
          )}
        >
          {count}
        </span>
      </div>
      <div className="mt-2 h-1 overflow-hidden bg-surface-2" aria-hidden="true">
        <div className={clsx("h-full", dot)} style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}

function CompactEventsTable({ events }: { events: EventEnvelope[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-36 px-4 py-2 text-left font-normal">Time</th>
          <th className="w-24 px-4 py-2 text-left font-normal">Severity</th>
          <th className="px-4 py-2 text-left font-normal">Action</th>
          <th className="w-48 px-4 py-2 text-left font-normal">Actor</th>
        </tr>
      </thead>
      <tbody>
        {events.map((ev) => (
          <tr
            key={ev.event_id}
            className="group relative border-b border-line-soft last:border-0 hover:bg-surface-2"
          >
            <td className="relative px-4 py-2">
              <span
                aria-hidden
                className={clsx(
                  "pointer-events-none absolute left-0 top-0 h-full w-0.5",
                  severityBorderBg(ev.severity as string | null | undefined),
                )}
              />
              <TimestampCell value={ev.event_time} />
            </td>
            <td className="px-4 py-2">
              <SeverityBadge severity={(ev.severity as string) ?? null} />
            </td>
            <td className="truncate px-4 py-2">
              <Link
                href={`/events/${ev.event_id}`}
                className="font-mono text-xs text-fg transition-colors hover:text-signal"
              >
                {ev.action}
              </Link>
            </td>
            <td className="truncate px-4 py-2 text-xs text-fg-muted">
              {ev.actor?.principal ?? "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function fmtCount(n: number): string {
  if (n < 1000) return String(n);
  if (n < 10_000) return `${(n / 1000).toFixed(1)}k`;
  if (n < 1_000_000) return `${Math.round(n / 1000)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}
