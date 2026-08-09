import clsx from "clsx";

import {
  fetchRdsSummary,
  fetchRdsLive,
  fetchRdsSessions,
  fetchRdsAuthFailures,
  fetchRdsProxySources,
  fetchRdsShapeB,
  fetchRdsAllowlist,
} from "@/lib/api";
import type {
  RdsAuthFailure,
  RdsDbSummary,
  RdsSession,
  RdsProxySource,
  RdsShapeBAlert,
  RdsAllowlistEntry,
} from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { RefreshButton } from "@/components/layout/RefreshButton";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { IpCell } from "@/components/domain/IpCell";
import { FlashToast } from "@/components/ui/FlashToast";
import { PendingButton } from "@/components/ui/PendingButton";
import { ConfirmSubmitButton } from "@/components/ui/ConfirmSubmitButton";
import { NativeSelect } from "@/components/ui/NativeSelect";
import {
  addAllowlistUserAction,
  removeAllowlistUserAction,
} from "./allowlist-actions";

export default async function RdsPage({
  searchParams,
}: {
  searchParams: Promise<{ msg?: string }>;
}) {
  const params = await searchParams;
  const [summary, live, history, auth, sources, shapeB, allowlist] =
    await Promise.all([
      fetchRdsSummary(),
      fetchRdsLive(),
      fetchRdsSessions(24),
      fetchRdsAuthFailures(24),
      fetchRdsProxySources(50),
      fetchRdsShapeB(24),
      fetchRdsAllowlist(),
    ]);

  const totalActive = summary.databases.reduce((n, d) => n + d.active, 0);
  const humans = allowlist.users.filter((u) => u.kind === "human");
  const services = allowlist.users.filter((u) => u.kind === "service");

  return (
    <>
      <AutoRefresh intervalMs={15_000} />
      {params?.msg && <FlashToast message={params.msg} />}
      <PageHeader
        title="RDS"
        subtitle={
          summary.databases.length === 0
            ? "No RDS activity ingested yet — deploy the log forwarder to start."
            : (
              <>
                {totalActive} active session{totalActive === 1 ? "" : "s"} ·{" "}
                {summary.auth_failures_24h_total} auth failure
                {summary.auth_failures_24h_total === 1 ? "" : "s"} in the last
                24h
                {shapeB.count > 0 && (
                  <>
                    {" · "}
                    <span className="text-sev-high">
                      {shapeB.count} Shape-B alert{shapeB.count === 1 ? "" : "s"}
                    </span>
                  </>
                )}
              </>
            )
        }
        actions={<RefreshButton connectorTypes={["aws_rds_sqs"]} />}
      />

      {/* -------- Shape-B alerts (top, because they're the real signal) --- */}
      <section className="space-y-2">
        <div className="flex items-baseline justify-between">
          <SectionLabel>shape-B alerts</SectionLabel>
          <span className="text-[11px] text-fg-subtle">
            new source · new user+ip · unknown user · last {shapeB.hours}h ·{" "}
            <span
              className={clsx(
                "font-mono",
                shapeB.count > 0 ? "text-sev-high" : "text-fg-muted",
              )}
            >
              {shapeB.count}
            </span>
          </span>
        </div>
        <DataPanel className="overflow-hidden">
          {shapeB.alerts.length === 0 ? (
            <EmptyState>
              No stolen-credential or new-source alerts. That&apos;s good —
              or your allowlist is too permissive.
            </EmptyState>
          ) : (
            <ShapeBAlertsTable alerts={shapeB.alerts} />
          )}
        </DataPanel>
      </section>

      {/* -------- Proxy source IPs (real client IPs) ---------------------- */}
      <section className="mt-6 space-y-2">
        <div className="flex items-baseline justify-between">
          <SectionLabel>proxy source IPs</SectionLabel>
          <span className="text-[11px] text-fg-subtle">
            real client IPs seen at the RDS Proxy ·{" "}
            <span className="font-mono text-fg-muted">{sources.count}</span>
          </span>
        </div>
        <DataPanel className="overflow-hidden">
          {sources.sources.length === 0 ? (
            <EmptyState>
              No proxy connects observed yet. New IPs will appear here as
              they connect (and fire rds.proxy.source.new the first time).
            </EmptyState>
          ) : (
            <ProxySourcesTable sources={sources.sources} />
          )}
        </DataPanel>
      </section>

      {/* -------- Databases summary --------------------------------------- */}
      <section className="mt-6 space-y-2">
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

      {/* -------- Currently connected ------------------------------------- */}
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

      {/* -------- Session history (collapsed) ----------------------------- */}
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

      {/* -------- Auth failures ------------------------------------------- */}
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

      {/* -------- User allowlist (collapsed) ------------------------------ */}
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
                user allowlist
              </span>
              <span className="text-xs text-fg-muted">
                users NOT on this list fire rds.user.unknown
              </span>
            </span>
            <span className="text-[11px] text-fg-subtle">
              <span className="font-mono text-fg-muted">{humans.length}</span>{" "}
              humans ·{" "}
              <span className="font-mono text-fg-muted">
                {services.length}
              </span>{" "}
              services
            </span>
          </summary>
          <div className="mt-2 space-y-4">
            <AllowlistManager
              humans={humans}
              services={services}
            />
          </div>
        </details>
      </section>
    </>
  );
}

