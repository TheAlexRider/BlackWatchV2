import Link from "next/link";
import clsx from "clsx";

import { fetchIam } from "@/lib/api";
import type { EventEnvelope, IamCounts } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { TimestampCell } from "@/components/domain/TimestampCell";
import {
  SeverityBadge,
  severityBorderBg,
} from "@/components/domain/SeverityBadge";
import { IpCell } from "@/components/domain/IpCell";

export default async function IamPage() {
  const data = await fetchIam();

  return (
    <>
      <AutoRefresh intervalMs={10_000} />

      <PageHeader
        title="IAM · AWS control plane"
        subtitle="Everything CloudTrail records — logins, IAM, network, storage, KMS, audit integrity. Host SSH/sudo and VPN auth live on /hosts and /vpn."
      />

      <CountersStrip counts={data.counts} />

      <EventsSection
        title="console + sso logins"
        subtitle="AWS console sign-ins (IAM + root) and federated SAML / WebIdentity logins"
        events={data.logins}
        showOutcome
        showSourceIp
        showLoginKind
        emptyHint="No console or federated logins captured in the recent window."
      />

      <EventsSection
        title="iam changes"
        subtitle="users · roles · groups · policies · access keys · MFA · login profiles · permission boundaries"
        events={data.iam_changes}
        showTarget
        emptyHint="No IAM changes in the recent window."
      />

      <EventsSection
        title="security group changes"
        subtitle="ingress / egress / create / delete / instance attach"
        events={data.sg_changes}
        showTarget
        showSgDetail
        emptyHint="No SG changes in the recent window."
      />

      <EventsSection
        title="network topology"
        subtitle="vpc · igw · nat · route · nacl · peering — the SHAPE of the network, not its rules"
        events={data.network_topology}
        showTarget
        emptyHint="No topology changes — VPCs, gateways, routes, and peerings are stable."
        emptyTone="ok"
      />

      <EventsSection
        title="storage / compute exposure"
        subtitle="S3 ACL · S3 policy · BPA · snapshot public · AMI public · IMDSv1 enabled"
        events={data.storage_exposure}
        showTarget
        showExposureDetail
        emptyHint="No storage / compute exposure changes — nothing was made public."
        emptyTone="ok"
      />

      <EventsSection
        title="kms / secrets"
        subtitle="key create · enable / disable · key policy · grants · rotation · scheduled deletion"
        events={data.kms_changes}
        showTarget
        emptyHint="No KMS changes in the recent window."
      />

      <PostureFindingsSection events={data.posture_findings_new} />

      <EventsSection
        title="cloudtrail tamper · audit"
        subtitle="anyone touching the audit trail itself · should always be empty"
        events={data.ct_tamper}
        showTarget
        emptyHint="Clean — nobody has stopped logging or modified a trail."
        emptyTone="ok"
      />
    </>
  );
}

// =========================================================================
// counters strip — 10 cells, wraps as 2 rows of 5
// =========================================================================

function CountersStrip({ counts }: { counts: IamCounts }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
      <CounterCell
        label="Logins · ok"
        value={counts.logins_ok}
        accent="neutral"
      />
      <CounterCell
        label="Logins · failed"
        value={counts.logins_failed}
        accent={
          counts.logins_failed >= 5
            ? "critical"
            : counts.logins_failed > 0
              ? "medium"
              : "ok"
        }
      />
      <CounterCell
        label="Logins · root"
        value={counts.logins_root}
        accent={counts.logins_root > 0 ? "critical" : "ok"}
      />
      <CounterCell
        label="Logins · sso"
        value={counts.logins_sso}
        accent="neutral"
      />
      <CounterCell
        label="MFA disabled"
        value={counts.mfa_disabled}
        accent={counts.mfa_disabled > 0 ? "critical" : "ok"}
      />
      <CounterCell
        label="IAM changes"
        value={counts.iam_changes}
        accent={counts.iam_changes > 0 ? "neutral" : "ok"}
      />
      <CounterCell
        label="SG changes"
        value={counts.sg_changes}
        accent={counts.sg_changes > 0 ? "neutral" : "ok"}
      />
      <CounterCell
        label="Network topology"
        value={counts.network_topology}
        accent={counts.network_topology > 0 ? "medium" : "ok"}
      />
      <CounterCell
        label="Storage exposure"
        value={counts.storage_exposure}
        accent={
          counts.storage_exposure > 0 ? "critical" : "ok"
        }
      />
      <CounterCell
        label="KMS changes"
        value={counts.kms_changes}
        accent={counts.kms_changes > 0 ? "medium" : "ok"}
      />
      <CounterCell
        label="CT tamper"
        value={counts.ct_tamper}
        accent={counts.ct_tamper > 0 ? "critical" : "ok"}
      />
    </div>
  );
}

