import Link from "next/link";
import clsx from "clsx";

import { fetchHosts } from "@/lib/api";
import type {
  EventEnvelope,
  HostSummary,
} from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { IpCell } from "@/components/domain/IpCell";
import {
  SeverityBadge,
  severityBorderBg,
} from "@/components/domain/SeverityBadge";

export default async function HostsPage() {
  const { count, servers, auth, changes } = await fetchHosts();

  return (
    <>
      <AutoRefresh intervalMs={15_000} />
      <PageHeader
        title="Hosts"
        subtitle={`${count} EC2 host${count === 1 ? "" : "s"} reporting`}
      />

      <section className="space-y-2">
        <SectionLabel>instances</SectionLabel>
        <DataPanel className="overflow-hidden">
          {servers.length === 0 ? (
            <EmptyState>
              No hosts reporting yet. Install the agent
              (<code className="text-fg">scripts/ec2_agent.py</code>) and add an SQS
              connector with target module <code className="text-fg">ec2.host</code>.
            </EmptyState>
          ) : (
            <InstancesTable servers={servers} />
          )}
        </DataPanel>
      </section>

      <section className="mt-6 space-y-2">
        <div className="flex items-baseline justify-between">
          <SectionLabel>recent state changes</SectionLabel>
          <span className="text-[11px] text-fg-subtle">
            ports · users · keys · sudoers · packages
          </span>
        </div>
        <DataPanel className="overflow-hidden">
          {changes.length === 0 ? (
            <EmptyState>No state changes recorded yet.</EmptyState>
          ) : (
            <ChangesTable changes={changes} />
          )}
        </DataPanel>
      </section>

      <section className="mt-6 space-y-2">
        <SectionLabel>recent access (SSH / sudo)</SectionLabel>
        <DataPanel className="overflow-hidden">
          {auth.length === 0 ? (
            <EmptyState>No SSH/sudo activity captured yet.</EmptyState>
          ) : (
            <AccessTable rows={auth} />
          )}
        </DataPanel>
      </section>
    </>
  );
}

// --- tables ----------------------------------------------------------------

