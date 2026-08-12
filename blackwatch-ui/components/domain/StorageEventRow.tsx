import Link from "next/link";
import type { StorageCriticalEvent } from "@/lib/types";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { SeverityBadge, severityBorderBg } from "@/components/domain/SeverityBadge";

// One row in the "Recent critical storage events" table. Shows the friendly
// message (fallback: action name) and identifies the actor + target so the
// user can act without opening the event detail.
export function StorageEventRow({
  event,
  showSignal = false,
}: {
  event: StorageCriticalEvent & { signal?: string };
  showSignal?: boolean;
}) {
  return (
    <tr className="group relative border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="relative px-4 py-2.5">
        <span
          aria-hidden
          className={`pointer-events-none absolute left-0 top-0 h-full w-0.5 ${severityBorderBg(event.severity)}`}
        />
        <div className="flex items-center gap-2 text-xs text-fg">
          <SeverityBadge severity={event.severity} />
          <span>{event.message ?? event.action}</span>
        </div>
        {event.message && (
          <div className="mt-0.5 font-mono text-[10px] text-fg-subtle">
            {event.action}
          </div>
        )}
      </td>
      {showSignal ? (
        <td className="w-36 px-4 py-2.5 text-xs text-fg-muted">
          {event.signal ?? event.action}
        </td>
      ) : (
        <td className="w-24 px-4 py-2.5 font-mono text-[10px] uppercase text-fg-muted">
          {event.group}
        </td>
      )}
      <td className="w-48 px-4 py-2.5 font-mono text-xs text-fg-muted">
        {event.target_id ?? "—"}
      </td>
      <td className="w-40 px-4 py-2.5 font-mono text-xs text-fg-muted">
        <div className="truncate" title={event.principal ?? ""}>
          {event.principal ?? "—"}
        </div>
        {event.source_ip && (
          <div className="text-[10px] text-fg-subtle">{event.source_ip}</div>
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
