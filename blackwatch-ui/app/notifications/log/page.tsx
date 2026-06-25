import Link from "next/link";
import clsx from "clsx";
import { ArrowLeft } from "lucide-react";

import { fetchNotificationLog } from "@/lib/api";
import type { NotificationLogEntry } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { SeverityBadge } from "@/components/domain/SeverityBadge";
import { AutoRefresh } from "@/components/layout/AutoRefresh";

const STATUSES = ["sent", "failed", "rate_limited", "throttled", "digested", "acked"];

type SearchParams = {
  status?: string;
  channel?: string;
  rule?: string;
};

export default async function NotificationLogPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const { count, entries } = await fetchNotificationLog({
    status: params.status,
    channel: params.channel,
    rule: params.rule,
    limit: 300,
  });

  return (
    <>
      <AutoRefresh intervalMs={5000} />

      <div className="mb-4">
        <Link
          href="/notifications"
          className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft size={12} /> back to notifications
        </Link>
      </div>

      <PageHeader
        title="Notification log"
        subtitle={`${count} entries`}
      />

      <form
        action="/notifications/log"
        method="GET"
        className="mb-4 flex flex-wrap items-center gap-2"
      >
        <NativeSelect name="status" defaultValue={params.status ?? ""}>
          <option value="">any status</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </NativeSelect>
        <Input
          name="channel"
          defaultValue={params.channel ?? ""}
          placeholder="channel name"
          className="w-44"
        />
        <Input
          name="rule"
          defaultValue={params.rule ?? ""}
          placeholder="rule name"
          className="w-44"
        />
        <Button type="submit" variant="primary" size="sm">
          Filter
        </Button>
        <Link href="/notifications/log" className="ml-1 text-xs text-fg-muted hover:text-fg">
          reset
        </Link>
      </form>

      <DataPanel className="overflow-hidden">
        {entries.length === 0 ? (
          <div className="px-6 py-12 text-center text-sm text-fg-muted">
            No log entries match the filter.
          </div>
        ) : (
          <LogTable entries={entries} />
        )}
      </DataPanel>
    </>
  );
}

function LogTable({ entries }: { entries: NotificationLogEntry[] }) {
  return (
    <table className="w-full table-fixed text-sm">
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-36 px-4 py-2 text-left font-normal">Time</th>
          <th className="w-28 px-4 py-2 text-left font-normal">Status</th>
          <th className="w-32 px-4 py-2 text-left font-normal">Channel</th>
          <th className="w-40 px-4 py-2 text-left font-normal">Rule</th>
          <th className="w-56 px-4 py-2 text-left font-normal">Event</th>
          <th className="w-16 px-4 py-2 text-right font-normal">Retries</th>
          <th className="px-4 py-2 text-left font-normal">Preview / error</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e) => (
          <tr
            key={String(e.id)}
            className="border-b border-line-soft last:border-0 hover:bg-surface-2"
          >
            <td className="px-4 py-2">
              <TimestampCell value={e.ts} />
            </td>
            <td className="px-4 py-2">
              <StatusPill status={e.status} />
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
                {e.event_severity && (
                  <SeverityBadge severity={e.event_severity} />
                )}
              </div>
            </td>
            <td className="px-4 py-2 text-right font-mono text-xs text-fg-muted">
              {e.retries_used}
            </td>
            <td className="truncate px-4 py-2 font-mono text-[11px] text-fg-subtle">
              {e.error_message ?? e.body_preview ?? ""}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function StatusPill({ status }: { status: string }) {
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
