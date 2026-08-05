import Link from "next/link";
import clsx from "clsx";

import { fetchPostureFindings } from "@/lib/api";
import type { PostureFinding } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { TimestampCell } from "@/components/domain/TimestampCell";
import {
  SeverityBadge,
  severityBorderBg,
} from "@/components/domain/SeverityBadge";
import { SeverityCounterGrid } from "@/components/domain/SeverityCounterGrid";
import { EmptyState as SharedEmptyState } from "@/components/ui/EmptyState";

export default async function AwsPosturePage() {
  const { count, findings, have_connector } = await fetchPostureFindings();

  const counts = tallySeverities(findings);
  const grouped = groupByResourceType(findings);

  return (
    <>
      <AutoRefresh intervalMs={30_000} />
      <PageHeader
        title="AWS posture"
        subtitle={`${count} open finding${count === 1 ? "" : "s"} · drift-detected, current state`}
      />

      <SeverityCounterGrid counts={counts} />

      {grouped.length === 0 ? (
        <EmptyState haveConnector={have_connector} />
      ) : (
        <div className="mt-6 space-y-6">
          {grouped.map(([resourceType, group]) => (
            <ResourceTypePanel
              key={resourceType}
              resourceType={resourceType}
              findings={group}
            />
          ))}
        </div>
      )}
    </>
  );
}

// --- panels ---------------------------------------------------------------

function ResourceTypePanel({
  resourceType,
  findings,
}: {
  resourceType: string;
  findings: PostureFinding[];
}) {
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between">
        <SectionLabel>{resourceType.replaceAll("_", " ")}</SectionLabel>
        <span className="font-mono text-[11px] text-fg-subtle">
          {findings.length} finding{findings.length === 1 ? "" : "s"}
        </span>
      </div>
      <DataPanel className="overflow-hidden">
        <Table>
          <thead>
            <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="w-24 px-4 py-2 text-left font-normal">Severity</th>
              <th className="w-72 px-4 py-2 text-left font-normal">Resource</th>
              <th className="px-4 py-2 text-left font-normal">Finding</th>
              <th className="w-24 px-4 py-2 text-left font-normal">Region</th>
              <th className="w-40 px-4 py-2 text-left font-normal">Last seen</th>
            </tr>
          </thead>
          <tbody>
            {findings.map((f) => (
              <FindingRow key={f.finding_id} finding={f} />
            ))}
          </tbody>
        </Table>
      </DataPanel>
    </section>
  );
}

function FindingRow({ finding }: { finding: PostureFinding }) {
  return (
    <tr className="group relative border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="relative px-4 py-2.5">
        <span
          aria-hidden
          className={clsx(
            "pointer-events-none absolute left-0 top-0 h-full w-0.5",
            severityBorderBg(finding.severity),
          )}
        />
        <SeverityBadge severity={finding.severity} />
      </td>
      <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
        {finding.resource_id}
      </td>
      <td className="truncate px-4 py-2.5">
        <Link
          href={`/aws-posture/${finding.finding_id}`}
          className="font-mono text-xs text-fg transition-colors hover:text-signal"
        >
          {finding.finding_type}
        </Link>
      </td>
      <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">
        {finding.region ?? "—"}
      </td>
      <td className="px-4 py-2.5">
        <TimestampCell value={finding.last_seen} />
      </td>
    </tr>
  );
}

// --- empty state ----------------------------------------------------------

function EmptyState({ haveConnector }: { haveConnector: boolean }) {
  return (
    <DataPanel className="mt-6">
      <SharedEmptyState size="lg">
        {haveConnector ? (
          <>
            No open findings. Either nothing&apos;s wrong, or the connector
            hasn&apos;t run yet — try <em className="not-italic text-fg">Run now</em> on
            the connector in Settings.
          </>
        ) : (
          <>
            No findings yet. Set up an <strong className="text-fg">AWS posture
            drift connector</strong> in <Link
              href="/settings"
              className="text-signal hover:underline"
            >Settings</Link> to start scanning.
          </>
        )}
      </SharedEmptyState>
    </DataPanel>
  );
}

// --- helpers --------------------------------------------------------------

function tallySeverities(findings: PostureFinding[]) {
  const c = { critical: 0, high: 0, medium: 0, lowAndInfo: 0 };
  for (const f of findings) {
    switch (f.severity) {
      case "critical":
        c.critical++;
        break;
      case "high":
        c.high++;
        break;
      case "medium":
        c.medium++;
        break;
      case "low":
      case "informational":
        c.lowAndInfo++;
        break;
    }
  }
  return c;
}

function groupByResourceType(
  findings: PostureFinding[],
): Array<[string, PostureFinding[]]> {
  const map = new Map<string, PostureFinding[]>();
  for (const f of findings) {
    const list = map.get(f.resource_type) ?? [];
    list.push(f);
    map.set(f.resource_type, list);
  }
  // Sort resource types by "hotness" (critical+high count desc), matching
  // the existing /ui/aws-posture behavior.
  return [...map.entries()].sort(([, a], [, b]) => {
    const hotA = a.filter((f) => f.severity === "critical" || f.severity === "high").length;
    const hotB = b.filter((f) => f.severity === "critical" || f.severity === "high").length;
    return hotB - hotA;
  });
}