function InstancesTable({ servers }: { servers: HostSummary[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-20 px-4 py-2 text-left font-normal">Env</th>
          <th className="w-32 px-4 py-2 text-left font-normal">Role</th>
          <th className="w-36 px-4 py-2 text-left font-normal">Name</th>
          <th className="w-36 px-4 py-2 text-left font-normal">Instance</th>
          <th className="w-32 px-4 py-2 text-left font-normal">Hostname</th>
          <th className="w-28 px-4 py-2 text-left font-normal">Agent</th>
          <th className="w-20 px-4 py-2 text-left font-normal">Region</th>
          <th className="w-14 px-4 py-2 text-right font-normal">Ports</th>
          <th className="w-14 px-4 py-2 text-right font-normal">Users</th>
          <th className="w-14 px-4 py-2 text-right font-normal">Keys</th>
          <th className="px-4 py-2 text-left font-normal">Last seen</th>
        </tr>
      </thead>
      <tbody>
        {servers.map((s) => (
          <tr
            key={s.instance_id}
            className="border-b border-line-soft last:border-0 hover:bg-surface-2"
          >
            <td className="truncate px-4 py-2.5 text-xs text-fg">
              {s.tags?.env ?? "—"}
            </td>
            <td className="truncate px-4 py-2.5 text-xs text-fg">
              {s.tags?.role ?? "—"}
            </td>
            <td className="truncate px-4 py-2.5">
              <Link
                href={`/hosts/${s.instance_id}`}
                className="text-xs text-fg transition-colors hover:text-signal"
                title="Set on the host detail page"
              >
                {s.display_name ?? (
                  <span className="text-fg-disabled">—</span>
                )}
              </Link>
            </td>
            <td className="truncate px-4 py-2.5">
              <Link
                href={`/hosts/${s.instance_id}`}
                className="font-mono text-xs text-fg-muted transition-colors hover:text-signal"
              >
                {s.instance_id}
              </Link>
            </td>
            <td className="truncate px-4 py-2.5 text-xs text-fg-muted">
              {s.hostname ?? "—"}
            </td>
            <td className="px-4 py-2.5">
              <AgentPill active={s.active} stale={s.stale} />
            </td>
            <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">
              {s.region ?? "—"}
            </td>
            <td className="px-4 py-2.5 text-right font-mono text-xs text-fg-muted">
              {s.port_count}
            </td>
            <td className="px-4 py-2.5 text-right font-mono text-xs text-fg-muted">
              {s.user_count}
            </td>
            <td className="px-4 py-2.5 text-right font-mono text-xs text-fg-muted">
              {s.key_count}
            </td>
            <td className="px-4 py-2.5">
              <LastSeenCell ageSeconds={s.age_seconds} stale={s.stale} />
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

// Prefer the role tag for an event's host display, fall back to hostname,
// then instance id. Keeps tables readable when "i-08ba075..." is meaningless.
function hostLabel(event: EventEnvelope): string {
  const extra = (event.extra as Record<string, unknown> | undefined) ?? {};
  const tags = extra.tags as Record<string, string> | undefined;
  return tags?.role ?? event.target?.name ?? event.target?.id ?? "—";
}

function ChangesTable({ changes }: { changes: EventEnvelope[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-40 px-4 py-2 text-left font-normal">Time</th>
          <th className="w-24 px-4 py-2 text-left font-normal">Severity</th>
          <th className="w-56 px-4 py-2 text-left font-normal">Action</th>
          <th className="w-40 px-4 py-2 text-left font-normal">Host</th>
          <th className="px-4 py-2 text-left font-normal">Detail</th>
        </tr>
      </thead>
      <tbody>
        {changes.map((c) => (
          <tr
            key={c.event_id}
            className="group relative border-b border-line-soft last:border-0 hover:bg-surface-2"
          >
            <td className="relative px-4 py-2.5">
              <span
                aria-hidden
                className={clsx(
                  "pointer-events-none absolute left-0 top-0 h-full w-0.5",
                  severityBorderBg(c.severity as string | null | undefined),
                )}
              />
              <TimestampCell value={c.event_time} />
            </td>
            <td className="px-4 py-2.5">
              <SeverityBadge severity={(c.severity as string) ?? null} />
            </td>
            <td className="truncate px-4 py-2.5">
              <Link
                href={`/events/${c.event_id}`}
                className="font-mono text-xs text-fg transition-colors hover:text-signal"
              >
                {c.action}
              </Link>
            </td>
            <td className="truncate px-4 py-2.5 text-xs text-fg-muted">
              {hostLabel(c)}
            </td>
            <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
              <ChangeDetail event={c} />
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function AccessTable({ rows }: { rows: EventEnvelope[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-40 px-4 py-2 text-left font-normal">Time</th>
          <th className="w-24 px-4 py-2 text-left font-normal">Result</th>
          <th className="w-48 px-4 py-2 text-left font-normal">Action</th>
          <th className="w-32 px-4 py-2 text-left font-normal">User</th>
          <th className="w-36 px-4 py-2 text-left font-normal">Source IP</th>
          <th className="px-4 py-2 text-left font-normal">Host</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((a) => (
          <tr
            key={a.event_id}
            className="border-b border-line-soft last:border-0 hover:bg-surface-2"
          >
            <td className="px-4 py-2.5">
              <TimestampCell value={a.event_time} />
            </td>
            <td className="px-4 py-2.5">
              <OutcomePill outcome={a.outcome} />
            </td>
            <td className="truncate px-4 py-2.5">
              <Link
                href={`/events/${a.event_id}`}
                className="font-mono text-xs text-fg transition-colors hover:text-signal"
              >
                {a.action}
              </Link>
            </td>
            <td className="truncate px-4 py-2.5 text-xs text-fg">
              {a.actor?.principal ?? "—"}
            </td>
            <td className="truncate px-4 py-2.5 text-xs">
              <IpCell
                value={(a.actor as { source_ip?: string } | undefined)?.source_ip}
                className="text-xs text-fg-muted"
              />
            </td>
            <td className="truncate px-4 py-2.5 text-xs text-fg-muted">
              {hostLabel(a)}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

// --- pills ----------------------------------------------------------------

function AgentPill({ active, stale }: { active: boolean; stale: boolean }) {
  const ok = active && !stale;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        className={clsx(
          "h-1.5 w-1.5 rounded-full",
          ok ? "bg-sev-resolved" : "bg-sev-critical",
        )}
        aria-hidden
      />
      <span className="text-fg-muted">{ok ? "reporting" : "stale / down"}</span>
    </span>
  );
}

function OutcomePill({ outcome }: { outcome: string | undefined }) {
  const ok = outcome === "success";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        className={clsx(
          "h-1.5 w-1.5 rounded-full",
          ok ? "bg-sev-resolved" : "bg-sev-critical",
        )}
        aria-hidden
      />
      <span className={clsx(ok ? "text-fg-muted" : "text-fg")}>
        {ok ? "success" : "FAILED"}
      </span>
    </span>
  );
}

function LastSeenCell({
  ageSeconds,
  stale,
}: {
  ageSeconds: number | null;
  stale: boolean;
}) {
  if (ageSeconds === null) {
    return <span className="font-mono text-xs text-fg-disabled">—</span>;
  }
  return (
    <span className="font-mono text-xs">
      <span className="text-fg-muted">{ageSeconds}s ago</span>
      {stale && (
        <span className="ml-1.5 text-[10px] uppercase tracking-wider text-sev-medium">
          stale
        </span>
      )}
    </span>
  );
}

// Best-effort renderer of the assorted ".extra" payloads the change events
// carry. Matches the rendering in /ui/hosts so the port is faithful.
function ChangeDetail({ event }: { event: EventEnvelope }) {
  const extra = (event.extra as Record<string, unknown> | undefined) ?? {};
  const parts: React.ReactNode[] = [];

  if (extra.port) {
    parts.push(
      <span key="port">
        port {String(extra.proto ?? "")}/{String(extra.port)} on{" "}
        {String(extra.address ?? "—")}
      </span>,
    );
  } else if (extra.fingerprint) {
    const fp = String(extra.fingerprint).slice(0, 12);
    parts.push(
      <span key="fp">
        {String(extra.user ?? "")} · fp <code>{fp}</code>
      </span>,
    );
  } else if (extra.user) {
    parts.push(<span key="user">user <b>{String(extra.user)}</b></span>);
  }
  if (extra.path) {
    parts.push(
      <span key="path">
        <code>{String(extra.path)}</code>
        {extra.change ? ` · ${String(extra.change)}` : ""}
      </span>,
    );
  }
  if (extra.unit) parts.push(<code key="unit">{String(extra.unit)}</code>);
  if (extra.added_count !== undefined) {
    parts.push(
      <span key="pkg">
        +{String(extra.added_count)} / −{String(extra.removed_count)} packages
      </span>,
    );
  }
  if (parts.length === 0) return <>—</>;
  return <>{parts.map((p, i) => (i === 0 ? p : <span key={i}> · {p}</span>))}</>;
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-6 py-12 text-center text-sm text-fg-muted">{children}</div>
  );
}
