import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { fetchPostureFinding } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { SeverityBadge } from "@/components/domain/SeverityBadge";

export default async function PostureFindingDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const finding = await fetchPostureFinding(id);
  if (!finding) notFound();

  const evidenceJson = JSON.stringify(finding.evidence ?? {}, null, 2);
  const evidenceEntries = Object.entries(finding.evidence ?? {});

  return (
    <>
      <div className="mb-4">
        <Link
          href="/aws-posture"
          className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft size={12} /> back to posture
        </Link>
      </div>

      <PageHeader
        title={finding.finding_type}
        subtitle={finding.resource_id}
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetaCell label="severity">
          <SeverityBadge severity={finding.severity} />
        </MetaCell>
        <MetaCell label="resource type">
          <span className="font-mono text-xs text-fg">
            {finding.resource_type}
          </span>
        </MetaCell>
        <MetaCell label="region">
          <span className="font-mono text-xs text-fg">
            {finding.region ?? "—"}
          </span>
        </MetaCell>
        <MetaCell label="account">
          <span className="font-mono text-xs text-fg">
            {finding.account ?? "—"}
          </span>
        </MetaCell>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4">
        <MetaCell label="first seen">
          <TimestampCell value={finding.first_seen} />
        </MetaCell>
        <MetaCell label="last seen">
          <TimestampCell value={finding.last_seen} />
        </MetaCell>
      </div>

      {evidenceEntries.length > 0 && (
        <div className="mt-6 space-y-2">
          <SectionLabel>evidence</SectionLabel>
          <DataPanel>
            <dl className="divide-y divide-line-soft">
              {evidenceEntries.map(([key, value]) => (
                <div key={key} className="grid grid-cols-3 gap-4 px-4 py-2.5">
                  <dt className="font-mono text-xs text-fg-muted">{key}</dt>
                  <dd className="col-span-2 break-all font-mono text-xs text-fg">
                    {formatEvidenceValue(value)}
                  </dd>
                </div>
              ))}
            </dl>
          </DataPanel>
        </div>
      )}

      <div className="mt-6 space-y-2">
        <SectionLabel>evidence (raw)</SectionLabel>
        <DataPanel className="overflow-auto p-4">
          <pre className="text-xs leading-relaxed text-fg-muted">
            {evidenceJson}
          </pre>
        </DataPanel>
      </div>
    </>
  );
}

function MetaCell({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <DataPanel className="p-4">
      <SectionLabel>{label}</SectionLabel>
      <div className="mt-2">{children}</div>
    </DataPanel>
  );
}

function formatEvidenceValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}
