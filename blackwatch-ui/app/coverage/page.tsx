import Link from "next/link";

import { fetchCoverage } from "@/lib/api";
import type { CoverageRow, CoverageStatus } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { StatusPill } from "@/components/ui/StatusPill";
import { TimestampCell } from "@/components/domain/TimestampCell";

export default async function CoveragePage() {
  const data = await fetchCoverage();

  return (
    <>
      <PageHeader
        title="Coverage"
        subtitle={`Collector health · freshness measured from the last connector run`}
      />

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Metric label="Total" value={data.summary.total} />
        <Metric label="Healthy" value={data.summary.healthy} tone="ok" />
        <Metric label="Needs attention" value={data.summary.attention} tone="warn" />
        <Metric label="Disabled" value={data.summary.disabled} />
        <Metric label="Stale" value={data.summary.stale} tone="warn" />
      </div>

      <DataPanel className="mb-4 overflow-hidden">
        {data.coverage.length === 0 ? (
          <div className="px-6 py-12 text-center text-sm text-fg-muted">
            No collectors configured. <Link href="/connectors/new" className="text-signal hover:underline">Add a connector →</Link>
          </div>
        ) : (
          <CoverageTable rows={data.coverage} />
        )}
      </DataPanel>

      <p className="max-w-3xl text-xs leading-5 text-fg-subtle">
        {data.zero_event_semantics} See <Link href="/connectors" className="text-signal hover:underline">connectors</Link> for tests and run controls.
      </p>
    </>
  );
}

function Metric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number;
  tone?: "neutral" | "ok" | "warn";
}) {
  return (
    <div className="border border-line-soft bg-surface-1 px-4 py-3">
      <div className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">{label}</div>
      <div className={tone === "ok" ? "mt-1 text-xl text-sev-resolved" : tone === "warn" ? "mt-1 text-xl text-sev-high" : "mt-1 text-xl text-fg"}>{value}</div>
    </div>
  );
}

function CoverageTable({ rows }: { rows: CoverageRow[] }) {
  return (
    <Table tableId="coverage-list">
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="px-4 py-2 text-left font-normal">Source</th>
          <th className="px-4 py-2 text-left font-normal">Module</th>
          <th className="px-4 py-2 text-left font-normal">Connector</th>
          <th className="px-4 py-2 text-left font-normal">Last seen</th>
          <th className="px-4 py-2 text-left font-normal">Verification</th>
          <th className="px-4 py-2 text-left font-normal">State</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <CoverageTableRow key={row.connector_id} row={row} />
        ))}
      </tbody>
    </Table>
  );
}

function CoverageTableRow({ row }: { row: CoverageRow }) {
  return (
    <tr className="border-b border-line-soft hover:bg-surface-2">
      <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">{row.source}</td>
      <td className="px-4 py-2.5">
        <Link href={row.module_href} className="text-sm text-signal hover:underline">{row.module}</Link>
      </td>
      <td className="px-4 py-2.5 text-sm text-fg">{row.connector_name}</td>
      <td className="px-4 py-2.5">
        {row.last_seen_event ? <TimestampCell value={row.last_seen_event} /> : <span className="font-mono text-xs text-fg-disabled">never</span>}
      </td>
      <td className="px-4 py-2.5">
        <StatusPill severity={row.verified ? "resolved" : "neutral"} label={row.verified ? "verified" : "not tested"} />
      </td>
      <td className="px-4 py-2.5">
        <StatusPill severity={statusSeverity(row.status)} label={row.status} title={row.reason} />
      </td>
    </tr>
  );
}

function statusSeverity(status: CoverageStatus): "critical" | "high" | "resolved" | "neutral" {
  if (status === "failing") return "critical";
  if (status === "stale" || status === "unverified") return "high";
  if (status === "healthy") return "resolved";
  return "neutral";
}
