import Link from "next/link";
import clsx from "clsx";
import { Plus, Pencil, X } from "lucide-react";

import {
  fetchNotificationChannels,
  fetchNotificationRoutes,
  fetchNotificationLog,
  fetchNotificationAcks,
  fetchPerfAlerts,
} from "@/lib/api";
import type {
  NotificationChannel,
  NotificationLogEntry,
  NotificationAck,
  PerfAlertRule,
  Route,
  RouteBucket,
  RoutesResponse,
} from "@/lib/types";

import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { Button } from "@/components/ui/Button";
import { PendingButton } from "@/components/ui/PendingButton";
import { FlashToast } from "@/components/ui/FlashToast";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { SeverityBadge } from "@/components/domain/SeverityBadge";

import {
  testChannelAction,
  toggleChannelAction,
  deleteChannelAction,
  clearAckAction,
} from "./actions";

import { RouteRow, AddRouteRow } from "./RouteRow";

type SearchParams = { msg?: string };

// /notifications — the ONE dashboard for signal routing.
//
// Vocabulary:
//   Channel      — a delivery destination (Slack, email, webhook, etc.)
//   Route        — a rule: "when a matching event fires, send it to a
//                  channel". Rules are stored in notification_rules.
//   Module       — a source of events (aws.rds, ec2.host, ...). Modules are
//                  a GROUPING over routes, not a data type.
//
// Layout: three tables — channels, alert routes (grouped by module),
// metric routes — plus the activity log. Same visual grammar across all
// four so the eye reads them as one instrument.

export default async function NotificationsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { msg } = await searchParams;
  const [channelsData, routesData, logData, acksData, perfData] = await Promise.all([
    fetchNotificationChannels(),
    fetchNotificationRoutes(),
    fetchNotificationLog({ limit: 200 }),
    fetchNotificationAcks(),
    fetchPerfAlerts(),
  ]);

  const channelsAvailable = channelsData.channels.length > 0;

  // Metrics: any perf-alert rule counts as a "metric route" in the new model.
  const metricRules = perfData.rules;

  // Compact top-line: coverage + last 24h + failed count.
  const sent24h = countSince(logData.entries, "sent", 24 * 3600 * 1000);
  const failed24h = countSince(logData.entries, "failed", 24 * 3600 * 1000);
  const coverage = routesData.coverage;

  return (
    <>
      <AutoRefresh intervalMs={30000} />
      <PageHeader
        title="Notifications"
        subtitle={
          <span className="font-mono text-xs text-fg-muted">
            {coverage.routed} of {coverage.total} modules covered ·{" "}
            <span className="text-fg">{sent24h}</span> sent (24h) ·{" "}
            <span className={failed24h > 0 ? "text-sev-critical" : "text-fg"}>
              {failed24h}
            </span>{" "}
            failed
          </span>
        }
      />

      {msg && <FlashToast message={msg} />}
      {acksData.acks.length > 0 && <AcksBanner acks={acksData.acks} />}
      {!channelsAvailable && <ChannelsFirstHint />}

      {/* CHANNELS */}
      <SectionHeader
        label="channels"
        action={{ href: "/notifications/channels/new", label: "add channel" }}
      />
      <ChannelsTable channels={channelsData.channels} />

      {/* ALERT ROUTES — grouped by module */}
      <SectionHeader label="alert routes" />
      <RoutesTable
        buckets={routesData.buckets}
        channels={routesData.channels}
        channelsAvailable={channelsAvailable}
      />

      {/* METRIC ROUTES */}
      <SectionHeader
        label="metric routes"
        action={{ href: "/notifications/perf-alerts/new", label: "add metric" }}
      />
      <MetricRoutesTable rules={metricRules} />

      {/* ACTIVITY */}
      <div className="mt-8 mb-2 flex items-baseline justify-between">
        <SectionHeaderLabel>activity · last 50</SectionHeaderLabel>
        <Link
          href="/notifications/log"
          className="text-[11px] text-fg-subtle hover:text-fg"
        >
          full log →
        </Link>
      </div>
      <ActivityTable entries={logData.entries.slice(0, 50)} />
    </>
  );
}

// =========================================================================
// SECTION HEADER — shared visual chrome for every table on the page
// =========================================================================

function SectionHeader({
  label,
  action,
}: {
  label: string;
  action?: { href: string; label: string };
}) {
  return (
    <div className="mt-8 mb-2 flex items-baseline justify-between">
      <SectionHeaderLabel>{label}</SectionHeaderLabel>
      {action && (
        <Button asChild variant="ghost" size="sm">
          <Link href={action.href}>
            <Plus size={12} /> {action.label}
          </Link>
        </Button>
      )}
    </div>
  );
}

function SectionHeaderLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
      {children}
    </span>
  );
}

// =========================================================================
// CHANNELS
// =========================================================================

function ChannelsTable({ channels }: { channels: NotificationChannel[] }) {
  return (
    <DataPanel className="overflow-hidden">
      {channels.length === 0 ? (
        <div className="px-4 py-6 text-center text-xs text-fg-muted">
          No channels yet.{" "}
          <Link
            href="/notifications/channels/new"
            className="text-signal hover:underline"
          >
            Add one →
          </Link>
        </div>
      ) : (
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="w-[240px] px-4 py-2 text-left font-normal">Name</th>
              <th className="w-[120px] px-4 py-2 text-left font-normal">Type</th>
              <th className="w-[120px] px-4 py-2 text-left font-normal">State</th>
              <th className="w-[140px] px-4 py-2 text-left font-normal">Last status</th>
              <th className="w-[180px] px-4 py-2 text-left font-normal">Last sent</th>
              <th className="px-4 py-2 text-right font-normal" />
            </tr>
          </thead>
          <tbody>
            {channels.map((c) => (
              <ChannelRow key={c.id} channel={c} />
            ))}
          </tbody>
        </table>
      )}
    </DataPanel>
  );
}

function ChannelRow({ channel: c }: { channel: NotificationChannel }) {
  return (
    <tr className="border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="truncate px-4 py-2 align-middle">
        <Link
          href={`/notifications/channels/${c.id}`}
          className="text-sm text-fg transition-colors hover:text-signal"
        >
          {c.name}
        </Link>
      </td>
      <td className="px-4 py-2 align-middle font-mono text-xs text-fg-muted">
        {c.type}
      </td>
      <td className="px-4 py-2 align-middle">
        <EnabledPill enabled={c.enabled} />
      </td>
      <td className="px-4 py-2 align-middle">
        <ChannelStatusPill status={c.last_status} error={c.last_error} />
      </td>
      <td className="px-4 py-2 align-middle">
        {c.last_sent_at ? (
          <TimestampCell value={c.last_sent_at} />
        ) : (
          <span className="font-mono text-xs text-fg-disabled">—</span>
        )}
      </td>
      <td className="whitespace-nowrap px-4 py-2 align-middle text-right">
        <div className="inline-flex items-center gap-1.5">
          <form action={testChannelAction} className="inline">
            <input type="hidden" name="id" value={c.id} />
            <PendingButton size="sm" variant="secondary" pendingLabel="Sending…">
              Test
            </PendingButton>
          </form>
          <form action={toggleChannelAction} className="inline">
            <input type="hidden" name="id" value={c.id} />
            <input type="hidden" name="enabled" value={c.enabled ? "off" : "on"} />
            <PendingButton size="sm" variant="secondary" pendingLabel="…">
              {c.enabled ? "Disable" : "Enable"}
            </PendingButton>
          </form>
          <Button asChild size="sm" variant="ghost">
            <Link href={`/notifications/channels/${c.id}`}>
              <Pencil size={12} />
            </Link>
          </Button>
          <form action={deleteChannelAction} className="inline">
            <input type="hidden" name="id" value={c.id} />
            <Button type="submit" size="sm" variant="danger">
              Delete
            </Button>
          </form>
        </div>
      </td>
    </tr>
  );
}

// =========================================================================
// ALERT ROUTES — grouped by module
// =========================================================================

function RoutesTable({
  buckets,
  channels,
  channelsAvailable,
}: {
  buckets: RouteBucket[];
  channels: RoutesResponse["channels"];
  channelsAvailable: boolean;
}) {
  return (
    <DataPanel className="overflow-hidden">
      <table className="w-full table-fixed text-sm">
        <thead>
          <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            <th className="w-[240px] px-4 py-2 text-left font-normal">
              Trigger (severities)
            </th>
            <th className="w-[220px] px-4 py-2 text-left font-normal">Channel</th>
            <th className="w-[100px] px-4 py-2 text-left font-normal">State</th>
            <th className="px-4 py-2 text-right font-normal" />
          </tr>
        </thead>
        <tbody>
          {!channelsAvailable && (
            <tr>
              <td
                colSpan={4}
                className="px-4 py-6 text-center text-xs text-fg-muted"
              >
                Add a channel first before creating routes.
              </td>
            </tr>
          )}
          {channelsAvailable &&
            buckets.map((bucket) => (
              <BucketGroup
                key={bucket.module}
                bucket={bucket}
                channels={channels}
              />
            ))}
        </tbody>
      </table>
    </DataPanel>
  );
}

