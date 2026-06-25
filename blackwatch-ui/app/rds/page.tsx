import Link from "next/link";
import clsx from "clsx";

import { fetchRds } from "@/lib/api";
import type { EventEnvelope, RdsCounts, RdsInstance } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { TimestampCell } from "@/components/domain/TimestampCell";

// What each flag means in plain English — used both on the instance cards
// (to label why a DB is flagged) and as the column legend below the events
// table. The set must stay in sync with the rds_* keys the adapter writes
// in blackwatch/modules/aws_cloudtrail.py.
const FLAG_META: Record<
  string,
  { label: string; tone: "critical" | "high" | "medium" | "info"; blurb: string }
> = {
  rds_publicly_accessible: {
    label: "publicly accessible",
    tone: "critical",
    blurb: "DB instance is reachable from the public internet.",
  },
  rds_snapshot_made_public: {
    label: "snapshot shared with all",
    tone: "critical",
    blurb: "A snapshot was shared with restore-permission=all (data-exfil path).",
  },
  rds_backups_disabled: {
    label: "backups disabled",
    tone: "high",
    blurb: "BackupRetentionPeriod=0 — no automated point-in-time recovery.",
  },
  rds_unencrypted_at_creation: {
    label: "no storage encryption",
    tone: "high",
    blurb: "StorageEncrypted=false. Can only be fixed by restore-from-snapshot.",
  },
  rds_deletion_protection_off: {
    label: "deletion protection off",
    tone: "medium",
    blurb: "DeletionProtection=false — single API call can drop the DB.",
  },
  rds_master_password_change: {
    label: "master password changed",
    tone: "medium",
    blurb: "Could be a rotation or a takeover. Check the actor.",
  },
  rds_iam_auth_disabled: {
    label: "IAM auth disabled",
    tone: "medium",
    blurb: "Falls back to master password only.",
  },
  rds_security_params_changed: {
    label: "TLS / log param changed",
    tone: "high",
    blurb: "rds.force_ssl, log_connections, or log_statement was touched.",
  },
};

export default async function RdsPage() {
  const data = await fetchRds();

  return (
    <>
      <AutoRefresh intervalMs={10_000} />
      <PageHeader
        title="RDS · database posture"
        subtitle="Event-driven view of every RDS change CloudTrail records. Instances appear after their first relevant event."
      />

      {!data.have_connector && <ConnectorMissingBanner />}

      <CountersStrip counts={data.counts} />

      <InstancesSection instances={data.instances} />

      <RecentEventsSection events={data.recent_events} />
    </>
  );
}

// =========================================================================
// connector banner — explains why the page might be empty
// =========================================================================

function ConnectorMissingBanner() {
  return (
    <div className="mb-4 border-l-2 border-sev-high bg-surface-1 px-3 py-2 text-xs text-fg-muted">
      No CloudTrail SQS connector is enabled. RDS events flow through that
      pipeline — without it, this page stays empty.{" "}
      <Link href="/connectors" className="text-signal hover:underline">
        configure a connector →
      </Link>
    </div>
  );
}

// =========================================================================
// counters
// =========================================================================

