import Link from "next/link";
import clsx from "clsx";
import { Plus, Pencil, X } from "lucide-react";

import {
  fetchNotificationCards,
  fetchNotificationChannels,
  fetchNotificationRules,
  fetchNotificationLog,
  fetchNotificationAcks,
  fetchPerfAlerts,
  fetchPerfQuick,
} from "@/lib/api";
import type {
  NotificationChannel,
  NotificationLogEntry,
  NotificationAck,
  NotificationRule,
  PerfAlertRule,
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

import { ModuleLane } from "./ModuleLane";
import { MetricLane } from "./MetricLane";
import { CustomLane } from "./CustomLane";

type SearchParams = { msg?: string };

// One page. Three tracks. Every alert source is a lane.
//
// The layout reads top-to-bottom like an oscilloscope panel: a compact
// status strip up top, channels track, then the ALERT SOURCES tracks
// (module / metric / custom) — every lane sharing the same visual
// grammar so the eye scans them as one instrument.
export default async function NotificationsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { msg } = await searchParams;
  const [
    channelsData,
    rulesData,
    logData,
    acksData,
    cardsData,
    perfQuickData,
    perfAllData,
  ] = await Promise.all([
    fetchNotificationChannels(),
    fetchNotificationRules(), // hides auto:* by default — leaves only hand-crafted rules
    fetchNotificationLog({ limit: 200 }),
    fetchNotificationAcks(),
    fetchNotificationCards(),
    fetchPerfQuick(),
    fetchPerfAlerts(),
  ]);
  // Custom perf-alerts = hand-crafted (not from the metric-lane quick UI).
  // We list them as a small "advanced" section so users who used the full
  // form still see their creations here without them cluttering the main
  // metric lanes.
  const customPerfAlerts = perfAllData.rules.filter(
    (r) => !(r.name || "").startsWith("auto:perf:"),
  );

  const channelsAvailable = channelsData.channels.length > 0;

  // ---- status strip metrics ----
  const coverageModules = cardsData.cards.filter((c) => c.channel).length;
  const coverageMetrics = perfQuickData.cards.filter((m) => m.existing.length > 0).length;
  const now24h = Date.now() - 24 * 60 * 60 * 1000;
  const sent24h = logData.entries.filter(
    (e) => e.status === "sent" && new Date(e.ts).getTime() >= now24h,
  ).length;
  const failed24h = logData.entries.filter(
    (e) => e.status === "failed" && new Date(e.ts).getTime() >= now24h,
  ).length;
  const errorChannels = channelsData.channels.filter(
    (c) => c.enabled && c.last_status && c.last_status !== "ok",
  ).length;
  const silencedCount =
    cardsData.cards.filter((c) => {
      if (!c.silence_until) return false;
      return new Date(c.silence_until).getTime() > Date.now();
    }).length +
    rulesData.rules.filter((r) => r.silenced).length;

  return (
    <>
      {/* Refresh less aggressively than before — lane actions already
          trigger revalidatePath, so the only reason to poll is to catch
          new activity entries and channel status drifts. 30s is fine. */}
      <AutoRefresh intervalMs={30000} />
      <PageHeader title="Notifications" subtitle="signal routing · quiet by default" />

      <StatusStrip
        coverageModules={coverageModules}
        totalModules={cardsData.cards.length}
        coverageMetrics={coverageMetrics}
        totalMetrics={perfQuickData.cards.length}
        sent24h={sent24h}
        failed24h={failed24h}
        errorChannels={errorChannels}
        silencedCount={silencedCount}
      />

      {msg && <FlashToast message={msg} />}

      {acksData.acks.length > 0 && <AcksBanner acks={acksData.acks} />}

      {!channelsAvailable && <ChannelsFirstHint />}

      {/* ═══════════════ CHANNELS ═══════════════ */}
      <TrackHeader label="channels" href="/notifications/channels/new" cta="add channel" />
      <ChannelsTrack channels={channelsData.channels} />

      {/* ═══════════════ WHAT SENDS ALERTS ═══════════════ */}
      <div className="mt-8">
        <div className="mb-2 flex items-baseline gap-3">
          <span className="text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
            what sends alerts
          </span>
          <span className="h-px flex-1 bg-line-soft" />
        </div>

        <SubTrackLabel>by module</SubTrackLabel>
        <DataPanel className="p-0">
          {cardsData.cards.map((card) => (
            <ModuleLane
              key={card.module}
              card={card}
              channels={cardsData.channels}
              disabled={!channelsAvailable}
            />
          ))}
        </DataPanel>

        <SubTrackLabel>metrics</SubTrackLabel>
        <DataPanel className="p-0">
          {perfQuickData.cards.map((mcard) => (
            <MetricLane
              key={mcard.metric}
              card={mcard}
              channels={perfQuickData.channels}
              instances={perfQuickData.instances}
              disabled={!channelsAvailable}
            />
          ))}
        </DataPanel>

        <div className="mt-6 mb-2 flex items-baseline justify-between">
          <SubTrackLabelInline>custom rules</SubTrackLabelInline>
          <Button asChild variant="ghost" size="sm">
            <Link href="/notifications/rules/new">
              <Plus size={12} /> new rule
            </Link>
          </Button>
        </div>
        <DataPanel className="p-0">
          {rulesData.rules.length === 0 ? (
            <div className="px-4 py-6 text-center text-xs text-fg-muted">
              No custom rules — module and metric lanes cover most needs.{" "}
              <Link
                href="/notifications/rules/new"
                className="text-signal hover:underline"
              >
                Add a custom rule
              </Link>{" "}
              only if you need action-specific conditions.
            </div>
          ) : (
            rulesData.rules.map((rule) => (
              <CustomLane
                key={rule.id}
                rule={rule}
                channels={cardsData.channels}
              />
            ))
          )}
        </DataPanel>

        {customPerfAlerts.length > 0 && (
          <>
            <div className="mt-6 mb-2 flex items-baseline justify-between">
              <SubTrackLabelInline>custom perf alerts</SubTrackLabelInline>
              <Button asChild variant="ghost" size="sm">
                <Link href="/notifications/perf-alerts/new">
                  <Plus size={12} /> new
                </Link>
              </Button>
            </div>
            <CustomPerfAlertsList rules={customPerfAlerts} />
          </>
        )}
      </div>

      {/* ═══════════════ ACTIVITY ═══════════════ */}
      <div className="mt-8">
        <div className="mb-2 flex items-baseline justify-between">
          <div className="flex items-baseline gap-3">
            <span className="text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
              activity · last 50
            </span>
          </div>
          <Link
            href="/notifications/log"
            className="text-[11px] text-fg-subtle hover:text-fg"
          >
            full log →
          </Link>
        </div>
        <ActivityList entries={logData.entries.slice(0, 50)} />
      </div>
    </>
  );
}