type Accent = "ok" | "neutral" | "medium" | "critical";

function CounterCell({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent: Accent;
}) {
  const dot =
    accent === "critical"
      ? "bg-sev-critical"
      : accent === "medium"
        ? "bg-sev-medium"
        : accent === "ok"
          ? "bg-sev-resolved"
          : "bg-fg-subtle";
  return (
    <div className="border border-line-soft bg-surface-1 px-3 py-2.5">
      <div className="truncate text-[11px] uppercase tracking-[0.08em] text-fg-subtle" title={label}>
        {label}
      </div>
      <div className="mt-1.5 flex items-baseline gap-2">
        <span
          aria-hidden
          className={clsx("h-1.5 w-1.5 translate-y-[-2px] rounded-full", dot)}
        />
        <span
          className={clsx(
            "font-mono text-2xl tabular-nums",
            value === 0 ? "text-fg-disabled" : "text-fg",
          )}
        >
          {value}
        </span>
        <span className="font-mono text-[10px] text-fg-subtle">/24h</span>
      </div>
    </div>
  );
}

// =========================================================================
// reusable section
// =========================================================================

interface EventsSectionProps {
  title: string;
  subtitle?: string;
  events: EventEnvelope[];
  showOutcome?: boolean;
  showSourceIp?: boolean;
  showTarget?: boolean;
  showSgDetail?: boolean;
  showExposureDetail?: boolean;
  showLoginKind?: boolean;
  emptyHint?: string;
  emptyTone?: "neutral" | "ok";
}

function EventsSection({
  title,
  subtitle,
  events,
  showOutcome,
  showSourceIp,
  showTarget,
  showSgDetail,
  showExposureDetail,
  showLoginKind,
  emptyHint,
  emptyTone = "neutral",
}: EventsSectionProps) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>
          {title}
          {events.length > 0 && (
            <span className="ml-2 normal-case tracking-normal text-fg-subtle">
              · {events.length}
            </span>
          )}
        </SectionLabel>
        {subtitle && (
          <span className="text-[11px] text-fg-subtle">{subtitle}</span>
        )}
      </div>
      <DataPanel className="overflow-hidden">
        {events.length === 0 ? (
          <EmptyState tone={emptyTone}>{emptyHint ?? "Nothing here."}</EmptyState>
        ) : (
          <EventsTable
            events={events}
            showOutcome={showOutcome}
            showSourceIp={showSourceIp}
            showTarget={showTarget}
            showSgDetail={showSgDetail}
            showExposureDetail={showExposureDetail}
            showLoginKind={showLoginKind}
          />
        )}
      </DataPanel>
    </section>
  );
}

function EventsTable({
  events,
  showOutcome,
  showSourceIp,
  showTarget,
  showSgDetail,
  showExposureDetail,
  showLoginKind,
}: {
  events: EventEnvelope[];
  showOutcome?: boolean;
  showSourceIp?: boolean;
  showTarget?: boolean;
  showSgDetail?: boolean;
  showExposureDetail?: boolean;
  showLoginKind?: boolean;
}) {
  return (
    <table className="w-full table-fixed text-sm">
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-36 px-4 py-2 text-left font-normal">Time</th>
          <th className="w-24 px-4 py-2 text-left font-normal">Severity</th>
          <th className="w-56 px-4 py-2 text-left font-normal">Action</th>
          {showLoginKind && (
            <th className="w-20 px-4 py-2 text-left font-normal">Kind</th>
          )}
          <th className="w-44 px-4 py-2 text-left font-normal">Actor</th>
          {showOutcome && (
            <th className="w-24 px-4 py-2 text-left font-normal">Result</th>
          )}
          {showSourceIp && (
            <th className="w-36 px-4 py-2 text-left font-normal">Source IP</th>
          )}
          {showTarget ? (
            <th className="px-4 py-2 text-left font-normal">
              {showSgDetail
                ? "Target / detail"
                : showExposureDetail
                  ? "Target / exposure flag"
                  : "Target"}
            </th>
          ) : (
            <th className="px-4 py-2 text-left font-normal">Detail</th>
          )}
        </tr>
      </thead>
      <tbody>
        {events.map((e) => (
          <EventRow
            key={e.event_id}
            event={e}
            showOutcome={showOutcome}
            showSourceIp={showSourceIp}
            showTarget={showTarget}
            showSgDetail={showSgDetail}
            showExposureDetail={showExposureDetail}
            showLoginKind={showLoginKind}
          />
        ))}
      </tbody>
    </table>
  );
}

