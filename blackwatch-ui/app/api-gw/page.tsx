import clsx from "clsx";

import {
  fetchApiGwSummary,
  fetchApiGwSources,
  fetchApiGwAlerts,
  fetchApiGwFailures,
} from "@/lib/api";
import type {
  ApiGwAlert,
  ApiGwSource,
  ApiGwFailure,
} from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { TimestampCell } from "@/components/domain/TimestampCell";

export default async function ApiGwPage() {
  const [summary, sources, alerts, failures] = await Promise.all([
    fetchApiGwSummary(),
    fetchApiGwSources(100),
    fetchApiGwAlerts(24),
    fetchApiGwFailures(24),
  ]);

  return (
    <>
      <AutoRefresh intervalMs={15_000} />
      <PageHeader
        title="API Gateway"
        subtitle={
          summary.sources === 0 ? (
            "No API Gateway traffic ingested yet — deploy the log forwarder to start."
          ) : (
            <>
              {summary.sources} unique source{summary.sources === 1 ? "" : "s"} ·{" "}
              {summary.requests.toLocaleString()} request
              {summary.requests === 1 ? "" : "s"} ·{" "}
              <span className={summary.err_4xx > 0 ? "text-sev-medium" : "text-fg-muted"}>
                {summary.err_4xx.toLocaleString()} 4xx
              </span>
              {" · "}
              <span className={summary.err_5xx > 0 ? "text-sev-critical" : "text-fg-muted"}>
                {summary.err_5xx.toLocaleString()} 5xx
              </span>
              {alerts.count > 0 && (
                <>
                  {" · "}
                  <span className="text-sev-high">
                    {alerts.count} alert{alerts.count === 1 ? "" : "s"}
                  </span>
                </>
              )}
            </>
          )
        }
      />

      {/* -------- Alerts (top) --------------------------------------------- */}
      <section className="space-y-2">
        <div className="flex items-baseline justify-between">
          <SectionLabel>alerts</SectionLabel>
          <span className="text-[11px] text-fg-subtle">
            new source · auth burst · scanner UA · 5xx burst · last {alerts.hours}h ·{" "}
            <span
              className={clsx(
                "font-mono",
                alerts.count > 0 ? "text-sev-high" : "text-fg-muted",
              )}
            >
              {alerts.count}
            </span>
          </span>
        </div>
        <DataPanel className="overflow-hidden">
          {alerts.alerts.length === 0 ? (
            <EmptyState>
              No credential-attack or new-source alerts. That&apos;s good — or
              the forwarder isn&apos;t running yet.
            </EmptyState>
          ) : (
            <AlertsTable alerts={alerts.alerts} />
          )}
        </DataPanel>
      </section>

      {/* -------- Source IPs ----------------------------------------------- */}
      <section className="mt-6 space-y-2">
        <div className="flex items-baseline justify-between">
          <SectionLabel>source IPs</SectionLabel>
          <span className="text-[11px] text-fg-subtle">
            real client IPs · sorted by last seen ·{" "}
            <span className="font-mono text-fg-muted">{sources.count}</span>
          </span>
        </div>
        <DataPanel className="overflow-hidden">
          {sources.sources.length === 0 ? (
            <EmptyState>
              No API activity yet. Source IPs will populate as the forwarder
              Lambda drains logs into BW.
            </EmptyState>
          ) : (
            <SourcesTable sources={sources.sources} />
          )}
        </DataPanel>
      </section>

      {/* -------- Recent failures ----------------------------------------- */}
      <section className="mt-6 space-y-2">
        <div className="flex items-baseline justify-between">
          <SectionLabel>failures (4xx auth + 5xx)</SectionLabel>
          <span className="text-[11px] text-fg-subtle">
            last {failures.hours}h ·{" "}
            <span
              className={clsx(
                "font-mono",
                failures.count > 0 ? "text-sev-medium" : "text-fg-muted",
              )}
            >
              {failures.count}
            </span>
          </span>
        </div>
        <DataPanel className="overflow-hidden">
          {failures.failures.length === 0 ? (
            <EmptyState>No failures. 🎉</EmptyState>
          ) : (
            <FailuresTable failures={failures.failures} />
          )}
        </DataPanel>
      </section>
    </>
  );
}

// =========================================================================
// Alerts
// =========================================================================

