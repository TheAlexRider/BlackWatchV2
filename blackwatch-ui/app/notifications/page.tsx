import Link from "next/link";
import clsx from "clsx";
import { Plus, Pencil, X, ArrowRight } from "lucide-react";

import {
  fetchNotificationChannels,
  fetchNotificationRules,
  fetchNotificationLog,
  fetchNotificationAcks,
  fetchPerfAlerts,
} from "@/lib/api";
import type {
  NotificationChannel,
  NotificationRule,
  NotificationLogEntry,
  NotificationAck,
  PerfAlertRule,
} from "@/lib/types";

import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { SeverityBadge } from "@/components/domain/SeverityBadge";

import {
  testChannelAction,
  toggleChannelAction,
  deleteChannelAction,
  toggleRuleAction,
  silenceRuleAction,
  deleteRuleAction,
  clearAckAction,
} from "./actions";

import {
  togglePerfAlertAction,
  deletePerfAlertAction,
} from "./perf-alerts/actions";

type SearchParams = { msg?: string };

export default async function NotificationsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { msg } = await searchParams;
  const [channelsData, rulesData, logData, acksData, perfData] = await Promise.all([
    fetchNotificationChannels(),
    fetchNotificationRules(),
    fetchNotificationLog({ limit: 50 }),
    fetchNotificationAcks(),
    fetchPerfAlerts(),
  ]);

  return (
    <>
      <AutoRefresh intervalMs={5000} />
      <PageHeader
        title="Notifications"
        subtitle={
          `${channelsData.count} channel${channelsData.count === 1 ? "" : "s"} · ` +
          `${rulesData.count} event rule${rulesData.count === 1 ? "" : "s"} · ` +
          `${perfData.rules.length} performance alert${perfData.rules.length === 1 ? "" : "s"}`
        }
      />

      {msg && <FlashBar message={msg} />}

      {acksData.acks.length > 0 && <AcksBanner acks={acksData.acks} />}

      <RoutingCta />

      <ChannelsSection channels={channelsData.channels} />
      <RulesSection
        rules={rulesData.rules}
        channelsAvailable={channelsData.channels.length > 0}
      />
      <PerfAlertsSection
        rules={perfData.rules}
        channelsAvailable={channelsData.channels.length > 0}
      />
      <RecentActivitySection entries={logData.entries} />
    </>
  );
}

// =========================================================================
// routing cta — hero link to /notifications/routing
// =========================================================================

function RoutingCta() {
  return (
    <Link
      href="/notifications/routing"
      className="mt-2 flex items-center justify-between border border-signal/30 bg-signal/5 px-4 py-3 text-sm transition-colors hover:bg-signal/10"
    >
      <div className="flex items-baseline gap-3">
        <span className="text-signal">▸</span>
        <div>
          <div className="text-fg">Set up alerts by module</div>
          <div className="text-xs text-fg-subtle">
            One channel + one severity per module. No rule editor. Recommended
            for most setups.
          </div>
        </div>
      </div>
      <ArrowRight size={14} className="text-signal" />
    </Link>
  );
}

// =========================================================================
// channels
// =========================================================================

