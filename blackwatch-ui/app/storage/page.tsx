import Link from "next/link";

import { fetchStorageSummary } from "@/lib/api";
import type { StorageGroup } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { Table } from "@/components/ui/Table";
import { EmptyState } from "@/components/ui/EmptyState";
import { StorageGroupCard } from "@/components/domain/StorageGroupCard";
import { StorageEventRow } from "@/components/domain/StorageEventRow";

// Sub-domain -> display label + optional deep link. Each group folds together
// the events whose action prefix matches (see _STORAGE_GROUPS on the backend).
const GROUP_META: Array<{ group: StorageGroup; label: string; href?: string }> = [
  { group: "s3",      label: "S3 buckets",       href: "/buckets" },
  { group: "ebs",     label: "EBS + AMI" },
  { group: "rds",     label: "RDS",              href: "/rds" },
  { group: "efs",     label: "EFS" },
  { group: "backup",  label: "AWS Backup" },
  { group: "secrets", label: "Secrets Manager" },
];

export default async function StoragePage() {
  const summary = await fetchStorageSummary(24);

  return (
    <>
      <PageHeader
        title="Storage"
        subtitle={`${summary.buckets.total} buckets tracked · ${summary.buckets.public} public · last ${summary.hours}h event activity`}
      />

      <section className="space-y-2">
        <SectionLabel>activity by domain</SectionLabel>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
          {GROUP_META.map((meta) => (
            <StorageGroupCard
              key={meta.group}
              group={meta.group}
              label={meta.label}
              counts={summary.groups[meta.group]}
              hours={summary.hours}
              href={meta.href}
            />
          ))}
        </div>
      </section>

      <section className="mt-6 space-y-2">
        <SectionLabel>recent critical events</SectionLabel>
        <DataPanel className="overflow-hidden">
          {summary.recent_critical.length === 0 ? (
            <EmptyState>
              <p>
                No critical storage events in the last {summary.hours} hours. When
                one fires — a snapshot shared cross-account, a bucket policy
                widened, a backup vault deleted, an EFS mount target opened — it
                appears here with a link straight to the event detail.
              </p>
              <p className="mt-2 text-fg-subtle">
                Browse all storage-category events on the{" "}
                <Link href="/events?category=storage" className="text-signal hover:underline">
                  events page
                </Link>
                .
              </p>
            </EmptyState>
          ) : (
            <Table>
              <thead>
                <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
                  <th className="px-4 py-2 text-left font-normal">Event</th>
                  <th className="px-4 py-2 text-left font-normal">Domain</th>
                  <th className="px-4 py-2 text-left font-normal">Target</th>
                  <th className="px-4 py-2 text-left font-normal">Principal</th>
                  <th className="px-4 py-2 text-left font-normal">When</th>
                  <th className="px-4 py-2 text-right font-normal"></th>
                </tr>
              </thead>
              <tbody>
                {summary.recent_critical.map((event) => (
                  <StorageEventRow key={event.event_id ?? event.action + event.event_time} event={event} />
                ))}
              </tbody>
            </Table>
          )}
        </DataPanel>
      </section>
    </>
  );
}