// =========================================================================
// STATUS STRIP — mission-control style compact header
// =========================================================================

function StatusStrip({
  coverageModules,
  totalModules,
  coverageMetrics,
  totalMetrics,
  sent24h,
  failed24h,
  errorChannels,
  silencedCount,
}: {
  coverageModules: number;
  totalModules: number;
  coverageMetrics: number;
  totalMetrics: number;
  sent24h: number;
  failed24h: number;
  errorChannels: number;
  silencedCount: number;
}) {
  return (
    <div className="mt-1 grid grid-cols-1 gap-0 border-y border-line-soft bg-surface-1 md:grid-cols-3">
      <StatusCell label="coverage">
        <span className="text-fg">
          {coverageModules}
          <span className="text-fg-subtle">/{totalModules}</span>
        </span>
        <span className="ml-1 text-fg-subtle">modules</span>
        <span className="mx-2 text-fg-disabled">·</span>
        <span className="text-fg">
          {coverageMetrics}
          <span className="text-fg-subtle">/{totalMetrics}</span>
        </span>
        <span className="ml-1 text-fg-subtle">metrics</span>
      </StatusCell>

      <StatusCell label="last 24h" border>
        <span className="text-fg">{sent24h}</span>
        <span className="ml-1 text-fg-subtle">sent</span>
        <span className="mx-2 text-fg-disabled">·</span>
        <span className={failed24h > 0 ? "text-sev-critical" : "text-fg"}>
          {failed24h}
        </span>
        <span className="ml-1 text-fg-subtle">failed</span>
      </StatusCell>

      <StatusCell label="active" border>
        {errorChannels > 0 ? (
          <>
            <span className="text-sev-critical">{errorChannels}</span>
            <span className="ml-1 text-fg-subtle">channel error{errorChannels === 1 ? "" : "s"}</span>
          </>
        ) : silencedCount > 0 ? (
          <>
            <span className="text-sev-medium">{silencedCount}</span>
            <span className="ml-1 text-fg-subtle">silenced</span>
          </>
        ) : (
          <span className="text-fg-subtle">nothing to look at</span>
        )}
      </StatusCell>
    </div>
  );
}

function StatusCell({
  label,
  children,
  border,
}: {
  label: string;
  children: React.ReactNode;
  border?: boolean;
}) {
  return (
    <div
      className={clsx(
        "px-4 py-2.5 text-xs",
        border && "md:border-l md:border-line-soft",
      )}
    >
      <div className="text-[10px] uppercase tracking-[0.14em] text-fg-subtle">
        {label}
      </div>
      <div className="mt-0.5 font-mono">{children}</div>
    </div>
  );
}

// =========================================================================
// TRACK HEADERS
// =========================================================================

