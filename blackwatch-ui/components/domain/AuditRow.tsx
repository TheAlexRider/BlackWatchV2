// One row of the /audit table. Presentational only.

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
      <td className="whitespace-nowrap px-2 py-1 font-mono text-xs text-fg-subtle">
        {row.ts}
      </td>
      <td className="px-2 py-1">{row.actor ?? "-"}</td>
      <td className="px-2 py-1 text-xs text-fg-subtle">{row.actor_role ?? "-"}</td>
      <td className="px-2 py-1 font-mono text-xs">{row.ip ?? "-"}</td>
      <td className="px-2 py-1 font-mono text-xs">{row.method}</td>
      <td className="px-2 py-1 font-mono text-xs">{row.path}</td>
      <td className={`px-2 py-1 font-mono text-xs ${statusClass}`}>{row.status}</td>
      <td className="max-w-[36rem] break-words px-2 py-1 font-mono text-xs text-fg-subtle">
        {row.body_summary ?? ""}
      </td>
    </tr>
  );
}