function CountersStrip({ counts }: { counts: RdsCounts }) {
  // First row = volume + inventory; second row = exposure flags
  const volume: Array<{ label: string; value: number; tone?: string }> = [
    { label: "events · 24h", value: counts.events_24h },
    { label: "instances seen · 30d", value: counts.instances_seen },
  ];

  const flags: Array<{ label: string; value: number; tone: string }> = [
    { label: "publicly accessible", value: counts.public_flagged, tone: "critical" },
    { label: "snapshot · public", value: counts.snapshot_public_flagged, tone: "critical" },
    { label: "no backups", value: counts.no_backups_flagged, tone: "high" },
    { label: "unencrypted", value: counts.unencrypted_flagged, tone: "high" },
    { label: "no deletion-protect", value: counts.no_deletion_protection_flagged, tone: "medium" },
  ];

  return (
    <section className="mb-4 space-y-2">
      <div className="grid grid-cols-2 gap-2">
        {volume.map((c) => (
          <CounterCell key={c.label} label={c.label} value={c.value} />
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
        {flags.map((c) => (
          <CounterCell
            key={c.label}
            label={c.label}
            value={c.value}
            tone={c.tone}
          />
        ))}
      </div>
    </section>
  );
}

function CounterCell({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: string;
}) {
  const isHot = (tone === "critical" || tone === "high") && value > 0;
  return (
    <div
      className={clsx(
        "border border-line-soft bg-surface-1 px-3 py-2.5",
        isHot && tone === "critical" && "border-sev-critical/40",
        isHot && tone === "high" && "border-sev-high/40",
      )}
    >
      <p className="text-[10px] uppercase tracking-[0.06em] text-fg-subtle">
        {label}
      </p>
      <p
        className={clsx(
          "mt-1 font-mono text-xl text-fg",
          isHot && tone === "critical" && "text-sev-critical",
          isHot && tone === "high" && "text-sev-high",
        )}
      >
        {value}
      </p>
    </div>
  );
}

// =========================================================================
// instances list — one card per DB we've seen events for
// =========================================================================

function InstancesSection({ instances }: { instances: RdsInstance[] }) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>database instances · last 30 days</SectionLabel>
        <span className="text-[10px] text-fg-disabled">
          appear after their first CloudTrail event lands
        </span>
      </div>
      <DataPanel className="overflow-hidden">
        {instances.length === 0 ? (
          <EmptyState>
            No RDS events captured yet. Trigger one (e.g.{" "}
            <code className="font-mono text-[11px]">
              aws rds modify-db-instance --no-deletion-protection
            </code>
            ) and it should appear here within 5–15 minutes (CloudTrail
            propagation lag).
          </EmptyState>
        ) : (
          <ul className="divide-y divide-line-soft">
            {instances.map((inst) => (
              <InstanceRow key={inst.instance_id} instance={inst} />
            ))}
          </ul>
        )}
      </DataPanel>
    </section>
  );
}

function InstanceRow({ instance }: { instance: RdsInstance }) {
  return (
    <li className="grid grid-cols-1 gap-3 px-4 py-3 md:grid-cols-[1fr_auto] md:items-start">
      <div className="space-y-1.5">
        <div className="flex flex-wrap items-baseline gap-2">
          <code className="font-mono text-sm text-fg">{instance.instance_id}</code>
          <span className="text-[11px] text-fg-subtle">
            {instance.events_30d} event{instance.events_30d === 1 ? "" : "s"} in
            30d
          </span>
        </div>

        {instance.flags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {instance.flags.map((f) => {
              const meta = FLAG_META[f] ?? {
                label: f,
                tone: "info" as const,
                blurb: "",
              };
              return (
                <span
                  key={f}
                  title={meta.blurb}
                  className={clsx(
                    "inline-flex items-center border px-1.5 py-0.5 text-[10px] uppercase tracking-[0.06em]",
                    meta.tone === "critical" &&
                      "border-sev-critical/50 bg-sev-critical/10 text-sev-critical",
                    meta.tone === "high" &&
                      "border-sev-high/50 bg-sev-high/10 text-sev-high",
                    meta.tone === "medium" &&
                      "border-sev-medium/50 bg-sev-medium/10 text-sev-medium",
                    meta.tone === "info" && "border-line text-fg-muted",
                  )}
                >
                  {meta.label}
                </span>
              );
            })}
          </div>
        )}

        <p className="text-[11px] text-fg-subtle">
          last:{" "}
          <code className="font-mono text-fg-muted">
            {instance.last_action ?? "—"}
          </code>{" "}
          {instance.last_actor && (
            <>
              by{" "}
              <code className="font-mono text-fg-muted">
                {shortenArn(instance.last_actor)}
              </code>{" "}
            </>
          )}
        </p>
      </div>
      <div className="text-right text-[11px] text-fg-subtle">
        {instance.last_event_time ? (
          <TimestampCell value={instance.last_event_time} />
        ) : (
          "—"
        )}
      </div>
    </li>
  );
}