function ChannelsSection({ channels }: { channels: NotificationChannel[] }) {
  return (
    <section className="mt-2 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>channels</SectionLabel>
        <Button asChild variant="ghost" size="sm">
          <Link href="/notifications/channels/new">
            <Plus size={12} /> add channel
          </Link>
        </Button>
      </div>
      <DataPanel className="overflow-hidden">
        {channels.length === 0 ? (
          <EmptyState>
            No channels yet.{" "}
            <Link
              href="/notifications/channels/new"
              className="text-signal hover:underline"
            >
              Add one →
            </Link>
          </EmptyState>
        ) : (
          <table className="w-full table-fixed text-sm">
            <thead>
              <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
                <th className="w-48 px-4 py-2 text-left font-normal">Name</th>
                <th className="w-24 px-4 py-2 text-left font-normal">Type</th>
                <th className="w-28 px-4 py-2 text-left font-normal">State</th>
                <th className="w-32 px-4 py-2 text-left font-normal">Last status</th>
                <th className="w-36 px-4 py-2 text-left font-normal">Last sent</th>
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
    </section>
  );
}

function ChannelRow({ channel: c }: { channel: NotificationChannel }) {
  return (
    <tr className="border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="truncate px-4 py-2.5">
        <Link
          href={`/notifications/channels/${c.id}`}
          className="text-sm text-fg transition-colors hover:text-signal"
        >
          {c.name}
        </Link>
      </td>
      <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">{c.type}</td>
      <td className="px-4 py-2.5">
        <EnabledPill enabled={c.enabled} />
      </td>
      <td className="px-4 py-2.5">
        <ChannelStatusPill status={c.last_status} error={c.last_error} />
      </td>
      <td className="px-4 py-2.5">
        {c.last_sent_at ? (
          <TimestampCell value={c.last_sent_at} />
        ) : (
          <span className="font-mono text-xs text-fg-disabled">—</span>
        )}
      </td>
      <td className="whitespace-nowrap px-4 py-2.5 text-right">
        <div className="inline-flex items-center gap-1.5">
          <form action={testChannelAction} className="inline">
            <input type="hidden" name="id" value={c.id} />
            <Button type="submit" size="sm" variant="secondary">
              Test
            </Button>
          </form>
          <form action={toggleChannelAction} className="inline">
            <input type="hidden" name="id" value={c.id} />
            <input type="hidden" name="enabled" value={c.enabled ? "off" : "on"} />
            <Button type="submit" size="sm" variant="secondary">
              {c.enabled ? "Disable" : "Enable"}
            </Button>
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
// rules
// =========================================================================

function RulesSection({
  rules,
  channelsAvailable,
}: {
  rules: NotificationRule[];
  channelsAvailable: boolean;
}) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>advanced rules · custom conditions</SectionLabel>
        <Button asChild variant="ghost" size="sm">
          <Link href="/notifications/rules/new">
            <Plus size={12} /> add rule
          </Link>
        </Button>
      </div>
      <DataPanel className="overflow-hidden">
        {rules.length === 0 ? (
          <EmptyState>
            No custom rules — most setups don&apos;t need any. Use{" "}
            <Link
              href="/notifications/routing"
              className="text-signal hover:underline"
            >
              module setup
            </Link>{" "}
            for per-module routing, or{" "}
            <Link
              href="/notifications/rules/new"
              className="text-signal hover:underline"
            >
              add a custom rule
            </Link>{" "}
            for action-specific conditions.
          </EmptyState>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
                <th className="w-48 px-4 py-2 text-left font-normal">Name</th>
                <th className="px-4 py-2 text-left font-normal">Tell me when…</th>
                <th className="w-56 px-4 py-2 text-left font-normal">Send to</th>
                <th className="w-28 px-4 py-2 text-left font-normal">State</th>
                <th className="w-80 px-4 py-2 text-right font-normal" />
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <RuleRow key={r.id} rule={r} />
              ))}
            </tbody>
          </table>
        )}
      </DataPanel>
    </section>
  );
}

function RuleRow({ rule: r }: { rule: NotificationRule }) {
  return (
    <tr className="border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="truncate px-4 py-2.5">
        <Link
          href={`/notifications/rules/${r.id}`}
          className="text-sm text-fg transition-colors hover:text-signal"
        >
          {r.name}
        </Link>
      </td>
      <td className="px-4 py-2.5">
        <CriteriaSummary match={r.match} />
      </td>
      <td className="px-4 py-2.5">
        <div className="flex flex-wrap gap-1">
          {r.channels.length === 0 ? (
            <span className="text-fg-disabled">—</span>
          ) : (
            r.channels.map((c) => (
              <span
                key={c}
                className="border border-line px-1.5 py-0.5 font-mono text-[10px] text-fg-muted"
              >
                {c}
              </span>
            ))
          )}
        </div>
      </td>
      <td className="px-4 py-2.5">
        <RuleStatePill rule={r} />
      </td>
      <td className="whitespace-nowrap px-4 py-2.5 text-right">
        <div className="inline-flex items-center gap-1.5">
          <form action={silenceRuleAction} className="inline-flex items-center gap-1">
            <input type="hidden" name="id" value={r.id} />
            <NativeSelect name="hours" defaultValue="1" className="h-7 text-xs">
              <option value="1">1h</option>
              <option value="4">4h</option>
              <option value="24">24h</option>
              <option value="0">clear</option>
            </NativeSelect>
            <Button type="submit" size="sm" variant="secondary">
              Silence
            </Button>
          </form>
          <form action={toggleRuleAction} className="inline">
            <input type="hidden" name="id" value={r.id} />
            <input type="hidden" name="enabled" value={r.enabled ? "off" : "on"} />
            <Button type="submit" size="sm" variant="secondary">
              {r.enabled ? "Disable" : "Enable"}
            </Button>
          </form>
          <Button asChild size="sm" variant="ghost">
            <Link href={`/notifications/rules/${r.id}`}>
              <Pencil size={12} />
            </Link>
          </Button>
          <form action={deleteRuleAction} className="inline">
            <input type="hidden" name="id" value={r.id} />
            <Button type="submit" size="sm" variant="danger">
              Delete
            </Button>
          </form>
        </div>
      </td>
    </tr>
  );
}

