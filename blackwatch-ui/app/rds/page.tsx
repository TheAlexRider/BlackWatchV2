import clsx from "clsx";

import {
  fetchRdsSummary,
  fetchRdsLive,
  fetchRdsSessions,
  fetchRdsAuthFailures,
} from "@/lib/api";
import type {
  RdsAuthFailure,
  RdsDbSummary,
  RdsSession,
} from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { TimestampCell } from "@/components/domain/TimestampCell";

export default async function RdsPage() {
  const [summary, live, history, auth] = await Promise.all([
    fetchRdsSummary(),
    fetchRdsLive(),
    fetchRdsSessions(24),
    fetchRdsAuthFailures(24),
  ]);

  const totalActive = summary.databases.reduce((n, d) => n + d.active, 0);

  return (
    <>
      <AutoRefresh intervalMs={15_000} />
      <PageHeader
        title="RDS"
        subtitle={
          summary.databases.length === 0
            ? "No RDS activity ingested yet — deploy the log forwarder to start."
            : `${totalActive} active session${totalActive === 1 ? "" : "s"} · ${summary.auth_failures_24h_total} auth failure${summary.auth_failures_24h_total === 1 ? "" : "s"} in the last 24h`
        }
      />

      <section className="space-y-2">
        <SectionLabel>databases</SectionLabel>
        <DataPanel className="overflow-hidden">
          {summary.databases.length === 0 ? (
            <EmptyState>
              Nothing here yet. Once the log-forwarder Lambda is subscribed
              to your RDS log groups and the BW connector is enabled,
              sessions + auth failures will flow into this page.
            </EmptyState>
          ) : (
            <DatabasesTable databases={summary.databases} />
          )}
        </DataPanel>
      </section>

      <section className="mt-6 space-y-2">
        <div className="flex items-baseline justify-between">
          <SectionLabel>currently connected</SectionLabel>
          <span className="text-[11px] text-fg-subtle">
            <span className="font-mono text-fg-muted">{live.count}</span>{" "}
            active
          </span>
        </div>
        <DataPanel className="overflow-hidden">
          {live.sessions.length === 0 ? (
            <EmptyState>No active sessions right now.</EmptyState>
          ) : (
            <SessionsTable sessions={live.sessions} live />
          )}
        </DataPanel>
      </section>

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
                session history
              </span>
              <span className="text-xs text-fg-muted">last 24h</span>
            </span>
            <span className="text-[11px] text-fg-subtle">
              <span className="font-mono text-fg-muted">{history.count}</span>{" "}
              sessions
            </span>
          </summary>
          <DataPanel className="mt-2 overflow-hidden">
            {history.sessions.length === 0 ? (
              <EmptyState>No session history in the last 24h.</EmptyState>
            ) : (
              <SessionsTable sessions={history.sessions} />
            )}
          </DataPanel>
        </details>
      </section>

      <section className="mt-6 space-y-2">
        <div className="flex items-baseline justify-between">
          <SectionLabel>auth failures</SectionLabel>
          <span className="text-[11px] text-fg-subtle">
            last {auth.hours}h ·{" "}
            <span
              className={clsx(
                "font-mono",
                auth.count > 0 ? "text-sev-critical" : "text-fg-muted",
              )}
            >
              {auth.count}
            </span>
          </span>
        </div>
        <DataPanel className="overflow-hidden">
          {auth.failures.length === 0 ? (
            <EmptyState>No auth failures. 🎉</EmptyState>
          ) : (
            <AuthFailuresTable failures={auth.failures} />
          )}
        </DataPanel>
      </section>
    </>
  );
}

// =========================================================================
// databases summary
// =========================================================================

