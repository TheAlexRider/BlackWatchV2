"use client";

import Link from "next/link";
import type { Investigation } from "@/lib/types";
import { Table } from "@/components/ui/Table";
import { TimestampCell } from "@/components/domain/TimestampCell";

export function InvestigationList({ investigations }: { investigations: Investigation[] }) {
  return (
    <Table tableId="investigations-list" ariaLabel="Investigations">
      <thead><tr><th>Investigation</th><th>Observable</th><th>Status</th><th>Priority</th><th>Results</th><th>Updated</th></tr></thead>
      <tbody>
        {investigations.map((item) => (
          <tr key={item.id} className="align-top">
            <th scope="row" className="px-4 py-3 text-left font-normal">
              <Link href={`/investigations/${item.id}`} className="font-medium text-fg hover:text-signal hover:underline">{item.title}</Link>
              <div className="mt-1 break-all font-mono text-[10px] text-fg-subtle">{item.id}</div>
            </th>
            <td className="px-4 py-3 font-mono text-xs text-fg-muted">{item.observables.join(", ") || "—"}</td>
            <td className="px-4 py-3 text-xs">{formatStatus(item.status)}</td>
            <td className="px-4 py-3 text-xs uppercase text-fg-muted">{item.priority}</td>
            <td className="px-4 py-3 font-mono text-xs text-fg-muted">{item.result_count}</td>
            <td className="px-4 py-3"><TimestampCell value={item.updated_at} /></td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

export function formatStatus(status: string): string {
  return status.replaceAll("_", " ");
}
