import clsx from "clsx";

import { fetchServices } from "@/lib/api";
import type { ProbeAgent, ServiceTarget } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { SeverityBadge } from "@/components/domain/SeverityBadge";
import { TimestampCell } from "@/components/domain/TimestampCell";

export default async function ServicesPage() {
  const { agents, grouped } = await fetchServices();
  const vpcs = Object.keys(grouped).sort();
  const totalServices = vpcs.reduce(
    (acc, vpc) => acc + grouped[vpc].length,
    0,
  );

  return (
    <>
      <AutoRefresh intervalMs={15_000} />
      <PageHeader
        title="Services"
        subtitle={`${totalServices} service${totalServices === 1 ? "" : "s"} across ${vpcs.length} VPC${vpcs.length === 1 ? "" : "s"}`}
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
            />
          ))}
        </div>
      )}
    </>
  );
}

// =========================================================================
// agents
// =========================================================================

function AgentsTable({ agents }: { agents: ProbeAgent[] }) {
  return (
    <table className="w-full table-fixed text-sm">
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
    </table>
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
}: {
  vpc: string;
  services: ServiceTarget[];
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>{vpc}</SectionLabel>
        <span className="text-[11px] text-fg-subtle">
          {services.length} service{services.length === 1 ? "" : "s"}
        </span>
      </div>
      <DataPanel className="overflow-hidden">
        <table className="w-full table-fixed text-sm">
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
        </table>
      </DataPanel>
    </section>
  );
}

function ServiceRow({ service }: { service: ServiceTarget }) {
  return (
    <tr className="border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="truncate px-4 py-2.5">
        <span className="text-fg">{service.name}</span>
        {!service.enabled && (
          <span className="ml-2 text-[10px] uppercase tracking-wider text-fg-subtle">
            disabled
          </span>
        )}
      </td>
      <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
        {service.tier}
      </td>
      <td className="px-4 py-2.5">
        <ServiceStatusPill status={service.status} />
      </td>
      <td className="px-4 py-2.5 text-right font-mono text-xs text-fg-muted">
        {service.latency_ms != null ? `${service.latency_ms}ms` : "—"}
      </td>
      <td
        className={clsx(
          "px-4 py-2.5 text-right font-mono text-xs",
          service.consecutive_fails > 0 ? "text-sev-critical" : "text-fg-muted",
        )}
      >
        {service.consecutive_fails}
      </td>
      <td className="px-4 py-2.5 font-mono text-xs">
        {service.age_seconds == null ? (
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
    unknown: { color: "bg-fg-subtle", label: "unknown" },
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
// empty state
// =========================================================================

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-6 py-10 text-center text-sm text-fg-muted">
      {children}
    </div>
  );
}
