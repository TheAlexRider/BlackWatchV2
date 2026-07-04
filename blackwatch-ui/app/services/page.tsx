import clsx from "clsx";

import { fetchServices } from "@/lib/api";
import type {
  ProbeAgent,
  ServiceCounts,
  ServiceTarget,
} from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { SeverityBadge } from "@/components/domain/SeverityBadge";
import { TimestampCell } from "@/components/domain/TimestampCell";

export default async function ServicesPage() {
  const { agents, grouped, counts, archived, archive_threshold_days } =
    await fetchServices();
  const vpcs = Object.keys(grouped).sort();
  const totalLive = vpcs.reduce((acc, vpc) => acc + grouped[vpc].length, 0);
  const totalDown = vpcs.reduce(
    (acc, vpc) => acc + (counts[vpc]?.down ?? 0) + (counts[vpc]?.degraded ?? 0),
    0,
  );

  return (
    <>
      <AutoRefresh intervalMs={15_000} />
      <PageHeader
        title="Services"
        subtitle={`${totalLive} live · ${totalDown} down · ${archived.length} archived · ${vpcs.length} VPC${vpcs.length === 1 ? "" : "s"}`}
      />

      <section className="space-y-2">
        <SectionLabel>per-VPC probe agents</SectionLabel>
        <DataPanel className="overflow-hidden">
          {agents.length === 0 ? (
            <EmptyState>
              No probe agents have reported yet. Either install one in a VPC,
              or add an <code className="text-fg">aws_ecs_health</code>{" "}
              connector for AWS-side reading.
            </EmptyState>
          ) : (
            <AgentsTable agents={agents} />
          )}
        </DataPanel>
      </section>

      {vpcs.length === 0 ? (
        <DataPanel className="mt-6 px-6 py-12 text-center">
          <p className="text-sm text-fg-muted">
            No probe targets configured yet. Add some via the FastAPI{" "}
            <code className="text-fg">/ui/services/targets</code> page (Next.js
            port pending).
          </p>
        </DataPanel>
      ) : (
        <div className="mt-6 space-y-6">
          {vpcs.map((vpc) => (
            <VpcPanel
              key={vpc}
              vpc={vpc}
              services={grouped[vpc]}
              counts={counts[vpc]}
            />
          ))}
        </div>
      )}

      {archived.length > 0 && (
        <ArchivePanel
          archived={archived}
          thresholdDays={archive_threshold_days}
        />
      )}
    </>
  );
}

// =========================================================================
// agents
// =========================================================================

