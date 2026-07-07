import Link from "next/link";
import clsx from "clsx";

import { fetchEvents } from "@/lib/api";
import { SEVERITY_VALUES, type EventEnvelope } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { TimestampCell } from "@/components/domain/TimestampCell";
import {
  SeverityBadge,
  severityBorderBg,
} from "@/components/domain/SeverityBadge";

type SearchParams = {
  q?: string;
  severity?: string;
  category?: string;
  module?: string;
  action?: string;
};

export default async function EventsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const { count, events } = await fetchEvents({
    q: params.q,
    severity: params.severity,
    category: params.category,
    module: params.module,
    action: params.action,
  });

  return (
    <>
      <AutoRefresh intervalMs={5000} />
      <PageHeader
        title="Events"
        subtitle={`Showing ${count} event${count === 1 ? "" : "s"}.`}
      />

      <FilterBar params={params} />

      <DataPanel className="mt-4 overflow-hidden">
        {events.length === 0 ? (
          <EmptyState />
        ) : (
          <EventsTable events={events} />
        )}
      </DataPanel>
    </>
  );
}

function FilterBar({ params }: { params: SearchParams }) {
  return (
    <form
      action="/events"
      method="GET"
      className="flex flex-wrap items-center gap-2"
    >
      <Input
        name="q"
        aria-label="Search events"
        autoComplete="off"
        defaultValue={params.q ?? ""}
        placeholder="search…"
        className="w-48"
      />
      <NativeSelect name="severity" aria-label="Severity" defaultValue={params.severity ?? ""}>
        <option value="">any severity</option>
        {SEVERITY_VALUES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </NativeSelect>
      <Input
        name="category"
        aria-label="Category"
        autoComplete="off"
        defaultValue={params.category ?? ""}
        placeholder="category…"
        className="w-32"
      />
      <Input
        name="module"
        aria-label="Module"
        autoComplete="off"
        defaultValue={params.module ?? ""}
        placeholder="module…"
        className="w-32"
      />
      <Input
        name="action"
        aria-label="Action"
        autoComplete="off"
        defaultValue={params.action ?? ""}
        placeholder="action…"
        className="w-32"
      />
      <Button type="submit" variant="primary" size="sm">
        Filter
      </Button>
      <Link
        href="/events"
        className="ml-1 text-xs text-fg-muted hover:text-fg"
      >
        reset
      </Link>
    </form>
  );
}

function EventsTable({ events }: { events: EventEnvelope[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-44 px-4 py-2 text-left font-normal">Time</th>
          <th className="w-28 px-4 py-2 text-left font-normal">Severity</th>
          <th className="w-32 px-4 py-2 text-left font-normal">Module</th>
          <th className="px-4 py-2 text-left font-normal">Action</th>
          <th className="w-48 px-4 py-2 text-left font-normal">Actor</th>
          <th className="w-64 px-4 py-2 text-left font-normal">Target</th>
        </tr>
      </thead>
      <tbody>
        {events.map((ev) => (
          <EventRow key={ev.event_id} event={ev} />
        ))}
      </tbody>
    </Table>
  );
}

function EventRow({ event }: { event: EventEnvelope }) {
  const severity = (event.severity as string | null | undefined) ?? null;
  const actor = event.actor?.principal ?? "—";
  // Prefer the role tag (set per-agent via BLACKWATCH_TAGS) so the column shows
  // "Dev-NAT" instead of "i-08ba075...". Falls back to hostname, then instance id.
  const extra = (event.extra as Record<string, unknown> | undefined) ?? {};
  const tags = extra.tags as Record<string, string> | undefined;
  const target =
    tags?.role ?? event.target?.name ?? event.target?.id ?? "—";
  const moduleName = event.source?.module ?? "—";

  return (
    <tr className="group relative border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td data-label="Time" className="relative px-4 py-2.5">
        {/* 2px severity left-border indicator — never a background fill */}
        <span
          aria-hidden
          className={clsx(
            "pointer-events-none absolute left-0 top-0 h-full w-0.5",
            severityBorderBg(severity),
          )}
        />
        <TimestampCell value={event.event_time} />
      </td>
      <td data-label="Severity" className="px-4 py-2.5">
        <SeverityBadge severity={severity} />
      </td>
      <td data-label="Module" className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
        {moduleName}
      </td>
      <td data-label="Action" className="truncate px-4 py-2.5">
        <Link
          href={`/events/${event.event_id}`}
          className="font-mono text-xs text-fg transition-colors hover:text-signal"
        >
          {event.action}
        </Link>
      </td>
      <td data-label="Actor" className="truncate px-4 py-2.5 text-xs text-fg-muted">{actor}</td>
      <td data-label="Target" className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
        {target}
      </td>
    </tr>
  );
}

function EmptyState() {
  return (
    <div className="px-6 py-16 text-center text-sm text-fg-muted">
      No events match the current filters.
    </div>
  );
}