// Plain-English summary of a rule's match. Reads the same Condition tree the
// engine evaluates, but writes it the way an on-call engineer would explain it
// out loud — "high or worse · in iam · action contains login". Anything we
// can't translate falls through to a small "custom" pill (the operator can
// open the rule to see the JSON).
function CriteriaSummary({ match }: { match: Record<string, unknown> }) {
  const parts: string[] = [];
  let sawUnknown = false;

  const all =
    (match.all as unknown[]) ?? (Object.keys(match).length > 0 ? [match] : []);

  for (const p of all) {
    if (typeof p !== "object" || p === null) {
      sawUnknown = true;
      continue;
    }
    const part = p as Record<string, unknown>;
    // Accept BOTH the shortcut shape ({field, in: [...]}) and the canonical
    // shape ({field, op: "in", value: [...]}). Only the canonical shape is
    // actually evaluated by the engine; the shortcut form is rendered too so
    // legacy rules look right until the user re-saves them.
    const inList: string[] | null =
      Array.isArray(part.in)
        ? (part.in as string[])
        : part.op === "in" && Array.isArray(part.value)
        ? (part.value as string[])
        : null;
    const iContainsValue: string | null =
      typeof part.icontains === "string"
        ? (part.icontains as string)
        : part.op === "icontains" && typeof part.value === "string"
        ? (part.value as string)
        : null;

    if (part.field === "severity" && inList) {
      parts.push(severityPhrase(inList));
    } else if (part.field === "category" && inList) {
      parts.push(`in ${inList.join(" or ")}`);
    } else if (part.field === "source.module" && inList) {
      parts.push(`from ${inList.join(" or ")}`);
    } else if (part.field === "action" && iContainsValue !== null) {
      parts.push(`action contains "${iContainsValue}"`);
    } else {
      sawUnknown = true;
    }
  }

  if (parts.length === 0 && !sawUnknown) {
    return (
      <span className="text-xs text-fg-subtle">everything (no filter)</span>
    );
  }

  return (
    <span className="text-xs text-fg-muted">
      {parts.join(" · ")}
      {sawUnknown && (
        <span className="ml-1.5 border border-line-soft px-1 py-0.5 text-[10px] uppercase tracking-[0.06em] text-fg-subtle">
          custom
        </span>
      )}
    </span>
  );
}

// "{critical}" -> "only emergencies"
// "{critical,high}" -> "high or worse"
// "{critical,high,medium}" -> "medium or worse"
// "{critical,high,medium,low}" -> "low or worse"
// anything else -> raw join, in case the rule was hand-edited
function severityPhrase(sevs: string[]): string {
  const set = new Set(sevs);
  if (set.size === 1 && set.has("critical")) return "only emergencies";
  if (set.size === 2 && set.has("critical") && set.has("high"))
    return "high or worse";
  if (
    set.size === 3 &&
    set.has("critical") &&
    set.has("high") &&
    set.has("medium")
  )
    return "medium or worse";
  if (
    set.size === 4 &&
    set.has("critical") &&
    set.has("high") &&
    set.has("medium") &&
    set.has("low")
  )
    return "low or worse";
  return sevs.join(" / ");
}

