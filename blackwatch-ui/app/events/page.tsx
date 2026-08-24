import Link from "next/link";
import clsx from "clsx";

import { fetchEventFilterOptions, fetchEvents } from "@/lib/api";
import { SEVERITY_VALUES, type EventEnvelope } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { EmptyState } from "@/components/ui/EmptyState";
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
  const [{ count, events }, options] = await Promise.all([
    fetchEvents({
      q: params.q,
      severity: params.severity,
      category: params.category,
      module: params.module,
      action: params.action,
    }),
    fetchEventFilterOptions(),
  ]);

  return (
    <>
      <AutoRefresh intervalMs={5000} />
      <PageHeader
        title="Events"
        subtitle={`Showing ${count} event${count === 1 ? "" : "s"}.`}
      />

      <FilterBar params={params} options={options} />

      <DataPanel className="mt-4 overflow-hidden">
        {events.length === 0 ? (
          <EmptyState size="lg">No events match the current filters.</EmptyState>
        ) : (
          <EventsTable events={events} />
        )}
      </DataPanel>
    </>
  );
}

function FilterBar({
  params,
  options,
}: {
  params: SearchParams;
  options: {
    categories: string[];
    modules: string[];
    actions: string[];
    severities: string[];
  };
}) {
  return (
    <form
      action="/events"
      method="GET"
    className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-[minmax(16rem,2fr)_repeat(4,minmax(10rem,1fr))_auto_auto]"
  >
      <Input
        name="q"
        aria-label="Search events"
        autoComplete="off"
        defaultValue={params.q ?? ""}
        placeholder="search…"
        className="w-full"
      />
      <NativeSelect name="severity" aria-label="Severity" defaultValue={params.severity ?? ""} className="w-full">
        <option value="">All severities</option>
        {(options.severities.length ? options.severities : SEVERITY_VALUES).map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </NativeSelect>
      <NativeSelect name="category" aria-label="Category" defaultValue={params.category ?? ""} className="w-full">
        <option value="">All categories</option>
        {options.categories.map((value) => <option key={value} value={value}>{value}</option>)}
      </NativeSelect>
      <NativeSelect name="module" aria-label="Source module" defaultValue={params.module ?? ""} className="w-full">
        <option value="">All source modules</option>
        {options.modules.map((value) => <option key={value} value={value}>{value}</option>)}
      </NativeSelect>
      <NativeSelect name="action" aria-label="Action" defaultValue={params.action ?? ""} className="w-full">
        <option value="">All actions</option>
        {options.actions.map((value) => <option key={value} value={value}>{value}</option>)}
      </NativeSelect>
      <Button type="submit" variant="primary" size="sm" className="w-1/2 justify-self-start">
        Apply filters
      </Button>
      <Button asChild variant="secondary" size="sm" className="w-1/2 justify-self-start">
        <Link href="/events">Clear</Link>
      </Button>
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
          <th className="w-52 px-4 py-2 text-left font-normal">Tags</th>
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
  const tags =
    (event.tags as Record<string, string> | undefined) ??
    (extra.tags as Record<string, string> | undefined);
  const target =
    tags?.role ?? event.target?.name ?? event.target?.id ?? "—";
  const moduleName = event.source?.module ?? "—";
  const tagEntries = Object.entries(tags ?? {});

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
      <td data-label="Tags" className="px-4 py-2.5">
        {tagEntries.length === 0 ? (
          <span className="text-xs text-fg-disabled">—</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {tagEntries.map(([key, value]) => (
              <span
                key={key}
                className="inline-flex max-w-full rounded border border-line-soft bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-muted"
                title={`${key}: ${value}`}
              >
                {key}={value}
              </span>
            ))}
          </div>
        )}
      </td>
    </tr>
  );
}