function EventRow({
  event,
  showOutcome,
  showSourceIp,
  showTarget,
  showSgDetail,
  showExposureDetail,
  showLoginKind,
}: {
  event: EventEnvelope;
  showOutcome?: boolean;
  showSourceIp?: boolean;
  showTarget?: boolean;
  showSgDetail?: boolean;
  showExposureDetail?: boolean;
  showLoginKind?: boolean;
}) {
  const severity = (event.severity as string | null | undefined) ?? null;
  const sourceIp = (event.actor as { source_ip?: string } | undefined)?.source_ip;
  const target = event.target?.id ?? event.target?.name ?? "—";

  return (
    <tr className="group relative border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="relative px-4 py-2.5">
        <span
          aria-hidden
          className={clsx(
            "pointer-events-none absolute left-0 top-0 h-full w-0.5",
            severityBorderBg(severity),
          )}
        />
        <TimestampCell value={event.event_time} />
      </td>
      <td className="px-4 py-2.5">
        <SeverityBadge severity={severity} />
      </td>
      <td className="truncate px-4 py-2.5">
        <Link
          href={`/events/${event.event_id}`}
          className="font-mono text-xs text-fg transition-colors hover:text-signal"
        >
          {event.action}
        </Link>
      </td>
      {showLoginKind && (
        <td className="px-4 py-2.5">
          <LoginKindPill event={event} />
        </td>
      )}
      <td className="truncate px-4 py-2.5 text-xs text-fg">
        {event.actor?.principal ?? <span className="text-fg-disabled">—</span>}
      </td>
      {showOutcome && (
        <td className="px-4 py-2.5">
          <OutcomePill outcome={event.outcome} />
        </td>
      )}
      {showSourceIp && (
        <td className="px-4 py-2.5 text-xs">
          <IpCell value={sourceIp} className="text-xs text-fg-muted" />
        </td>
      )}
      {showTarget ? (
        <td className="truncate px-4 py-2.5 font-mono text-[11px] text-fg-muted">
          {showSgDetail ? (
            <SgDetail event={event} fallback={target} />
          ) : showExposureDetail ? (
            <ExposureDetail event={event} fallback={target} />
          ) : (
            target
          )}
        </td>
      ) : (
        <td className="truncate px-4 py-2.5 font-mono text-[11px] text-fg-muted">
          {target}
        </td>
      )}
    </tr>
  );
}

function LoginKindPill({ event }: { event: EventEnvelope }) {
  const extra = (event.extra as Record<string, unknown> | undefined) ?? {};
  const kind = String(extra.login_kind ?? "iam").toLowerCase();
  const cls =
    kind === "root"
      ? "border-sev-critical/40 bg-sev-critical/10 text-sev-critical"
      : kind === "sso"
        ? "border-signal/30 bg-signal/10 text-signal"
        : "border-line-soft bg-surface-1 text-fg-muted";
  return (
    <span
      className={clsx(
        "inline-flex h-5 items-center rounded-sm border px-1.5 font-mono text-[10px] uppercase tracking-[0.08em]",
        cls,
      )}
    >
      {kind}
    </span>
  );
}

// =========================================================================
// detail renderers
// =========================================================================

function SgDetail({
  event,
  fallback,
}: {
  event: EventEnvelope;
  fallback: string;
}) {
  const extra = (event.extra as Record<string, unknown> | undefined) ?? {};
  const parts: React.ReactNode[] = [];

  if (event.action === "network.sg.instance_attach") {
    const instanceId = String(extra.instance_id ?? event.target?.id ?? "—");
    const sgIds = Array.isArray(extra.sg_ids) ? (extra.sg_ids as string[]) : [];
    return (
      <>
        <span>{instanceId}</span>
        {sgIds.length > 0 && (
          <span> · attached {sgIds.length} SG{sgIds.length === 1 ? "" : "s"}: </span>
        )}
        {sgIds.map((id, i) => (
          <span key={id}>
            <code className="text-fg">{id}</code>
            {i < sgIds.length - 1 ? ", " : ""}
          </span>
        ))}
      </>
    );
  }

  const sg = event.target?.id ?? event.target?.name;
  if (sg) parts.push(<span key="sg">{String(sg)}</span>);

  const port = extra.port ?? extra.from_port;
  const toPort = extra.to_port;
  const proto = extra.proto ?? extra.ip_protocol;
  if (port !== undefined) {
    parts.push(
      <span key="port">
        {String(proto ?? "tcp")}/{String(port)}
        {toPort !== undefined && toPort !== port ? `–${String(toPort)}` : ""}
      </span>,
    );
  }

  const cidr = extra.cidr ?? extra.cidr_ip ?? extra.address;
  if (cidr) parts.push(<span key="cidr">from {String(cidr)}</span>);

  if (extra.public_ingress_risky_port) {
    parts.push(
      <span key="risky" className="text-sev-critical">
        ⚠ public risky port
      </span>,
    );
  } else if (extra.public_ingress) {
    parts.push(
      <span key="public" className="text-sev-medium">
        public ingress
      </span>,
    );
  }

  if (parts.length === 0) return <>{fallback}</>;
  return (
    <>
      {parts.map((p, i) =>
        i === 0 ? p : <span key={`sep-${i}`}> · {p}</span>,
      )}
    </>
  );
}

