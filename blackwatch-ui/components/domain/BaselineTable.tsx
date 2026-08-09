import { Table, TableEmpty } from "@/components/ui/Table";

export interface BaselineRow {
  principal_type: string;
  principal_id: string;
  dimension: string;
  value: string;
  first_seen: number;
  last_seen: number;
  count: number;
}

function fmtEpoch(ts: number): string {
  if (!ts) return "";
  try {
    return new Date(ts * 1000).toISOString().replace("T", " ").slice(0, 19) + "Z";
  } catch {
    return String(ts);
  }
}

export function BaselineTable({ rows }: { rows: BaselineRow[] }) {
  return (
    <Table tableId="ueba-baselines">
      <thead>
        <tr>
          <th style={{ width: 130 }}>Type</th>
          <th style={{ width: 220 }}>Principal</th>
          <th style={{ width: 150 }}>Dimension</th>
          <th style={{ width: 220 }}>Value</th>
          <th data-align="right" style={{ width: 90 }}>Count</th>
          <th style={{ width: 180 }}>First seen</th>
          <th style={{ width: 180 }}>Last seen</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <TableEmpty columns={7}>No baseline rows.</TableEmpty>
        ) : (
          rows.map((r) => (
            <tr
              key={`${r.principal_type}|${r.principal_id}|${r.dimension}|${r.value}`}
            >
              <td className="font-mono text-xs">{r.principal_type}</td>
              <td>{r.principal_id}</td>
              <td className="font-mono text-xs">{r.dimension}</td>
              <td className="font-mono text-xs">{r.value}</td>
              <td data-align="right">{r.count}</td>
              <td className="font-mono text-xs">{fmtEpoch(r.first_seen)}</td>
              <td className="font-mono text-xs">{fmtEpoch(r.last_seen)}</td>
            </tr>
          ))
        )}
      </tbody>
    </Table>
  );
}
