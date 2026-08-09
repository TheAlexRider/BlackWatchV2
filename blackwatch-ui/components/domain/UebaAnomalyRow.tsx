import Link from "next/link";
import { TimestampCell } from "./TimestampCell";
import type { EventEnvelope } from "@/lib/types";

export interface UebaAnomalyRowProps {
  event: EventEnvelope;
}

export function UebaAnomalyRow({ event }: UebaAnomalyRowProps) {
  const extra = (event as { extra?: Record<string, unknown> }).extra ?? {};
  const dimension = String(extra.dimension ?? "");
  const value = String(extra.baseline_value ?? "");
  const principalId = String(extra.principal_id ?? event.actor?.principal ?? "");
  const principalType = String(extra.principal_type ?? event.actor?.type ?? "");
  const triggerId = String(extra.trigger_event_id ?? "");
  return (
    <tr>
      <td>
        <TimestampCell value={event.event_time} />
      </td>
      <td className="font-mono text-xs">{event.action}</td>
      <td>
        <span className="text-fg">{principalId}</span>
        {principalType && (
          <span className="ml-1 text-fg-muted">({principalType})</span>
        )}
      </td>
      <td className="font-mono text-xs">{dimension}</td>
      <td className="font-mono text-xs">{value}</td>
      <td>
        {triggerId ? (
          <Link
            href={`/events/${encodeURIComponent(triggerId)}`}
            className="text-signal underline-offset-2 hover:underline"
          >
            trigger
          </Link>
        ) : null}
      </td>
    </tr>
  );
}
