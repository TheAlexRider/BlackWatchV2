import Link from "next/link";
import clsx from "clsx";
import { Plus, Pencil, Trash2, X } from "lucide-react";

import {
  fetchNotificationChannels,
  fetchNotificationRoutes,
  fetchNotificationLog,
  fetchNotificationAcks,
  fetchPerfAlerts,
  hostLabel,
} from "@/lib/api";
import type {
  NotificationChannel,
  NotificationLogEntry,
  NotificationAck,
  PerfAlertInstance,
  PerfAlertRule,
  Route,
  SeverityKey,
} from "@/lib/types";

import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { Button } from "@/components/ui/Button";
import { PendingButton } from "@/components/ui/PendingButton";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { FlashToast } from "@/components/ui/FlashToast";
import { Table } from "@/components/ui/Table";
import { SeverityChip } from "@/components/ui/SeverityChip";
import { StatusDot, type Severity } from "@/components/ui/StatusDot";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { SeverityBadge } from "@/components/domain/SeverityBadge";

import {
  testChannelAction,
  toggleChannelAction,
  deleteChannelAction,
  clearAckAction,
} from "./actions";
import {
  toggleRouteAction,
  silenceRouteAction,
  deleteRouteAction,
  testRouteAction,
} from "./route-actions";
import {
  togglePerfAlertAction,
  deletePerfAlertAction,
} from "./perf-alerts/actions";

type SearchParams = { msg?: string };