function RuleStatePill({ rule }: { rule: NotificationRule }) {
  if (!rule.enabled) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span className="h-1.5 w-1.5 rounded-full bg-fg-subtle" aria-hidden />
        <span className="text-fg-subtle">disabled</span>
      </span>
    );
  }
  if (rule.silenced) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span className="h-1.5 w-1.5 rounded-full bg-sev-medium" aria-hidden />
        <span className="text-fg-muted">silenced</span>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className="h-1.5 w-1.5 rounded-full bg-sev-resolved" aria-hidden />
      <span className="text-fg-muted">active</span>
    </span>
  );
}

// =========================================================================
// performance alerts (threshold-based)
// =========================================================================

const METRIC_LABEL: Record<string, string> = {
  memory_pct: "Memory %",
  cpu_load_norm: "CPU load (norm)",
  disk_pct_max: "Disk % (worst mount)",
};

const COMPARISON_SYM: Record<string, string> = {
  gte: "≥",
  gt: ">",
  lte: "≤",
  lt: "<",
};

function PerfAlertsSection({
  rules,
  channelsAvailable,
}: {
  rules: PerfAlertRule[];
  channelsAvailable: boolean;
}) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>performance alerts · threshold-based</SectionLabel>
        <Button asChild variant="ghost" size="sm">
          <Link href="/notifications/perf-alerts/new">
            <Plus size={12} className="mr-1" /> new
          </Link>
        </Button>
      </div>
      <DataPanel className="overflow-hidden">
        {!channelsAvailable ? (
          <div className="px-6 py-8 text-center text-sm text-fg-muted">
            Create a notification channel above first — perf alerts need
            somewhere to send their pings.
          </div>
        ) : rules.length === 0 ? (
          <div className="px-6 py-8 text-center text-sm text-fg-muted">
            No performance alerts yet.{" "}
            <Link
              href="/notifications/perf-alerts/new"
              className="text-signal hover:underline"
            >
              Create one
            </Link>
            {" "}— alerts trigger when a metric stays above your threshold
            for the configured window.
          </div>
        ) : (
          <table className="w-full table-fixed text-sm">
            <thead>
              <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
                <th className="w-12 px-4 py-2 text-left font-normal">On</th>
                <th className="px-4 py-2 text-left font-normal">Alert</th>
                <th className="w-44 px-4 py-2 text-left font-normal">Scope</th>
                <th className="w-44 px-4 py-2 text-left font-normal">Condition</th>
                <th className="w-32 px-4 py-2 text-left font-normal">Channels</th>
                <th className="w-24 px-4 py-2 text-right font-normal">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <PerfAlertRow key={r.id} rule={r} />
              ))}
            </tbody>
          </table>
        )}
      </DataPanel>
    </section>
  );
}

function PerfAlertRow({ rule }: { rule: PerfAlertRule }) {
  const minutes = Math.max(1, Math.round(rule.window_seconds / 60));
  const metric = METRIC_LABEL[rule.metric] ?? rule.metric;
  const sym = COMPARISON_SYM[rule.comparison] ?? rule.comparison;
  const scope = rule.instance_id
    ? rule.instance_id
    : rule.tag_key
    ? `tag ${rule.tag_key}=${rule.tag_value}`
    : "—";

  return (
    <tr className="border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="px-4 py-2.5">
        <form action={togglePerfAlertAction.bind(null, rule.id, !rule.enabled)}>
          <button
            type="submit"
            className="inline-flex items-center"
            aria-label={rule.enabled ? "Disable" : "Enable"}
          >
            <span
              className={clsx(
                "h-1.5 w-1.5 rounded-full",
                rule.enabled ? "bg-sev-resolved" : "bg-fg-disabled",
              )}
              aria-hidden
            />
            <span className="ml-1.5 text-xs text-fg-muted">
              {rule.enabled ? "on" : "off"}
            </span>
          </button>
        </form>
      </td>
      <td className="truncate px-4 py-2.5 text-sm text-fg">
        {rule.name}
        {rule.last_value != null && (
          <span className="ml-2 text-[11px] text-fg-subtle">
            (last: {rule.last_value.toFixed(1)}%)
          </span>
        )}
      </td>
      <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
        {scope}
      </td>
      <td className="truncate px-4 py-2.5 text-xs text-fg-muted">
        {metric} {sym} {rule.threshold}% / {minutes}m
      </td>
      <td className="truncate px-4 py-2.5 text-xs text-fg-muted">
        {(rule.channels || []).join(", ") || "—"}
      </td>
      <td className="px-4 py-2.5 text-right">
        <div className="inline-flex items-center gap-1">
          <Link
            href={`/notifications/perf-alerts/${encodeURIComponent(rule.id)}/edit`}
            className="rounded p-1 text-fg-muted hover:bg-surface-3 hover:text-fg"
            aria-label="Edit"
          >
            <Pencil size={14} />
          </Link>
          <form action={deletePerfAlertAction.bind(null, rule.id, rule.name)}>
            <button
              type="submit"
              className="rounded p-1 text-fg-muted hover:bg-surface-3 hover:text-fg"
              aria-label="Delete"
            >
              <X size={14} />
            </button>
          </form>
        </div>
      </td>
    </tr>
  );
}

