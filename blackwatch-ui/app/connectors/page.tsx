import Link from "next/link";
import clsx from "clsx";
import { Plus, Pencil } from "lucide-react";

import { fetchConnectors } from "@/lib/api";
import type { Connector } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { Button } from "@/components/ui/Button";
import { ConfirmSubmitButton } from "@/components/ui/ConfirmSubmitButton";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { StatusPill as SharedStatusPill } from "@/components/ui/StatusPill";
import { RequireAdmin } from "@/components/auth/RequireAdmin";
import { ConnectorActionButton } from "@/components/domain/connectors/ConnectorActionButton";
import { RetryAllButton } from "@/components/domain/connectors/RetryAllButton";
import {
  toggleConnectorAction,
  deleteConnectorAction,
} from "./actions";

type SearchParams = { msg?: string };

export default async function ConnectorsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { msg } = await searchParams;
  const { count, connectors, scheduler } = await fetchConnectors();

  return (
    <>
      <PageHeader
        title="Connectors"
        subtitle={`${count} configured · poll AWS, SQS, and probe targets on a schedule`}
        actions={
          <div className="flex items-center gap-2">
            <RequireAdmin>
              <RetryAllButton />
            </RequireAdmin>
            <Button asChild variant="primary" size="sm">
              <Link href="/connectors/new">
                <Plus size={14} /> Add connector
              </Link>
            </Button>
          </div>
        }
      />

      {msg && (
        <div className="mb-4 border-l-2 border-signal bg-surface-1 px-3 py-2 text-xs text-fg-muted">
          <span className="text-signal">·</span> {msg}
        </div>
      )}

      {scheduler?.heartbeat_at && (
        <div className="mb-4 text-[11px] text-fg-subtle" role="status">
          scheduler heartbeat <TimestampCell value={scheduler.heartbeat_at} />
        </div>
      )}

      <DataPanel className="overflow-hidden">
        {connectors.length === 0 ? (
          <div className="px-6 py-12 text-center text-sm text-fg-muted">
            No connectors yet.{" "}
            <Link href="/connectors/new" className="text-signal hover:underline">
              Add one →
            </Link>
          </div>
        ) : (
          <ConnectorsTable connectors={connectors} />
        )}
      </DataPanel>
    </>
  );
}

// =========================================================================
// table
// =========================================================================