// /notifications — one dashboard.
//
// Three tables (channels, alert routes, metric routes) + activity log.
// Only CONFIGURED routes are shown; empty modules are discovered via the
// [+ Create alert] wizard, not surfaced as coverage-gap rows.
//
// One primary teal CTA on the page: the Create button. Everything else is
// muted so the eye lands on the action that unblocks first-run users.
export default async function NotificationsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { msg } = await searchParams;
  const [channelsData, routesData, logData, acksData, perfData] =
    await Promise.all([
      fetchNotificationChannels(),
      fetchNotificationRoutes(),
      fetchNotificationLog({ limit: 200 }),
      fetchNotificationAcks(),
      fetchPerfAlerts(),
    ]);
  const channelsAvailable = channelsData.channels.length > 0;
  const sent24h = countSince(logData.entries, "sent", 24 * 3600 * 1000);
  const failed24h = countSince(logData.entries, "failed", 24 * 3600 * 1000);

  return (
    <>
      <AutoRefresh intervalMs={30000} />
      <PageHeader
        title="Notifications"
        subtitle={`${routesData.routes.length} route${
          routesData.routes.length === 1 ? "" : "s"
        } · ${sent24h} sent (24h) · ${failed24h} failed`}
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

      {/* ALERT ROUTES */}
      <div className="mt-8 mb-2 flex items-baseline justify-between">
        <SectionHeaderLabel>alert routes</SectionHeaderLabel>
        <Button asChild variant="primary" size="sm">
          <Link href="/notifications/create">
            <Plus size={12} /> Create alert
          </Link>
        </Button>
      </div>
      <RoutesTable routes={routesData.routes} channelsAvailable={channelsAvailable} />

      {/* METRIC ROUTES */}
      <SectionHeader
        label="metric routes"
        action={{ href: "/notifications/perf-alerts/new", label: "add metric" }}
      />
      <MetricRoutesTable rules={perfData.rules} instances={perfData.instances} />

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
// SECTION HEADERS
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
        <Table tableId="notifications-channels" ariaLabel="Channels">
          <thead>
            <tr>
              <th style={{ width: 240 }}>Name</th>
              <th style={{ width: 120 }}>Type</th>
              <th style={{ width: 120 }}>State</th>
              <th style={{ width: 140 }}>Last status</th>
              <th style={{ width: 180 }}>Last sent</th>
              <th data-actions style={{ width: 320 }} />
            </tr>
          </thead>
          <tbody>
            {channels.map((c) => (
              <ChannelRow key={c.id} channel={c} />
            ))}
          </tbody>
        </Table>
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
      <td className="px-4 py-2 align-middle font-mono text-xs text-fg-muted">{c.type}</td>
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
// ALERT ROUTES — only configured, row-level quick actions
// =========================================================================

function RoutesTable({
  routes,
  channelsAvailable,
}: {
  routes: Route[];
  channelsAvailable: boolean;
}) {
  if (!channelsAvailable) {
    return (
      <DataPanel>
        <div className="px-4 py-6 text-center text-xs text-fg-muted">
          Add a channel first before creating routes.
        </div>
      </DataPanel>
    );
  }
  if (routes.length === 0) {
    return (
      <DataPanel>
        <div className="px-4 py-8 text-center">
          <p className="text-sm text-fg-muted">
            No alerts set up yet.
          </p>
          <p className="mt-1 text-xs text-fg-subtle">
            Create your first alert — pick a module, choose severity, wire it to a channel.
          </p>
          <div className="mt-4">
            <Button asChild size="sm" variant="primary">
              <Link href="/notifications/create">
                <Plus size={12} /> Create your first alert
              </Link>
            </Button>
          </div>
        </div>
      </DataPanel>
    );
  }
  return (
    <DataPanel className="overflow-hidden">
      <Table tableId="notifications-alert-routes" ariaLabel="Alert routes">
        <thead>
          <tr>
            <th style={{ width: 200 }}>Source</th>
            <th style={{ width: 220 }}>Trigger</th>
            <th style={{ width: 200 }}>Channel</th>
            <th style={{ width: 90 }}>State</th>
            <th data-actions style={{ width: 480 }} />
          </tr>
        </thead>
        <tbody>
          {routes.map((r) => (
            <RouteRow key={r.id} route={r} />
          ))}
        </tbody>
      </Table>
    </DataPanel>
  );
}


function RouteRow({ route: r }: { route: Route }) {
  const state = computeRouteState(r);
  return (
    <tr className="border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="truncate px-4 py-2 align-middle">
        <div className="text-sm text-fg">
          {r.kind === "custom" && r.name ? r.name : r.module_label}
        </div>
        {r.kind === "custom" && (
          <div className="font-mono text-[10px] text-fg-subtle">
            {r.module_label}
          </div>
        )}
      </td>
      <td className="px-4 py-2 align-middle">
        {r.severities.length === 0 ? (
          <span className="text-xs text-fg-muted">custom condition</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {r.severities.map((s) => (
              <SeverityChip key={s} severity={s} />
            ))}
          </div>
        )}
      </td>
      <td className="truncate px-4 py-2 align-middle font-mono text-xs text-fg-muted">
        {r.channels && r.channels.length > 0 ? (
          <>
            <span className="text-fg-subtle">→ </span>
            {r.channels.join(", ")}
          </>
        ) : r.channel ? (
          <>
            <span className="text-fg-subtle">→ </span>
            {r.channel}
          </>
        ) : (
          "—"
        )}
      </td>
      <td className="px-4 py-2 align-middle">
        <span className={clsx("text-xs", state.className)}>{state.label}</span>
      </td>
      <td className="whitespace-nowrap px-4 py-2 align-middle text-right">
        <div className="inline-flex items-center gap-1.5">
          <form action={testRouteAction} className="inline">
            <input type="hidden" name="channel" value={r.channel ?? ""} />
            <PendingButton
              size="sm"
              variant="secondary"
              disabled={!r.channel}
              pendingLabel="Sending…"
            >
              Test
            </PendingButton>
          </form>
          <form action={silenceRouteAction} className="inline-flex items-center gap-1">
            <input type="hidden" name="id" value={r.id} />
            <NativeSelect
              name="hours"
              defaultValue={r.silenced ? "0" : "1"}
              className="h-7 text-xs"
              aria-label="Silence duration"
            >
              <option value="1">1h</option>
              <option value="4">4h</option>
              <option value="24">24h</option>
              <option value="0">clear</option>
            </NativeSelect>
            <PendingButton size="sm" variant="secondary" pendingLabel="…">
              {r.silenced ? "Un-silence" : "Silence"}
            </PendingButton>
          </form>
          <form action={toggleRouteAction} className="inline">
            <input type="hidden" name="id" value={r.id} />
            <input type="hidden" name="target" value={r.enabled ? "off" : "on"} />
            <PendingButton size="sm" variant="secondary" pendingLabel="…">
              {r.enabled ? "Turn off" : "Turn on"}
            </PendingButton>
          </form>
          <Button asChild size="sm" variant="ghost" aria-label="Edit route">
            <Link href={`/notifications/rules/${encodeURIComponent(r.id)}/edit`}>
              <Pencil size={12} />
            </Link>
          </Button>
          <form action={deleteRouteAction} className="inline">
            <input type="hidden" name="id" value={r.id} />
            <PendingButton size="sm" variant="danger" pendingLabel="…">
              <Trash2 size={11} /> Delete
            </PendingButton>
          </form>
        </div>
      </td>
    </tr>
  );
}

function computeRouteState(r: Route): { label: string; className: string } {
  if (r.silenced) return { label: "silenced", className: "text-sev-medium" };
  if (!r.enabled) return { label: "off", className: "text-fg-subtle" };
  if (!r.channel) return { label: "no channel", className: "text-fg-subtle" };
  return { label: "on", className: "text-signal" };
}

// =========================================================================
// METRIC ROUTES
// =========================================================================

const METRIC_LABEL: Record<string, string> = {
  memory_pct: "Memory %",
  cpu_utilization_pct: "CPU utilization %",
  disk_pct_max: "Disk %",
};

function MetricRoutesTable({
  rules,
  instances,
}: {
  rules: PerfAlertRule[];
  instances: PerfAlertInstance[];
}) {
  // Build a lookup so each row can resolve display_name > hostname > id
  // without re-scanning the instance list per rule.
  const byId = new Map(instances.map((i) => [i.instance_id, i]));

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
          </Link>
        </div>
      ) : (
        <Table tableId="notifications-metric-routes" ariaLabel="Metric routes">
          <thead>
            <tr>
              <th style={{ width: 180 }}>Metric</th>
              <th style={{ width: 240 }}>Trigger</th>
              <th style={{ width: 200 }}>Channel</th>
              <th style={{ width: 90 }}>State</th>
              <th data-actions style={{ width: 320 }} />
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <MetricRow key={r.id} rule={r} instancesById={byId} />
            ))}
          </tbody>
        </Table>
      )}
    </DataPanel>
  );
}