function DatabasesTable({ databases }: { databases: RdsDbSummary[] }) {
  return (
    <table className="w-full table-fixed text-sm">
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-64 px-4 py-2 text-left font-normal">Database</th>
          <th className="w-32 px-4 py-2 text-left font-normal">Source</th>
          <th className="w-24 px-4 py-2 text-right font-normal">Active</th>
          <th className="w-32 px-4 py-2 text-right font-normal">Auth fails 24h</th>
          <th className="w-32 px-4 py-2 text-right font-normal">Total seen</th>
          <th className="px-4 py-2 text-left font-normal">Last activity</th>
        </tr>
      </thead>
      <tbody>
        {databases.map((d) => (
          <tr
            key={`${d.db_instance}:${d.source_type}`}
            className="border-b border-line-soft last:border-0 hover:bg-surface-2"
          >
            <td className="truncate px-4 py-2.5 font-mono text-xs text-fg">
              {d.db_instance}
            </td>
            <td className="px-4 py-2.5">
              <SourcePill type={d.source_type} />
            </td>
            <td className="px-4 py-2.5 text-right font-mono text-xs">
              <span
                className={
                  d.active > 0 ? "text-sev-resolved" : "text-fg-disabled"
                }
              >
                {d.active}
              </span>
            </td>
            <td className="px-4 py-2.5 text-right font-mono text-xs">
              <span
                className={clsx(
                  d.auth_failures_24h > 0
                    ? "text-sev-critical"
                    : "text-fg-muted",
                )}
              >
                {d.auth_failures_24h}
              </span>
            </td>
            <td className="px-4 py-2.5 text-right font-mono text-xs text-fg-muted">
              {d.total_seen}
            </td>
            <td className="px-4 py-2.5 font-mono text-xs">
              {d.last_activity ? (
                <TimestampCell value={d.last_activity} />
              ) : (
                <span className="text-fg-disabled">—</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// =========================================================================
// sessions (live + history)
// =========================================================================

function SessionsTable({
  sessions,
  live = false,
}: {
  sessions: RdsSession[];
  live?: boolean;
}) {
  return (
    <table className="w-full table-fixed text-sm">
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-56 px-4 py-2 text-left font-normal">Database</th>
          <th className="w-32 px-4 py-2 text-left font-normal">User</th>
          <th className="w-40 px-4 py-2 text-left font-normal">Source IP</th>
          <th className="w-32 px-4 py-2 text-left font-normal">Duration</th>
          <th className="w-40 px-4 py-2 text-left font-normal">
            {live ? "Connected since" : "Connected at"}
          </th>
          {!live && (
            <th className="px-4 py-2 text-left font-normal">Disconnected</th>
          )}
        </tr>
      </thead>
      <tbody>
        {sessions.map((s) => (
          <tr
            key={s.session_id}
            className="border-b border-line-soft last:border-0 hover:bg-surface-2"
          >
            <td className="truncate px-4 py-2.5 font-mono text-xs text-fg">
              {s.db_instance}
              {s.db_name && (
                <span className="ml-1 text-fg-muted">
                  ({s.db_name})
                </span>
              )}
            </td>
            <td className="truncate px-4 py-2.5 text-fg">
              {s.db_user || <span className="text-fg-disabled">—</span>}
            </td>
            <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
              {s.source_ip || "—"}
              {s.source_port ? `:${s.source_port}` : ""}
            </td>
            <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">
              {formatDuration(s.duration_seconds)}
            </td>
            <td className="px-4 py-2.5 font-mono text-xs">
              {s.connected_at ? (
                <TimestampCell value={s.connected_at} />
              ) : (
                <span className="text-fg-disabled">—</span>
              )}
            </td>
            {!live && (
              <td className="px-4 py-2.5 font-mono text-xs">
                {s.disconnected_at ? (
                  <TimestampCell value={s.disconnected_at} />
                ) : (
                  <span className="text-sev-resolved">still open</span>
                )}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// =========================================================================
// auth failures
// =========================================================================

function AuthFailuresTable({ failures }: { failures: RdsAuthFailure[] }) {
  return (
    <table className="w-full table-fixed text-sm">
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-40 px-4 py-2 text-left font-normal">When</th>
          <th className="w-56 px-4 py-2 text-left font-normal">Database</th>
          <th className="w-32 px-4 py-2 text-left font-normal">User</th>
          <th className="w-40 px-4 py-2 text-left font-normal">Source IP</th>
          <th className="w-28 px-4 py-2 text-left font-normal">Source</th>
          <th className="px-4 py-2 text-left font-normal">Reason</th>
        </tr>
      </thead>
      <tbody>
        {failures.map((f) => (
          <tr
            key={f.event_id ?? `${f.event_time}-${f.user}-${f.source_ip}`}
            className="border-b border-line-soft last:border-0 hover:bg-surface-2"
          >
            <td className="px-4 py-2.5 font-mono text-xs">
              {f.event_time ? (
                <TimestampCell value={f.event_time} />
              ) : (
                <span className="text-fg-disabled">—</span>
              )}
            </td>
            <td className="truncate px-4 py-2.5 font-mono text-xs text-fg">
              {f.db_instance || "—"}
            </td>
            <td className="truncate px-4 py-2.5 text-fg">
              {f.user || <span className="text-fg-disabled">—</span>}
            </td>
            <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
              {f.source_ip || "—"}
            </td>
            <td className="px-4 py-2.5">
              <SourcePill type={f.source_type || "unknown"} />
            </td>
            <td className="truncate px-4 py-2.5 text-xs text-fg-muted">
              {f.reason || f.message || "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SourcePill({ type }: { type: string }) {
  const map: Record<string, { label: string; color: string }> = {
    postgres: { label: "postgres", color: "bg-sev-resolved" },
    rds_proxy: { label: "proxy", color: "bg-sev-medium" },
    unknown: { label: "?", color: "bg-fg-subtle" },
  };
  const { label, color } = map[type] ?? map.unknown;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span aria-hidden className={clsx("h-1.5 w-1.5 rounded-full", color)} />
      <span className="text-fg-muted">{label}</span>
    </span>
  );
}

function formatDuration(secs: number): string {
  if (secs < 60) return `${secs}s`;
  const days = Math.floor(secs / 86400);
  if (days >= 1) {
    const hours = Math.floor((secs % 86400) / 3600);
    return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
  }
  const hours = Math.floor(secs / 3600);
  if (hours >= 1) {
    const mins = Math.floor((secs % 3600) / 60);
    return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
  }
  return `${Math.floor(secs / 60)}m`;
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-6 py-10 text-center text-sm text-fg-muted">
      {children}
    </div>
  );
}