function TrackHeader({
  label,
  href,
  cta,
}: {
  label: string;
  href?: string;
  cta?: string;
}) {
  return (
    <div className="mt-6 mb-2 flex items-baseline justify-between">
      <div className="flex items-baseline gap-3">
        <span className="text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
          {label}
        </span>
      </div>
      {href && cta && (
        <Button asChild variant="ghost" size="sm">
          <Link href={href}>
            <Plus size={12} /> {cta}
          </Link>
        </Button>
      )}
    </div>
  );
}

function SubTrackLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-6 mb-2 flex items-center gap-3">
      <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-subtle">
        ▎ {children}
      </span>
      <span className="h-px flex-1 bg-line-soft" />
    </div>
  );
}

function SubTrackLabelInline({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-subtle">
      ▎ {children}
    </span>
  );
}

// =========================================================================
// CHANNELS TRACK — kept as a compact table for now (simpler shape than
// alert lanes; converting to lanes adds no value here).
// =========================================================================

function ChannelsTrack({ channels }: { channels: NotificationChannel[] }) {
  if (channels.length === 0) {
    return (
      <DataPanel>
        <div className="px-4 py-6 text-center text-xs text-fg-muted">
          No channels yet.{" "}
          <Link
            href="/notifications/channels/new"
            className="text-signal hover:underline"
          >
            Add one →
          </Link>
        </div>
      </DataPanel>
    );
  }
  return (
    <DataPanel className="overflow-hidden">
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
    </DataPanel>
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
// CUSTOM PERF ALERTS — compact list for hand-crafted perf-alert rules
// =========================================================================

const METRIC_LABEL: Record<string, string> = {
  memory_pct: "Memory %",
  cpu_load_norm: "CPU load (norm)",
  disk_pct_max: "Disk %",
};

function CustomPerfAlertsList({ rules }: { rules: PerfAlertRule[] }) {
  return (
    <DataPanel className="p-0">
      {rules.map((r) => (
        <div
          key={r.id}
          className={clsx(
            "flex items-center gap-3 border-b border-b-line-soft border-l-2 px-4 py-2.5 text-sm last:border-b-0",
            r.enabled ? "border-l-signal" : "border-l-line-soft",
          )}
        >
          <div className="min-w-0 flex-1 truncate">
            <span className="text-fg">{r.name}</span>
            <span className="ml-2 font-mono text-[10px] text-fg-subtle">
              {METRIC_LABEL[r.metric] ?? r.metric} ≥ {r.threshold}% /{" "}
              {Math.max(1, Math.round(r.window_seconds / 60))}m ·{" "}
              {r.instance_id ??
                (r.tag_key ? `${r.tag_key}=${r.tag_value}` : "all hosts")}
            </span>
          </div>
          <span className="font-mono text-xs text-fg-muted">
            → {(r.channels || []).join(", ") || "—"}
          </span>
          <span
            className={clsx(
              "text-xs",
              r.enabled ? "text-signal" : "text-fg-subtle",
            )}
          >
            {r.enabled ? "on" : "off"}
          </span>
          <Link
            href={`/notifications/perf-alerts/${encodeURIComponent(r.id)}/edit`}
            className="rounded p-1 text-fg-muted hover:bg-surface-2 hover:text-fg"
            aria-label="Edit"
          >
            <Pencil size={12} />
          </Link>
        </div>
      ))}
    </DataPanel>
  );
}

// =========================================================================
// ACTIVITY
// =========================================================================

function ActivityList({ entries }: { entries: NotificationLogEntry[] }) {
  if (entries.length === 0) {
    return (
      <DataPanel>
        <div className="px-4 py-6 text-center text-xs text-fg-muted">
          Nothing has fired yet. When a rule matches an event, you&apos;ll see it here.
        </div>
      </DataPanel>
    );
  }
  return (
    <DataPanel className="overflow-hidden">
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
            <ActivityRow key={String(e.id)} entry={e} />
          ))}
        </tbody>
      </table>
    </DataPanel>
  );
}

function ActivityRow({ entry: e }: { entry: NotificationLogEntry }) {
  return (
    <tr className="border-b border-line-soft last:border-0">
      <td className="px-4 py-2">
        <TimestampCell value={e.ts} />
      </td>
      <td className="px-4 py-2">
        <ActivityStatusPill status={e.status} />
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
// HINTS
// =========================================================================

function ChannelsFirstHint() {
  return (
    <div className="mt-3 border border-sev-medium/30 bg-sev-medium/5 px-4 py-3 text-sm text-fg-muted">
      <span className="text-sev-medium">▸</span> Start by adding a channel — Slack,
      email, webhook, PagerDuty, etc.{" "}
      <Link href="/notifications/channels/new" className="text-signal hover:underline">
        Add one →
      </Link>{" "}
      then wire it to modules below.
    </div>
  );
}

// =========================================================================
// SMALL SHARED BITS
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