// Resolve a rule's scope into a human-readable string, using instance names
// (display_name > hostname > id) instead of raw IDs. Matches the same
// fallback logic hostLabel uses everywhere else.
function scopeLabel(
  r: PerfAlertRule,
  instancesById: Map<string, PerfAlertInstance>,
): string {
  const ids = r.instance_ids ?? [];
  if (ids.length > 0) {
    const names = ids.map((id) => {
      const inst = instancesById.get(id);
      return inst ? hostLabel(inst) : id;
    });
    // Compact past 3 to keep the trigger cell readable.
    if (names.length <= 3) return names.join(", ");
    return `${names.slice(0, 3).join(", ")} +${names.length - 3} more`;
  }
  if (r.instance_id) {
    const inst = instancesById.get(r.instance_id);
    return inst ? hostLabel(inst) : r.instance_id;
  }
  if (r.tag_key) return `tag ${r.tag_key}=${r.tag_value}`;
  return "all hosts";
}

function MetricRow({
  rule: r,
  instancesById,
}: {
  rule: PerfAlertRule;
  instancesById: Map<string, PerfAlertInstance>;
}) {
  const minutes = Math.max(1, Math.round(r.window_seconds / 60));
  const scope = scopeLabel(r, instancesById);
  const opText =
    { gte: "≥", gt: ">", lte: "≤", lt: "<" }[r.comparison] ?? "≥";
  return (
    <tr className="border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="truncate px-4 py-2 align-middle text-sm text-fg">
        {METRIC_LABEL[r.metric] ?? r.metric}
      </td>
      <td className="truncate px-4 py-2 align-middle font-mono text-xs text-fg-muted">
        {opText} {r.threshold}% / {minutes}m · {scope}
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
        <div className="inline-flex items-center gap-1.5">
          <form action={togglePerfAlertAction} className="inline">
            <input type="hidden" name="id" value={r.id} />
            <input type="hidden" name="target" value={r.enabled ? "off" : "on"} />
            <PendingButton size="sm" variant="secondary" pendingLabel="…">
              {r.enabled ? "Turn off" : "Turn on"}
            </PendingButton>
          </form>
          <Button asChild size="sm" variant="ghost" aria-label="Edit metric">
            <Link href={`/notifications/perf-alerts/${encodeURIComponent(r.id)}/edit`}>
              <Pencil size={12} />
            </Link>
          </Button>
          <form action={deletePerfAlertAction} className="inline">
            <input type="hidden" name="id" value={r.id} />
            <input type="hidden" name="name" value={r.name} />
            <PendingButton size="sm" variant="danger" pendingLabel="…">
              <Trash2 size={11} /> Delete
            </PendingButton>
          </form>
        </div>
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
        <Table tableId="notifications-activity" ariaLabel="Recent notification activity">
          <thead>
            <tr>
              <th style={{ width: 160 }}>Time</th>
              <th style={{ width: 120 }}>Status</th>
              <th style={{ width: 180 }}>Channel</th>
              <th style={{ width: 220 }}>Rule</th>
              <th style={{ width: 480 }}>Event</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <ActivityRow key={String(e.id)} entry={e} />
            ))}
          </tbody>
        </Table>
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
            <code className="font-mono text-xs text-fg-muted">{e.event_action ?? "—"}</code>
          )}
          {e.event_severity && <SeverityBadge severity={e.event_severity} />}
        </div>
      </td>
    </tr>
  );
}

