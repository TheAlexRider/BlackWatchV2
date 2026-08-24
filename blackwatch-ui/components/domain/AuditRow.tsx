// One row of the /audit table. Presentational only.

import { IpCell } from "@/components/domain/IpCell";
import { TimestampCell } from "@/components/domain/TimestampCell";

export interface AuditEntry {
  id: number;
  ts: string;
  actor: string | null;
  actor_role: string | null;
  ip: string | null;
  method: string;
  path: string;
  status: number;
  body_summary: string | null;
}

export function AuditRow({ row }: { row: AuditEntry }) {
  const statusClass =
    row.status >= 500
      ? "text-red-400"
      : row.status >= 400
        ? "text-amber-400"
        : "text-fg-subtle";
  return (
    <tr className="border-b border-line-soft align-top text-sm">
      <td className="px-3 py-2">
        <TimestampCell value={row.ts} />
      </td>
      <td className="px-2 py-1">{row.actor ?? "-"}</td>
      <td className="px-2 py-1 text-xs text-fg-subtle">{row.actor_role ?? "-"}</td>
      <td className="px-3 py-2 font-mono text-xs"><IpCell value={row.ip} className="text-xs" /></td>
      <td className="px-3 py-2 font-mono text-xs">{row.method}</td>
      <td className="px-3 py-2 font-mono text-xs">{row.path}</td>
      <td className={`px-3 py-2 font-mono text-xs ${statusClass}`}>{row.status}</td>
      <td className="max-w-[36rem] break-words px-3 py-2 font-mono text-xs text-fg-subtle">
        {row.body_summary ?? ""}
      </td>
    </tr>
  );
}