function ConnectorsTable({ connectors }: { connectors: Connector[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-44 px-4 py-2 text-left font-normal">Name</th>
          <th className="w-44 px-4 py-2 text-left font-normal">Type</th>
          <th className="px-4 py-2 text-left font-normal">Details</th>
          <th className="w-24 px-4 py-2 text-left font-normal">Verified</th>
          <th className="w-32 px-4 py-2 text-left font-normal">Schedule</th>
          <th className="w-36 px-4 py-2 text-left font-normal">Last run</th>
          <th className="w-24 px-4 py-2 text-left font-normal">Status</th>
          <th className="w-72 px-4 py-2 text-right font-normal" />
        </tr>
      </thead>
      <tbody>
        {connectors.map((c) => (
          <ConnectorRow key={c.id} connector={c} />
        ))}
      </tbody>
    </Table>
  );
}

function ConnectorRow({ connector: c }: { connector: Connector }) {
  return (
    <>
      <tr className="border-b border-line-soft hover:bg-surface-2">
        <td className="truncate px-4 py-2.5 text-sm text-fg">{c.name}</td>
        <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
          {c.type}
        </td>
        <td className="truncate px-4 py-2.5 font-mono text-[11px] text-fg-muted">
          <ConnectorDetails connector={c} />
        </td>
        <td className="px-4 py-2.5">
          {c.verified ? (
            <SharedStatusPill severity="resolved" label="verified" />
          ) : (
            <SharedStatusPill severity="neutral" label="not tested" />
          )}
        </td>
        <td className="px-4 py-2.5 font-mono text-xs">
          <span className={c.enabled ? "text-fg" : "text-fg-subtle"}>
            {c.enabled ? "on" : "off"}
          </span>
          <span className="ml-1 text-fg-subtle">
            · {String((c.config as { interval_seconds?: number }).interval_seconds ?? "—")}s
          </span>
        </td>
        <td className="px-4 py-2.5">
          {c.last_run_at ? (
            <TimestampCell value={c.last_run_at} />
          ) : (
            <span className="text-fg-disabled">—</span>
          )}
        </td>
        <td className="px-4 py-2.5">
          <StatusPill connector={c} />
        </td>
        <td className="whitespace-nowrap px-4 py-2.5 text-right">
          <Actions connector={c} />
        </td>
      </tr>
      {(c.last_error || c.latest_operation?.error_message) && (
        <tr className="border-b border-line-soft">
          <td colSpan={8} className="bg-surface-1 px-4 py-1.5 font-mono text-[11px] text-sev-critical">
            {c.latest_operation?.error_category ? `${c.latest_operation.error_category}: ` : "last error: "}
            {c.latest_operation?.error_message ?? c.last_error}
            {c.latest_operation?.correlation_id && (
              <span className="ml-2 text-fg-subtle">ref {c.latest_operation.correlation_id.slice(0, 8)}</span>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

// --- per-row action buttons -----------------------------------------------

function Actions({ connector: c }: { connector: Connector }) {
  return (
    <RequireAdmin>
      <div className="inline-flex items-center gap-1.5">
        <ConnectorActionButton connectorId={c.id} kind="test" />
        <ConnectorActionButton connectorId={c.id} kind="manual" disabled={!c.verified} />

        <form action={toggleConnectorAction} className="inline">
          <input type="hidden" name="connector_id" value={c.id} />
          <input type="hidden" name="enabled" value={c.enabled ? "off" : "on"} />
          <Button type="submit" size="sm" variant="secondary" disabled={!c.verified} title={!c.verified ? "Test successfully first" : ""}>
            {c.enabled ? "Disable" : "Enable"}
          </Button>
        </form>

        <Button asChild size="sm" variant="ghost">
          <Link href={`/connectors/${c.id}`} title="Edit"><Pencil size={12} /></Link>
        </Button>

        <form action={deleteConnectorAction} className="inline">
          <input type="hidden" name="connector_id" value={c.id} />
          <ConfirmSubmitButton size="sm" variant="danger" confirmMessage={`Delete connector “${c.name}”? This cannot be undone.`}>
            Delete
          </ConfirmSubmitButton>
        </form>
      </div>
    </RequireAdmin>
  );
}

// --- type-specific "details" cell -----------------------------------------

function ConnectorDetails({ connector: c }: { connector: Connector }) {
  const cfg = c.config as Record<string, unknown>;
  switch (c.type) {
    case "aws_cloudtrail_sqs":
      return (
        <span>
          {String(cfg.aws_region ?? "—")} ·{" "}
          {String(cfg.target_module ?? "aws.cloudtrail")}
        </span>
      );
    case "aws_ecs_health":
      return (
        <span>
          {String(cfg.aws_region ?? "—")} · vpc={String(cfg.vpc ?? "—")}
        </span>
      );
    case "aws_s3_drift":
      return (
        <span>
          all regions · profile={String(cfg.aws_profile ?? "(default)")}
        </span>
      );
    case "aws_s3_access_logs":
      return (
        <span>
          bucket={String(cfg.bucket ?? "—")} · prefix={String(cfg.prefix ?? "(all)")}
        </span>
      );
    case "aws_posture_drift": {
      const regions = (cfg.regions as string[]) ?? [];
      return (
        <span>
          {regions.length > 0 ? regions.join(",") : "all regions"} · profile=
          {String(cfg.aws_profile ?? "(default)")}
        </span>
      );
    }
    case "cert_probe": {
      const targets = (cfg.targets as unknown[]) ?? [];
      return (
        <span>
          {targets.length} target{targets.length === 1 ? "" : "s"} · every{" "}
          {String(cfg.interval_seconds ?? 3600)}s
        </span>
      );
    }
    default:
      return <>—</>;
  }
}

// --- pills ----------------------------------------------------------------

function StatusPill({
  connector,
}: {
  connector: Connector;
}) {
  const operation = connector.latest_operation;
  if (operation?.status === "queued" || operation?.status === "running") {
    return <SharedStatusPill severity="neutral" label={operation.status} />;
  }
  const state = connector.health_state ?? connector.last_status;
  if (state === "healthy" || state === "ok") {
    return <SharedStatusPill severity="resolved" label="healthy" />;
  }
  if (state === "failing" || state === "error" || operation?.status === "failed" || operation?.status === "timed_out") {
    return <SharedStatusPill severity="critical" label={operation?.status === "timed_out" ? "timed out" : "failing"} />;
  }
  if (state === "stale") return <SharedStatusPill severity="medium" label="stale" />;
  if (state === "disabled") return <SharedStatusPill severity="neutral" label="disabled" />;
  if (state === "unverified") return <SharedStatusPill severity="neutral" label="unverified" />;
  return <SharedStatusPill severity="neutral" label="never run" />;
}