// =========================================================================
// recent activity
// =========================================================================

function RecentActivitySection({ entries }: { entries: NotificationLogEntry[] }) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>recent activity · last 50</SectionLabel>
        <Link
          href="/notifications/log"
          className="text-[11px] text-fg-subtle hover:text-fg"
        >
          full log →
        </Link>
      </div>
      <DataPanel className="overflow-hidden">
        {entries.length === 0 ? (
          <EmptyState>
            Nothing fired yet. When a rule matches an event, you&apos;ll see it
            here.
          </EmptyState>
        ) : (
          <table className="w-full table-fixed text-sm">
            <thead>
              <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
                <th className="w-32 px-4 py-2 text-left font-normal">Time</th>
                <th className="w-24 px-4 py-2 text-left font-normal">Status</th>
                <th className="w-32 px-4 py-2 text-left font-normal">Channel</th>
                <th className="w-40 px-4 py-2 text-left font-normal">Rule</th>
                <th className="px-4 py-2 text-left font-normal">Event</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <LogRow key={String(e.id)} entry={e} />
              ))}
            </tbody>
          </table>
        )}
      </DataPanel>
    </section>
  );
}

function LogRow({ entry: e }: { entry: NotificationLogEntry }) {
  return (
    <tr className="border-b border-line-soft last:border-0">
      <td className="px-4 py-2">
        <TimestampCell value={e.ts} />
      </td>
      <td className="px-4 py-2">
        <LogStatusPill status={e.status} />
      </td>
      <td className="truncate px-4 py-2 text-xs text-fg-muted">
        {e.channel_name ?? "—"}
      </td>
      <td className="truncate px-4 py-2 text-xs text-fg-muted">
        {e.rule_name ?? "—"}
      </td>
      <td className="truncate px-4 py-2">
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
          {e.event_severity && (
            <SeverityBadge severity={e.event_severity} />
          )}
        </div>
      </td>
    </tr>
  );
}

function LogStatusPill({ status }: { status: string }) {
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
// acks banner
// =========================================================================

function AcksBanner({ acks }: { acks: NotificationAck[] }) {
  return (
    <section className="mb-6 border border-line-soft bg-surface-1">
      <div className="flex items-baseline justify-between border-b border-line-soft px-4 py-2">
        <SectionLabel>
          {acks.length} active ack{acks.length === 1 ? "" : "s"} · paused
          notifications
        </SectionLabel>
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
              {a.reason && (
                <span className="ml-2 text-fg-muted">· {a.reason}</span>
              )}
            </div>
            <div className="text-fg-subtle">
              until <TimestampCell value={a.ack_until} />
            </div>
            <div className="text-right">
              <form action={clearAckAction} className="inline">
                <input
                  type="hidden"
                  name="fingerprint"
                  value={a.fingerprint}
                />
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
// shared bits
// =========================================================================

function FlashBar({ message }: { message: string }) {
  return (
    <div className="mb-4 border-l-2 border-signal bg-surface-1 px-3 py-2 text-xs text-fg-muted">
      <span className="text-signal">·</span> {message}
    </div>
  );
}

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

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-6 py-10 text-center text-sm text-fg-muted">
      {children}
    </div>
  );
}