function BucketGroup({
  bucket,
  channels,
}: {
  bucket: RouteBucket;
  channels: RoutesResponse["channels"];
}) {
  const isCustom = bucket.module === "__custom__";
  return (
    <>
      <tr className="bg-surface-1">
        <td colSpan={4} className="px-4 py-2">
          <div className="flex items-baseline gap-3">
            <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              {bucket.label}
            </span>
            {bucket.blurb && !isCustom && (
              <span className="truncate text-[11px] text-fg-subtle">
                {bucket.blurb}
              </span>
            )}
            {bucket.routes.length === 0 && !isCustom && (
              <span className="ml-auto text-[11px] text-fg-subtle">
                coverage gap
              </span>
            )}
          </div>
        </td>
      </tr>
      {bucket.routes.map((route: Route) => (
        <RouteRow
          key={route.id}
          route={route}
          module={bucket.module}
          channels={channels}
          isCustom={isCustom}
        />
      ))}
      {!isCustom && (
        <AddRouteRow
          module={bucket.module}
          channels={channels}
          moduleLabel={bucket.label}
        />
      )}
    </>
  );
}

// =========================================================================
// METRIC ROUTES — perf-alert rules table
// =========================================================================

const METRIC_LABEL: Record<string, string> = {
  memory_pct: "Memory %",
  cpu_load_norm: "CPU load (norm)",
  disk_pct_max: "Disk %",
};

function MetricRoutesTable({ rules }: { rules: PerfAlertRule[] }) {
  return (
    <DataPanel className="overflow-hidden">
      {rules.length === 0 ? (
        <div className="px-4 py-6 text-center text-xs text-fg-muted">
          No metric routes yet.{" "}
          <Link
            href="/notifications/perf-alerts/new"
            className="text-signal hover:underline"
          >
            Add one →
          </Link>{" "}
          — Memory, CPU or Disk on hosts with a threshold + channel.
        </div>
      ) : (
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="w-[180px] px-4 py-2 text-left font-normal">Metric</th>
              <th className="w-[240px] px-4 py-2 text-left font-normal">Trigger</th>
              <th className="w-[200px] px-4 py-2 text-left font-normal">Channel</th>
              <th className="w-[100px] px-4 py-2 text-left font-normal">State</th>
              <th className="px-4 py-2 text-right font-normal" />
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <MetricRow key={r.id} rule={r} />
            ))}
          </tbody>
        </table>
      )}
    </DataPanel>
  );
}

function MetricRow({ rule: r }: { rule: PerfAlertRule }) {
  const minutes = Math.max(1, Math.round(r.window_seconds / 60));
  const scope = r.instance_id
    ? r.instance_id
    : r.tag_key
    ? `tag ${r.tag_key}=${r.tag_value}`
    : "all hosts";
  return (
    <tr className="border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="truncate px-4 py-2 align-middle text-sm text-fg">
        {METRIC_LABEL[r.metric] ?? r.metric}
      </td>
      <td className="truncate px-4 py-2 align-middle font-mono text-xs text-fg-muted">
        ≥ {r.threshold}% / {minutes}m · {scope}
      </td>
      <td className="truncate px-4 py-2 align-middle font-mono text-xs text-fg-muted">
        {(r.channels || []).join(", ") || "—"}
      </td>
      <td className="px-4 py-2 align-middle">
        <span
          className={clsx("text-xs", r.enabled ? "text-signal" : "text-fg-subtle")}
        >
          {r.enabled ? "on" : "off"}
        </span>
      </td>
      <td className="whitespace-nowrap px-4 py-2 align-middle text-right">
        <Button asChild size="sm" variant="ghost">
          <Link href={`/notifications/perf-alerts/${encodeURIComponent(r.id)}/edit`}>
            <Pencil size={12} />
          </Link>
        </Button>
      </td>
    </tr>
  );
}

// =========================================================================
// ACTIVITY
// =========================================================================

function ActivityTable({ entries }: { entries: NotificationLogEntry[] }) {
  return (
    <DataPanel className="overflow-hidden">
      {entries.length === 0 ? (
        <div className="px-4 py-6 text-center text-xs text-fg-muted">
          Nothing has fired yet.
        </div>
      ) : (
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="w-[160px] px-4 py-2 text-left font-normal">Time</th>
              <th className="w-[120px] px-4 py-2 text-left font-normal">Status</th>
              <th className="w-[180px] px-4 py-2 text-left font-normal">Channel</th>
              <th className="w-[220px] px-4 py-2 text-left font-normal">Rule</th>
              <th className="px-4 py-2 text-left font-normal">Event</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <ActivityRow key={String(e.id)} entry={e} />
            ))}
          </tbody>
        </table>
      )}
    </DataPanel>
  );
}