// =========================================================================
// Shape-B alerts feed
// =========================================================================

function ShapeBAlertsTable({ alerts }: { alerts: RdsShapeBAlert[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-40 px-4 py-2 text-left font-normal">When</th>
          <th className="w-48 px-4 py-2 text-left font-normal">Signal</th>
          <th className="w-40 px-4 py-2 text-left font-normal">User</th>
          <th className="w-40 px-4 py-2 text-left font-normal">Source IP</th>
          <th className="px-4 py-2 text-left font-normal">Detail</th>
        </tr>
      </thead>
      <tbody>
        {alerts.map((a) => (
          <tr
            key={a.event_id ?? `${a.event_time}-${a.action}-${a.user}-${a.source_ip}`}
            className="border-b border-line-soft last:border-0 hover:bg-surface-2"
          >
            <td className="px-4 py-2.5 font-mono text-xs">
              {a.event_time ? (
                <TimestampCell value={a.event_time} />
              ) : (
                <span className="text-fg-disabled">—</span>
              )}
            </td>
            <td className="px-4 py-2.5">
              <ShapeBPill action={a.action} />
            </td>
            <td className="truncate px-4 py-2.5 text-fg">
              {a.user || <span className="text-fg-disabled">—</span>}
            </td>
            <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
              <IpCell value={a.source_ip} />
            </td>
            <td className="px-4 py-2.5 text-xs text-fg-muted">
              {a.message || <span className="text-fg-disabled">—</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function ShapeBPill({
  action,
}: {
  action: RdsShapeBAlert["action"];
}) {
  const map: Record<
    RdsShapeBAlert["action"],
    { label: string; color: string }
  > = {
    "rds.proxy.source.new": {
      label: "new proxy source",
      color: "bg-sev-high",
    },
    "rds.session.new_source": {
      label: "user × new IP",
      color: "bg-sev-high",
    },
    "rds.user.unknown": {
      label: "unknown user",
      color: "bg-sev-critical",
    },
  };
  const { label, color } = map[action];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span aria-hidden className={clsx("h-1.5 w-1.5 rounded-full", color)} />
      <span className="text-fg-muted">{label}</span>
    </span>
  );
}

// =========================================================================
// Proxy source IPs
// =========================================================================

function ProxySourcesTable({ sources }: { sources: RdsProxySource[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-56 px-4 py-2 text-left font-normal">Source IP</th>
          <th className="w-32 px-4 py-2 text-right font-normal">Connects</th>
          <th className="w-48 px-4 py-2 text-left font-normal">First seen</th>
          <th className="px-4 py-2 text-left font-normal">Last seen</th>
        </tr>
      </thead>
      <tbody>
        {sources.map((s) => (
          <tr
            key={s.source_ip}
            className="border-b border-line-soft last:border-0 hover:bg-surface-2"
          >
            <td className="truncate px-4 py-2.5 font-mono text-xs text-fg">
              <IpCell value={s.source_ip} />
            </td>
            <td className="px-4 py-2.5 text-right font-mono text-xs text-fg-muted">
              {s.connect_count.toLocaleString()}
            </td>
            <td className="px-4 py-2.5 font-mono text-xs">
              <TimestampCell value={s.first_seen_at} />
            </td>
            <td className="px-4 py-2.5 font-mono text-xs">
              <TimestampCell value={s.last_seen_at} />
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

// =========================================================================
// Allowlist manager
// =========================================================================

function AllowlistManager({
  humans,
  services,
}: {
  humans: RdsAllowlistEntry[];
  services: RdsAllowlistEntry[];
}) {
  return (
    <div className="space-y-4">
      <DataPanel className="overflow-hidden">
        <form action={addAllowlistUserAction} className="border-b border-line-soft p-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <input
              name="username"
              placeholder="username (e.g. aravinda_jatavallabha)"
              aria-label="Allowlist username"
              className="min-w-0 flex-1 rounded border border-line-soft bg-surface-1 px-3 py-1.5 font-mono text-xs text-fg placeholder:text-fg-disabled focus-visible:border-signal focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal"
              required
            />
            <NativeSelect
              name="kind"
              defaultValue="human"
              aria-label="Allowlist entry type"
              className="h-8 rounded px-3 text-xs"
            >
              <option value="human">human</option>
              <option value="service">service</option>
            </NativeSelect>
            <input
              name="note"
              placeholder="note (optional)"
              aria-label="Allowlist note"
              className="min-w-0 flex-1 rounded border border-line-soft bg-surface-1 px-3 py-1.5 text-xs text-fg placeholder:text-fg-disabled focus-visible:border-signal focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal"
            />
            <PendingButton className="rounded border border-signal bg-signal/10 px-3 py-1.5 text-xs text-signal hover:bg-signal/20">
              Add
            </PendingButton>
          </div>
        </form>
        <AllowlistTable
          entries={humans}
          heading="Humans"
          empty="No humans on the allowlist. Add real people here so they don't trigger rds.user.unknown."
        />
      </DataPanel>
      <DataPanel className="overflow-hidden">
        <AllowlistTable
          entries={services}
          heading="Service accounts"
          empty="No service accounts allowlisted. Add app pool users (application_user, ai_gateway_user, etc.) so their traffic doesn't trigger alerts."
        />
      </DataPanel>
    </div>
  );
}

function AllowlistTable({
  entries,
  heading,
  empty,
}: {
  entries: RdsAllowlistEntry[];
  heading: string;
  empty: string;
}) {
  if (entries.length === 0) {
    return (
      <div className="px-4 py-6">
        <div className="mb-2 text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          {heading}
        </div>
        <div className="text-xs text-fg-muted">{empty}</div>
      </div>
    );
  }
  return (
    <div>
      <div className="px-4 pt-3 pb-1 text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
        {heading} · {entries.length}
      </div>
      <Table>
        <thead>
          <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            <th className="w-64 px-4 py-2 text-left font-normal">Username</th>
            <th className="w-24 px-4 py-2 text-left font-normal">Kind</th>
            <th className="px-4 py-2 text-left font-normal">Note</th>
            <th className="w-40 px-4 py-2 text-left font-normal">Added</th>
            <th className="w-24 px-4 py-2 text-right font-normal" />
          </tr>
        </thead>
        <tbody>
          {entries.map((u) => (
            <tr
              key={u.username}
              className="border-b border-line-soft last:border-0 hover:bg-surface-2"
            >
              <td className="truncate px-4 py-2.5 font-mono text-xs text-fg">
                {u.username}
              </td>
              <td className="px-4 py-2.5 text-xs">
                <span
                  className={clsx(
                    "inline-block rounded px-1.5 py-0.5 text-[10px]",
                    u.kind === "human"
                      ? "bg-signal/10 text-signal"
                      : "bg-fg-subtle/10 text-fg-muted",
                  )}
                >
                  {u.kind}
                </span>
              </td>
              <td className="px-4 py-2.5 text-xs text-fg-muted">
                {u.note || <span className="text-fg-disabled">—</span>}
              </td>
              <td className="px-4 py-2.5 font-mono text-xs">
                <TimestampCell value={u.added_at} />
              </td>
              <td className="px-4 py-2.5 text-right">
                <form action={removeAllowlistUserAction}>
                  <input type="hidden" name="username" value={u.username} />
                  <ConfirmSubmitButton
                    className="rounded border border-line-soft px-2 py-1 text-[11px] text-fg-muted hover:border-sev-critical hover:text-sev-critical"
                    confirmMessage={`Remove ${u.username} from the allowlist?`}
                    pendingLabel="Removing…"
                  >
                    Remove
                  </ConfirmSubmitButton>
                </form>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

// =========================================================================
// databases summary
// =========================================================================

function DatabasesTable({ databases }: { databases: RdsDbSummary[] }) {
  return (
    <Table>
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
    </Table>
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
    <Table>
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
              <IpCell value={s.source_ip} />
              {s.source_ip && s.source_port ? (
                <span className="text-fg-subtle">:{s.source_port}</span>
              ) : null}
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
    </Table>
  );
}

// =========================================================================
// auth failures
// =========================================================================

function AuthFailuresTable({ failures }: { failures: RdsAuthFailure[] }) {
  return (
    <Table>
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
              <IpCell value={f.source_ip} />
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
    </Table>
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
