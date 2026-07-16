import Link from "next/link";

import { fetchNotificationLog } from "@/lib/api";
import type { NotificationLogEntry } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { BackLink } from "@/components/ui/BackLink";
import { StatusDot, type Severity } from "@/components/ui/StatusDot";
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

      <BackLink href="/notifications" label="back to notifications" />

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
    <Table>
      <thead>
        <tr>
          <th style={{ width: 144 }}>Time</th>
          <th style={{ width: 112 }}>Status</th>
          <th style={{ width: 128 }}>Channel</th>
          <th style={{ width: 160 }}>Rule</th>
          <th style={{ width: 224 }}>Event</th>
          <th data-align="right" style={{ width: 64 }}>Retries</th>
          <th>Preview / error</th>
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
    </Table>
  );
}

function StatusPill({ status }: { status: string }) {
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
