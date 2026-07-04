import Link from "next/link";
import clsx from "clsx";

import { fetchBuckets } from "@/lib/api";
import type {
  BucketStatus,
  BlockPublicAccess,
} from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { StatusDot } from "@/components/ui/StatusDot";

export default async function BucketsPage() {
  const { count, buckets, counts } = await fetchBuckets();

  return (
    <>
      <PageHeader
        title="S3 buckets"
        subtitle={`${count} bucket${count === 1 ? "" : "s"} tracked · inventory snapshot`}
      />

      <CountersGrid counts={counts} />

      <section className="mt-6 space-y-2">
        <SectionLabel>all buckets</SectionLabel>
        <DataPanel className="overflow-hidden">
          {buckets.length === 0 ? (
            <EmptyState />
          ) : (
            <BucketsTable buckets={buckets} />
          )}
        </DataPanel>
      </section>
    </>
  );
}

// --- counters ------------------------------------------------------------

function CountersGrid({
  counts,
}: {
  counts: { total: number; public: number; unencrypted: number; no_versioning: number };
}) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <CountCell label="Total" count={counts.total} tone="neutral" />
      <CountCell label="Public" count={counts.public} tone={counts.public > 0 ? "bad" : "ok"} />
      <CountCell
        label="Unencrypted"
        count={counts.unencrypted}
        tone={counts.unencrypted > 0 ? "warn" : "ok"}
      />
      <CountCell
        label="No versioning"
        count={counts.no_versioning}
        tone={counts.no_versioning > 0 ? "warn" : "ok"}
      />
    </div>
  );
}

function CountCell({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone: "ok" | "warn" | "bad" | "neutral";
}) {
  const dotSeverity =
    tone === "ok"
      ? "resolved"
      : tone === "warn"
        ? "medium"
        : tone === "bad"
          ? "critical"
          : "neutral";
  const textColor =
    tone === "neutral" || count === 0
      ? "text-fg"
      : tone === "bad"
        ? "text-sev-critical"
        : tone === "warn"
          ? "text-sev-medium"
          : "text-fg";
  return (
    <div className="border border-line-soft bg-surface-1 px-4 py-3">
      <div className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
        {label}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        {tone !== "neutral" && (
          <StatusDot severity={dotSeverity} className="translate-y-[-3px]" />
        )}
        <span className={clsx("font-mono text-3xl tabular-nums", textColor)}>
          {count}
        </span>
      </div>
    </div>
  );
}

// --- table ---------------------------------------------------------------