function AgentsTable({ agents }: { agents: ProbeAgent[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-44 px-4 py-2 text-left font-normal">VPC</th>
          <th className="w-32 px-4 py-2 text-left font-normal">Agent</th>
          <th className="w-44 px-4 py-2 text-left font-normal">Last report</th>
          <th className="px-4 py-2 text-left font-normal">Version</th>
        </tr>
      </thead>
      <tbody>
        {agents.map((a) => (
          <tr key={a.vpc} className="border-b border-line-soft last:border-0">
            <td className="px-4 py-2.5 font-mono text-xs text-fg">{a.vpc}</td>
            <td className="px-4 py-2.5">
              <AgentPill active={a.active === true} />
            </td>
            <td className="px-4 py-2.5">
              {a.last_report ? (
                <TimestampCell value={a.last_report} />
              ) : (
                <span className="text-fg-disabled">—</span>
              )}
            </td>
            <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">
              {a.agent_version ?? "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function AgentPill({ active }: { active: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        aria-hidden
        className={clsx(
          "h-1.5 w-1.5 rounded-full",
          active ? "bg-sev-resolved" : "bg-sev-critical",
        )}
      />
      <span className="text-fg-muted">{active ? "reporting" : "stale / down"}</span>
    </span>
  );
}

// =========================================================================
// VPC panel (one per VPC, each contains a services table)
// =========================================================================

function VpcPanel({
  vpc,
  services,
  counts,
}: {
  vpc: string;
  services: ServiceTarget[];
  counts: ServiceCounts | undefined;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>{vpc}</SectionLabel>
        <CountsLine counts={counts} />
      </div>
      <DataPanel className="overflow-hidden">
        <Table>
          <thead>
            <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="w-56 px-4 py-2 text-left font-normal">Service</th>
              <th className="w-32 px-4 py-2 text-left font-normal">Tier</th>
              <th className="w-32 px-4 py-2 text-left font-normal">Status</th>
              <th className="w-24 px-4 py-2 text-right font-normal">Latency</th>
              <th className="w-20 px-4 py-2 text-right font-normal">Fails</th>
              <th className="w-32 px-4 py-2 text-left font-normal">Last check</th>
              <th className="w-28 px-4 py-2 text-left font-normal">Sev</th>
              <th className="px-4 py-2 text-left font-normal">Tags</th>
            </tr>
          </thead>
          <tbody>
            {services.map((s) => (
              <ServiceRow key={s.id} service={s} />
            ))}
          </tbody>
        </Table>
      </DataPanel>
    </section>
  );
}

function CountsLine({ counts }: { counts: ServiceCounts | undefined }) {
  if (!counts) {
    return <span className="text-[11px] text-fg-subtle">—</span>;
  }
  const bad = counts.down + counts.degraded;
  return (
    <span className="text-[11px] text-fg-subtle">
      <span className="font-mono text-fg-muted">{counts.total}</span> total
      {bad > 0 && (
        <>
          {" · "}
          <span className="font-mono text-sev-critical">{bad}</span> down
        </>
      )}
      {counts.up > 0 && (
        <>
          {" · "}
          <span className="font-mono text-sev-resolved">{counts.up}</span> up
        </>
      )}
      {counts.unknown > 0 && (
        <>
          {" · "}
          <span className="font-mono">{counts.unknown}</span> unknown
        </>
      )}
      {counts.disabled > 0 && (
        <>
          {" · "}
          <span className="font-mono text-fg-disabled">{counts.disabled}</span>{" "}
          disabled
        </>
      )}
    </span>
  );
}

function ServiceRow({ service }: { service: ServiceTarget }) {
  // `unknown` means BW can't see this service for some reason -- any latency /
  // fails / last_seen we may have stored is meaningless. Dash them out.
  const hideMetrics = service.status === "unknown";
  return (
    <tr className="border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="truncate px-4 py-2.5">
        <span className="text-fg">{service.name}</span>
      </td>
      <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
        {service.tier}
      </td>
      <td className="px-4 py-2.5">
        <ServiceStatusPill status={service.status} />
      </td>
      <td className="px-4 py-2.5 text-right font-mono text-xs text-fg-muted">
        {hideMetrics || service.latency_ms == null
          ? "—"
          : `${service.latency_ms}ms`}
      </td>
      <td
        className={clsx(
          "px-4 py-2.5 text-right font-mono text-xs",
          !hideMetrics && service.consecutive_fails > 0
            ? "text-sev-critical"
            : "text-fg-muted",
        )}
      >
        {hideMetrics ? "—" : service.consecutive_fails}
      </td>
      <td className="px-4 py-2.5 font-mono text-xs">
        {hideMetrics || service.age_seconds == null ? (
          <span className="text-fg-disabled">—</span>
        ) : (
          <>
            <span className="text-fg-muted">{service.age_seconds}s ago</span>
            {service.stale && (
              <span className="ml-1.5 text-[10px] uppercase tracking-wider text-sev-medium">
                stale
              </span>
            )}
          </>
        )}
      </td>
      <td className="px-4 py-2.5">
        <SeverityBadge severity={service.severity_when_down} />
      </td>
      <td className="truncate px-4 py-2.5 font-mono text-[11px] text-fg-muted">
        {service.tags && Object.keys(service.tags).length > 0 ? (
          <span className="flex flex-wrap gap-x-2 gap-y-0.5">
            {Object.entries(service.tags).map(([k, v]) => (
              <code key={k}>
                {k}={v}
              </code>
            ))}
          </span>
        ) : (
          "—"
        )}
      </td>
    </tr>
  );
}

function ServiceStatusPill({ status }: { status: string }) {
  const map: Record<string, { color: string; label: string }> = {
    up: { color: "bg-sev-resolved", label: "up" },
    down: { color: "bg-sev-critical", label: "DOWN" },
    degraded: { color: "bg-sev-medium", label: "degraded" },
    // unknown = unprobeable but AWS still wants it running. Yellow to
    // signal "we can't see, look at AWS state".
    unknown: { color: "bg-sev-medium", label: "unknown" },
    disabled: { color: "bg-fg-disabled", label: "disabled" },
  };
  const { color, label } = map[status] ?? map.unknown;
  const emphatic = status === "down";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span aria-hidden className={clsx("h-1.5 w-1.5 rounded-full", color)} />
      <span className={clsx(emphatic ? "text-fg" : "text-fg-muted")}>
        {label}
      </span>
    </span>
  );
}

// =========================================================================
// archive panel — one collapsible table for services down >= threshold,
// rendered below all VPC panels regardless of which VPC they belong to.
// =========================================================================

function ArchivePanel({
  archived,
  thresholdDays,
}: {
  archived: ServiceTarget[];
  thresholdDays: number;
}) {
  return (
    <section className="mt-6 space-y-2">
      <details className="group">
        <summary className="flex cursor-pointer list-none items-baseline justify-between rounded-md border border-line-soft bg-surface-1 px-4 py-2.5 hover:bg-surface-2">
          <span className="flex items-baseline gap-2">
            <span
              aria-hidden
              className="text-fg-subtle transition-transform group-open:rotate-90"
            >
              ▸
            </span>
            <span className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              archive
            </span>
            <span className="text-xs text-fg-muted">
              services down for ≥ {thresholdDays} day{thresholdDays === 1 ? "" : "s"}
            </span>
          </span>
          <span className="text-[11px] text-fg-subtle">
            <span className="font-mono text-fg-muted">{archived.length}</span>{" "}
            archived
          </span>
        </summary>
        <DataPanel className="mt-2 overflow-hidden">
          <Table>
            <thead>
              <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
                <th className="w-20 px-4 py-2 text-left font-normal">VPC</th>
                <th className="w-56 px-4 py-2 text-left font-normal">Service</th>
                <th className="w-32 px-4 py-2 text-left font-normal">Tier</th>
                <th className="w-32 px-4 py-2 text-left font-normal">Status</th>
                <th className="w-36 px-4 py-2 text-left font-normal">Down for</th>
                <th className="w-28 px-4 py-2 text-left font-normal">Sev</th>
                <th className="px-4 py-2 text-left font-normal">Tags</th>
              </tr>
            </thead>
            <tbody>
              {archived.map((s) => (
                <ArchiveRow key={s.id} service={s} />
              ))}
            </tbody>
          </Table>
        </DataPanel>
      </details>
    </section>
  );
}

function ArchiveRow({ service }: { service: ServiceTarget }) {
  return (
    <tr className="border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
        {service.vpc}
      </td>
      <td className="truncate px-4 py-2.5 text-fg-muted">{service.name}</td>
      <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
        {service.tier}
      </td>
      <td className="px-4 py-2.5">
        <ServiceStatusPill status={service.status} />
      </td>
      <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">
        {formatDownDuration(service.down_since)}
      </td>
      <td className="px-4 py-2.5">
        <SeverityBadge severity={service.severity_when_down} />
      </td>
      <td className="truncate px-4 py-2.5 font-mono text-[11px] text-fg-muted">
        {service.tags && Object.keys(service.tags).length > 0 ? (
          <span className="flex flex-wrap gap-x-2 gap-y-0.5">
            {Object.entries(service.tags).map(([k, v]) => (
              <code key={k}>
                {k}={v}
              </code>
            ))}
          </span>
        ) : (
          "—"
        )}
      </td>
    </tr>
  );
}

function formatDownDuration(downSince: string | null): string {
  if (!downSince) return "—";
  const since = new Date(downSince).getTime();
  if (Number.isNaN(since)) return "—";
  const secs = Math.max(0, Math.floor((Date.now() - since) / 1000));
  const days = Math.floor(secs / 86400);
  if (days >= 1) {
    const hours = Math.floor((secs % 86400) / 3600);
    return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
  }
  const hours = Math.floor(secs / 3600);
  if (hours >= 1) return `${hours}h`;
  return `${Math.floor(secs / 60)}m`;
}

// =========================================================================
// empty state
// =========================================================================

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-6 py-10 text-center text-sm text-fg-muted">
      {children}
    </div>
  );
}