function ActivityStatusPill({ status }: { status: string }) {
  const sevMap: Record<string, Severity> = {
    sent: "resolved",
    failed: "critical",
    rate_limited: "medium",
    throttled: "medium",
    digested: "low",
    acked: "neutral",
  };
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <StatusDot severity={sevMap[status] ?? "neutral"} />
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
          {acks.length} active ack{acks.length === 1 ? "" : "s"} · paused notifications
        </span>
      </div>
      <div className="divide-y divide-line-soft">
        {acks.map((a) => (
          <div
            key={a.fingerprint}
            className="grid grid-cols-[1fr_220px_80px] items-center gap-4 px-4 py-2 text-xs"
          >
            <div className="truncate">
              <code className="font-mono text-fg">{a.fingerprint.slice(0, 24)}…</code>
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
// HINTS + SMALL BITS
// =========================================================================

function ChannelsFirstHint() {
  return (
    <div className="mt-3 border border-sev-medium/30 bg-sev-medium/5 px-4 py-3 text-sm text-fg-muted">
      <span className="text-sev-medium">▸</span> Start by adding a channel — Slack,
      email, webhook, PagerDuty, etc.{" "}
      <Link href="/notifications/channels/new" className="text-signal hover:underline">
        Add one →
      </Link>{" "}
      then create alerts below.
    </div>
  );
}

function EnabledPill({ enabled }: { enabled: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <StatusDot severity={enabled ? "resolved" : "neutral"} />
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
  const sev: Severity = status === "ok" ? "resolved" : status ? "critical" : "neutral";
  const label = status ?? "never";
  return (
    <span title={error ?? undefined} className="inline-flex items-center gap-1.5 text-xs">
      <StatusDot severity={sev} />
      <span className={status ? "text-fg-muted" : "text-fg-subtle"}>{label}</span>
    </span>
  );
}

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