function ActivityRow({ entry: e }: { entry: NotificationLogEntry }) {
  return (
    <tr className="border-b border-line-soft last:border-0">
      <td className="px-4 py-2 align-middle">
        <TimestampCell value={e.ts} />
      </td>
      <td className="px-4 py-2 align-middle">
        <ActivityStatusPill status={e.status} />
      </td>
      <td className="truncate px-4 py-2 align-middle text-xs text-fg-muted">
        {e.channel_name ?? "—"}
      </td>
      <td className="truncate px-4 py-2 align-middle text-xs text-fg-muted">
        {e.rule_name ?? "—"}
      </td>
      <td className="truncate px-4 py-2 align-middle">
        <div className="flex items-center gap-2">
          {e.event_id ? (
            <Link
              href={`/events/${e.event_id}`}
              className="font-mono text-xs text-fg transition-colors hover:text-signal"
            >
              {e.event_action ?? "—"}
            </Link>
          ) : (
            <code className="font-mono text-xs text-fg-muted">
              {e.event_action ?? "—"}
            </code>
          )}
          {e.event_severity && <SeverityBadge severity={e.event_severity} />}
        </div>
      </td>
    </tr>
  );
}

function ActivityStatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    sent: "bg-sev-resolved",
    failed: "bg-sev-critical",
    rate_limited: "bg-sev-medium",
    throttled: "bg-sev-medium",
    digested: "bg-sev-low",
    acked: "bg-fg-subtle",
  };
  const color = map[status] ?? "bg-fg-subtle";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span aria-hidden className={clsx("h-1.5 w-1.5 rounded-full", color)} />
      <span className="text-fg-muted">{status}</span>
    </span>
  );
}

// =========================================================================
// ACKS BANNER
// =========================================================================

function AcksBanner({ acks }: { acks: NotificationAck[] }) {
  return (
    <section className="mb-6 mt-3 border border-line-soft bg-surface-1">
      <div className="flex items-baseline justify-between border-b border-line-soft px-4 py-2">
        <span className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          {acks.length} active ack{acks.length === 1 ? "" : "s"} · paused
          notifications
        </span>
      </div>
      <div className="divide-y divide-line-soft">
        {acks.map((a) => (
          <div
            key={a.fingerprint}
            className="grid grid-cols-[1fr_220px_80px] items-center gap-4 px-4 py-2 text-xs"
          >
            <div className="truncate">
              <code className="font-mono text-fg">
                {a.fingerprint.slice(0, 24)}…
              </code>
              {a.reason && <span className="ml-2 text-fg-muted">· {a.reason}</span>}
            </div>
            <div className="text-fg-subtle">
              until <TimestampCell value={a.ack_until} />
            </div>
            <div className="text-right">
              <form action={clearAckAction} className="inline">
                <input type="hidden" name="fingerprint" value={a.fingerprint} />
                <Button type="submit" size="sm" variant="ghost">
                  <X size={12} /> clear
                </Button>
              </form>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// =========================================================================
// SMALL BITS
// =========================================================================

function EnabledPill({ enabled }: { enabled: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        aria-hidden
        className={clsx(
          "h-1.5 w-1.5 rounded-full",
          enabled ? "bg-sev-resolved" : "bg-fg-subtle",
        )}
      />
      <span className="text-fg-muted">{enabled ? "enabled" : "disabled"}</span>
    </span>
  );
}

function ChannelStatusPill({
  status,
  error,
}: {
  status: string | null;
  error: string | null;
}) {
  if (status === "ok") {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span className="h-1.5 w-1.5 rounded-full bg-sev-resolved" aria-hidden />
        <span className="text-fg-muted">ok</span>
      </span>
    );
  }
  if (status && status !== "ok") {
    return (
      <span title={error ?? ""} className="inline-flex items-center gap-1.5 text-xs">
        <span className="h-1.5 w-1.5 rounded-full bg-sev-critical" aria-hidden />
        <span className="text-fg-muted">{status}</span>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className="h-1.5 w-1.5 rounded-full bg-fg-subtle" aria-hidden />
      <span className="text-fg-subtle">never</span>
    </span>
  );
}

function ChannelsFirstHint() {
  return (
    <div className="mt-3 border border-sev-medium/30 bg-sev-medium/5 px-4 py-3 text-sm text-fg-muted">
      <span className="text-sev-medium">▸</span> Start by adding a channel —
      Slack, email, webhook, PagerDuty, etc.{" "}
      <Link href="/notifications/channels/new" className="text-signal hover:underline">
        Add one →
      </Link>{" "}
      then route modules to it below.
    </div>
  );
}

// ---- helper -----------------------------------------------------------

function countSince(
  entries: NotificationLogEntry[],
  status: string,
  windowMs: number,
): number {
  const cutoff = Date.now() - windowMs;
  return entries.filter(
    (e) => e.status === status && new Date(e.ts).getTime() >= cutoff,
  ).length;
}
