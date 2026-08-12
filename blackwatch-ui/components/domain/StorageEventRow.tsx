import Link from "next/link";
import type { StorageCriticalEvent, StorageS3SecurityEvent } from "@/lib/types";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { SeverityBadge, severityBorderBg } from "@/components/domain/SeverityBadge";

// One row in the "Recent critical storage events" table. Shows the friendly
// message (fallback: action name) and identifies the actor + target so the
// user can act without opening the event detail.
export function StorageEventRow({
  event,
  showSignal = false,
}: {
  event: StorageCriticalEvent & Partial<StorageS3SecurityEvent>;
  showSignal?: boolean;
}) {
  const sourceIps = event.source_ips ?? (event.source_ip ? [event.source_ip] : []);
  const count = event.count ?? 1;
  return (
    <tr className="group relative border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="relative px-4 py-2.5">
        <span
          aria-hidden
          className={`pointer-events-none absolute left-0 top-0 h-full w-0.5 ${severityBorderBg(event.severity)}`}
        />
        <div className="min-w-0 text-xs text-fg">
          <span className="truncate">{event.message ?? event.action}</span>
        </div>
        {event.message && (
          <div className="mt-0.5 font-mono text-[10px] text-fg-subtle">
            {event.action}
          </div>
        )}
      </td>
      <td className="w-28 px-4 py-2.5">
        <SeverityBadge severity={event.severity} />
      </td>
      {showSignal ? (
        <td className="w-36 px-4 py-2.5 text-xs text-fg-muted">
          <span className="font-medium text-fg">{event.signal ?? event.action}</span>
          <span className="mt-0.5 block text-[10px] text-fg-subtle">
            {count > 1 ? `${count} grouped accesses` : "1 access"}
          </span>
        </td>
      ) : (
        <td className="w-24 px-4 py-2.5 font-mono text-[10px] uppercase text-fg-muted">
          {event.group}
        </td>
      )}
      <td className="w-48 px-4 py-2.5 font-mono text-xs text-fg-muted">
        <div className="max-w-[22rem] break-words" title={event.target_id ?? undefined}>
          {event.target_id ?? "—"}
        </div>
      </td>
      <td className="w-40 px-4 py-2.5 font-mono text-xs text-fg-muted">
        <div className="truncate" title={event.principal ?? undefined}>
          {event.principal ?? (sourceIps.length ? sourceIps.join(", ") : "—")}
        </div>
        {event.reason && (
          <div className="mt-1 max-w-[20rem] font-sans text-[10px] leading-relaxed text-fg-subtle">
            {event.reason}
          </div>
        )}
      </td>
      <td className="w-36 px-4 py-2.5">
        {event.event_time ? (
          <TimestampCell value={event.event_time} />
        ) : (
          <span className="text-fg-disabled">—</span>
        )}
      </td>
      <td className="w-16 px-4 py-2.5 text-right">
        {event.event_id && (
          <Link
            href={`/events/${event.event_id}`}
            className="text-[11px] text-signal hover:underline"
          >
            open
          </Link>
        )}
      </td>
    </tr>
  );
}