// =========================================================================
// recent events table
// =========================================================================

function RecentEventsSection({ events }: { events: EventEnvelope[] }) {
  return (
    <section className="mt-6 space-y-2">
      <SectionLabel>recent rds events · last 24h</SectionLabel>
      <DataPanel className="overflow-hidden">
        {events.length === 0 ? (
          <EmptyState>
            No RDS events in the last 24 hours. CloudTrail latency for
            ModifyDBInstance is typically 5–15 minutes; check back shortly
            after triggering one.
          </EmptyState>
        ) : (
          <table className="w-full table-fixed text-sm">
            <thead>
              <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
                <th className="w-32 px-4 py-2 text-left font-normal">Time</th>
                <th className="w-44 px-4 py-2 text-left font-normal">Action</th>
                <th className="w-48 px-4 py-2 text-left font-normal">Instance</th>
                <th className="w-44 px-4 py-2 text-left font-normal">Actor</th>
                <th className="px-4 py-2 text-left font-normal">Signal</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <EventRow key={String(e.event_id ?? `${e.action}-${e.event_time}`)} event={e} />
              ))}
            </tbody>
          </table>
        )}
      </DataPanel>
    </section>
  );
}

function EventRow({ event: e }: { event: EventEnvelope }) {
  const flags = collectFlags(e);
  return (
    <tr className="border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="px-4 py-2.5 align-top">
        <TimestampCell value={e.event_time} />
      </td>
      <td className="px-4 py-2.5 align-top">
        <code className="font-mono text-xs text-fg">{e.action}</code>
      </td>
      <td className="truncate px-4 py-2.5 align-top">
        <code className="font-mono text-xs text-fg-muted">
          {e.target?.id ?? "—"}
        </code>
      </td>
      <td className="truncate px-4 py-2.5 align-top">
        <span className="font-mono text-xs text-fg-muted">
          {shortenArn(e.actor?.principal)}
        </span>
      </td>
      <td className="px-4 py-2.5 align-top">
        {flags.length === 0 ? (
          <span className="text-[11px] text-fg-disabled">—</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {flags.map((f) => {
              const meta = FLAG_META[f] ?? {
                label: f,
                tone: "info" as const,
                blurb: "",
              };
              return (
                <span
                  key={f}
                  title={meta.blurb}
                  className={clsx(
                    "border px-1.5 py-0.5 text-[10px] uppercase tracking-[0.06em]",
                    meta.tone === "critical" &&
                      "border-sev-critical/50 bg-sev-critical/10 text-sev-critical",
                    meta.tone === "high" &&
                      "border-sev-high/50 bg-sev-high/10 text-sev-high",
                    meta.tone === "medium" &&
                      "border-sev-medium/50 bg-sev-medium/10 text-sev-medium",
                    meta.tone === "info" && "border-line text-fg-muted",
                  )}
                >
                  {meta.label}
                </span>
              );
            })}
          </div>
        )}
      </td>
    </tr>
  );
}

// =========================================================================
// shared bits
// =========================================================================

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-6 py-10 text-center text-sm text-fg-muted">
      {children}
    </div>
  );
}

// IAM ARNs are noisy — `arn:aws:iam::095899260107:user/apoorva.sharma@…` is
// 60+ chars. Strip to just the role/user name so the table doesn't wrap.
function shortenArn(value: string | null | undefined): string {
  if (!value) return "—";
  if (!value.startsWith("arn:")) return value;
  const last = value.split("/").pop();
  return last || value;
}

function collectFlags(e: EventEnvelope): string[] {
  const extras = (e.extra ?? {}) as Record<string, unknown>;
  return Object.keys(extras).filter(
    (k) => k.startsWith("rds_") && extras[k] && extras[k] !== false,
  );
}