function AlertsTable({ alerts }: { alerts: ApiGwAlert[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-40 px-4 py-2 text-left font-normal">When</th>
          <th className="w-40 px-4 py-2 text-left font-normal">Signal</th>
          <th className="w-44 px-4 py-2 text-left font-normal">Source IP</th>
          <th className="px-4 py-2 text-left font-normal">Detail</th>
        </tr>
      </thead>
      <tbody>
        {alerts.map((a) => (
          <tr
            key={a.event_id ?? `${a.event_time}-${a.action}-${a.source_ip}`}
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
              <AlertPill action={a.action} />
            </td>
            <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
              {a.source_ip || <span className="text-fg-disabled">—</span>}
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

function AlertPill({ action }: { action: ApiGwAlert["action"] }) {
  const map: Record<ApiGwAlert["action"], { label: string; color: string }> = {
    "api.source.new": { label: "new source", color: "bg-sev-high" },
    "api.auth.burst": { label: "auth burst", color: "bg-sev-critical" },
    "api.error.burst": { label: "5xx burst", color: "bg-sev-medium" },
    "api.scanner_ua": { label: "scanner UA", color: "bg-sev-high" },
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
// Sources
// =========================================================================

function SourcesTable({ sources }: { sources: ApiGwSource[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-48 px-4 py-2 text-left font-normal">Source IP</th>
          <th className="w-44 px-4 py-2 text-left font-normal">API</th>
          <th className="w-28 px-4 py-2 text-right font-normal">Requests</th>
          <th className="w-24 px-4 py-2 text-right font-normal">4xx</th>
          <th className="w-24 px-4 py-2 text-right font-normal">5xx</th>
          <th className="w-40 px-4 py-2 text-left font-normal">First seen</th>
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
              {s.source_ip}
            </td>
            <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
              {s.api_name}
            </td>
            <td className="px-4 py-2.5 text-right font-mono text-xs text-fg-muted">
              {s.request_count.toLocaleString()}
            </td>
            <td className="px-4 py-2.5 text-right font-mono text-xs">
              <span
                className={
                  s.error_4xx_count > 0 ? "text-sev-medium" : "text-fg-disabled"
                }
              >
                {s.error_4xx_count.toLocaleString()}
              </span>
            </td>
            <td className="px-4 py-2.5 text-right font-mono text-xs">
              <span
                className={
                  s.error_5xx_count > 0 ? "text-sev-critical" : "text-fg-disabled"
                }
              >
                {s.error_5xx_count.toLocaleString()}
              </span>
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
// Failures
// =========================================================================

function FailuresTable({ failures }: { failures: ApiGwFailure[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-40 px-4 py-2 text-left font-normal">When</th>
          <th className="w-32 px-4 py-2 text-left font-normal">Kind</th>
          <th className="w-16 px-4 py-2 text-left font-normal">Method</th>
          <th className="w-20 px-4 py-2 text-left font-normal">Status</th>
          <th className="w-44 px-4 py-2 text-left font-normal">Source IP</th>
          <th className="w-40 px-4 py-2 text-left font-normal">Reason</th>
          <th className="px-4 py-2 text-left font-normal">User Agent</th>
        </tr>
      </thead>
      <tbody>
        {failures.map((f) => (
          <tr
            key={f.event_id ?? `${f.event_time}-${f.action}-${f.source_ip}`}
            className="border-b border-line-soft last:border-0 hover:bg-surface-2"
          >
            <td className="px-4 py-2.5 font-mono text-xs">
              {f.event_time ? (
                <TimestampCell value={f.event_time} />
              ) : (
                <span className="text-fg-disabled">—</span>
              )}
            </td>
            <td className="px-4 py-2.5 text-xs text-fg-muted">
              {f.action === "api.auth.failure" ? "auth" : "5xx"}
            </td>
            <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">
              {f.method || "—"}
            </td>
            <td className="px-4 py-2.5 font-mono text-xs">
              <span
                className={clsx(
                  (f.status ?? 0) >= 500
                    ? "text-sev-critical"
                    : (f.status ?? 0) >= 400
                    ? "text-sev-medium"
                    : "text-fg-muted",
                )}
              >
                {f.status ?? "—"}
              </span>
            </td>
            <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
              {f.source_ip || "—"}
            </td>
            <td className="truncate px-4 py-2.5 text-xs text-fg-muted">
              {f.reason || <span className="text-fg-disabled">—</span>}
            </td>
            <td className="truncate px-4 py-2.5 font-mono text-[11px] text-fg-subtle">
              {f.user_agent || <span className="text-fg-disabled">—</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-6 py-10 text-center text-sm text-fg-muted">
      {children}
    </div>
  );
}