function ExposureDetail({
  event,
  fallback,
}: {
  event: EventEnvelope;
  fallback: string;
}) {
  const extra = (event.extra as Record<string, unknown> | undefined) ?? {};
  const target = event.target?.id ?? event.target?.name ?? fallback;
  const flags: string[] = [];
  if (extra.public_acl) flags.push("public ACL");
  if (extra.public_policy) flags.push("public policy");
  if (extra.bpa_weakened) flags.push("BPA weakened");
  if (extra.versioning_suspended) flags.push("versioning suspended");
  if (extra.mfa_delete_disabled) flags.push("MFA-delete disabled");
  if (extra.logging_disabled) flags.push("logging disabled");
  if (extra.snapshot_made_public) flags.push("snapshot → public");
  if (extra.ami_made_public) flags.push("AMI → public");
  if (extra.imdsv1_enabled) flags.push("IMDSv1 enabled");

  return (
    <>
      <span>{String(target)}</span>
      {flags.length > 0 && (
        <span className="ml-2 text-sev-critical">
          · {flags.join(" · ")}
        </span>
      )}
    </>
  );
}

// =========================================================================
// posture findings section — links to /aws-posture for the full list
// =========================================================================

function PostureFindingsSection({ events }: { events: EventEnvelope[] }) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>
          posture findings · new
          {events.length > 0 && (
            <span className="ml-2 normal-case tracking-normal text-fg-subtle">
              · {events.length}
            </span>
          )}
        </SectionLabel>
        <Link
          href="/aws-posture"
          className="text-[11px] text-fg-subtle hover:text-fg"
        >
          full posture →
        </Link>
      </div>
      <DataPanel className="overflow-hidden">
        {events.length === 0 ? (
          <EmptyState tone="ok">
            No new posture findings in the recent window.
          </EmptyState>
        ) : (
          <table className="w-full table-fixed text-sm">
            <thead>
              <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
                <th className="w-36 px-4 py-2 text-left font-normal">Time</th>
                <th className="w-24 px-4 py-2 text-left font-normal">Severity</th>
                <th className="w-48 px-4 py-2 text-left font-normal">Finding</th>
                <th className="w-24 px-4 py-2 text-left font-normal">Region</th>
                <th className="px-4 py-2 text-left font-normal">Resource</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => {
                const extra = (e.extra as Record<string, unknown> | undefined) ?? {};
                const findingId = extra.finding_id as string | undefined;
                return (
                  <tr
                    key={e.event_id}
                    className="group relative border-b border-line-soft last:border-0 hover:bg-surface-2"
                  >
                    <td className="relative px-4 py-2.5">
                      <span
                        aria-hidden
                        className={clsx(
                          "pointer-events-none absolute left-0 top-0 h-full w-0.5",
                          severityBorderBg(e.severity as string | null | undefined),
                        )}
                      />
                      <TimestampCell value={e.event_time} />
                    </td>
                    <td className="px-4 py-2.5">
                      <SeverityBadge severity={(e.severity as string) ?? null} />
                    </td>
                    <td className="truncate px-4 py-2.5">
                      {findingId ? (
                        <Link
                          href={`/aws-posture/${findingId}`}
                          className="font-mono text-xs text-fg hover:text-signal"
                        >
                          {String(extra.finding_type ?? e.action)}
                        </Link>
                      ) : (
                        <span className="font-mono text-xs text-fg">
                          {String(extra.finding_type ?? e.action)}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">
                      {String(extra.region ?? "—")}
                    </td>
                    <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
                      {String(extra.resource_id ?? e.target?.id ?? "—")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </DataPanel>
    </section>
  );
}

// =========================================================================
// pills
// =========================================================================

function OutcomePill({ outcome }: { outcome: string | undefined }) {
  const ok = outcome === "success";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        aria-hidden
        className={clsx(
          "h-1.5 w-1.5 rounded-full",
          ok ? "bg-sev-resolved" : "bg-sev-critical",
        )}
      />
      <span className={ok ? "text-fg-muted" : "text-fg"}>
        {ok ? "success" : "FAILED"}
      </span>
    </span>
  );
}

function EmptyState({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "ok";
}) {
  return (
    <div className="flex items-center justify-center gap-2 px-6 py-8 text-sm text-fg-muted">
      {tone === "ok" && (
        <span
          aria-hidden
          className="h-1.5 w-1.5 rounded-full bg-sev-resolved"
        />
      )}
      <span>{children}</span>
    </div>
  );
}