function BucketsTable({ buckets }: { buckets: BucketStatus[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="px-4 py-2 text-left font-normal">Bucket</th>
          <th className="w-24 px-4 py-2 text-left font-normal">Region</th>
          <th className="w-28 px-4 py-2 text-left font-normal">Public</th>
          <th className="w-36 px-4 py-2 text-left font-normal">Encryption</th>
          <th className="w-36 px-4 py-2 text-left font-normal">Versioning</th>
          <th className="w-44 px-4 py-2 text-left font-normal">BPA</th>
          <th className="w-32 px-4 py-2 text-left font-normal">Logging</th>
          <th className="w-32 px-4 py-2 text-left font-normal">Last scan</th>
        </tr>
      </thead>
      <tbody>
        {buckets.map((b) => (
          <BucketRow key={b.bucket_name + ":" + (b.region ?? "")} bucket={b} />
        ))}
      </tbody>
    </Table>
  );
}

function BucketRow({ bucket: b }: { bucket: BucketStatus }) {
  return (
    <tr
      className={clsx(
        "group relative border-b border-line-soft last:border-0 hover:bg-surface-2",
      )}
    >
      <td className="relative px-4 py-2.5">
        {b.public && (
          <span
            aria-hidden
            className="pointer-events-none absolute left-0 top-0 h-full w-0.5 bg-sev-critical"
          />
        )}
        <div className="font-mono text-xs text-fg">{b.bucket_name}</div>
        {b.tags && Object.keys(b.tags).length > 0 && (
          <div className="mt-1 flex flex-wrap gap-x-2 font-mono text-[10px] text-fg-subtle">
            {Object.entries(b.tags).map(([k, v]) => (
              <code key={k}>
                {k}={v}
              </code>
            ))}
          </div>
        )}
      </td>
      <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">
        {b.region ?? "—"}
      </td>
      <td className="px-4 py-2.5">
        <PublicCell isPublic={b.public} reasons={b.public_reasons} />
      </td>
      <td className="px-4 py-2.5">
        {b.encryption === "none" ? (
          <span className="inline-flex items-center gap-1.5 text-xs">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-sev-critical" />
            <span className="text-sev-critical">none</span>
          </span>
        ) : (
          <code className="font-mono text-xs text-fg-muted">{b.encryption}</code>
        )}
      </td>
      <td className="px-4 py-2.5">
        <VersioningCell versioning={b.versioning} mfaDelete={b.mfa_delete} />
      </td>
      <td className="px-4 py-2.5">
        <BpaCell bpa={b.block_public_access} />
      </td>
      <td className="px-4 py-2.5">
        {b.logging_target ? (
          <span className="inline-flex items-center gap-1.5 text-xs">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-sev-resolved" />
            <code className="font-mono text-xs text-fg-muted">{b.logging_target}</code>
          </span>
        ) : (
          <span className="text-xs text-fg-subtle">off</span>
        )}
      </td>
      <td className="px-4 py-2.5">
        {b.last_scan ? (
          <TimestampCell value={b.last_scan} />
        ) : (
          <span className="text-fg-disabled">—</span>
        )}
      </td>
    </tr>
  );
}

// --- cells ---------------------------------------------------------------

function PublicCell({
  isPublic,
  reasons,
}: {
  isPublic: boolean;
  reasons: string[] | null;
}) {
  if (!isPublic) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-sev-resolved" />
        <span className="text-fg-muted">private</span>
      </span>
    );
  }
  return (
    <div className="space-y-1">
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-sev-critical" />
        <span className="font-medium text-sev-critical">PUBLIC</span>
      </span>
      {reasons && reasons.length > 0 && (
        <div className="text-[11px] text-fg-subtle">{reasons.join(", ")}</div>
      )}
    </div>
  );
}

function VersioningCell({
  versioning,
  mfaDelete,
}: {
  versioning: string | null;
  mfaDelete: boolean | null;
}) {
  if (versioning === "Enabled") {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-sev-resolved" />
        <span className="text-fg-muted">
          Enabled
          {mfaDelete && (
            <span className="ml-1 text-fg-subtle">· MFA</span>
          )}
        </span>
      </span>
    );
  }
  if (versioning === "Suspended") {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-sev-medium" />
        <span className="text-sev-medium">Suspended</span>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-fg-subtle" />
      <span className="text-fg-subtle">Disabled</span>
    </span>
  );
}

function BpaCell({ bpa }: { bpa: BlockPublicAccess | null }) {
  if (!bpa) {
    return <span className="text-xs text-fg-subtle">not configured</span>;
  }
  const allOn =
    bpa.block_public_acls &&
    bpa.ignore_public_acls &&
    bpa.block_public_policy &&
    bpa.restrict_public_buckets;
  if (allOn) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-sev-resolved" />
        <span className="text-fg-muted">all on</span>
      </span>
    );
  }
  return (
    <div className="space-y-1">
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-sev-medium" />
        <span className="text-sev-medium">partial</span>
      </span>
      <div className="font-mono text-[10px] text-fg-subtle">
        acls={String(bpa.block_public_acls)} · ig={String(bpa.ignore_public_acls)} · pol={String(bpa.block_public_policy)} · rs={String(bpa.restrict_public_buckets)}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="px-6 py-12 text-center text-sm text-fg-muted">
      <p>
        No buckets tracked yet. Either run the bootstrap script
        (<code className="text-fg">scripts/s3_bucket_inventory.py</code>) to seed
        the inventory once, or set up an{" "}
        <strong className="text-fg">S3 drift connector</strong> in{" "}
        <Link href="/settings" className="text-signal hover:underline">
          Settings
        </Link>{" "}
        for ongoing scans.
      </p>
    </div>
  );
}
