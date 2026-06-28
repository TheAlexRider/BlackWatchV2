import Link from "next/link";
import clsx from "clsx";

import { fetchFimView } from "@/lib/api";
import type {
  FimHostRow,
  FimChangeWithInstance,
} from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { ResizableTable } from "@/components/ui/ResizableTable";

export default async function FimPage() {
  const { count, hosts, recent_changes } = await fetchFimView();

  return (
    <>
      <AutoRefresh intervalMs={15_000} />
      <PageHeader
        title="File integrity monitoring"
        subtitle={
          `${count} host${count === 1 ? "" : "s"} monitored · ` +
          `inotify + auditd whodata + 6h baseline scan`
        }
      />

      <section className="space-y-2">
        <SectionLabel>monitored hosts</SectionLabel>
        <DataPanel className="overflow-hidden">
          {hosts.length === 0 ? (
            <EmptyState>
              No hosts are reporting FIM data yet. Install the EC2 agent
              (v1.3+) — FIM auto-enables on first start.
            </EmptyState>
          ) : (
            <HostsTable hosts={hosts} />
          )}
        </DataPanel>
      </section>

      <section className="mt-6 space-y-2">
        <div className="flex items-baseline justify-between">
          <SectionLabel>recent fim activity · all hosts</SectionLabel>
          <span className="text-[11px] text-fg-subtle">
            last {recent_changes.length} change
            {recent_changes.length === 1 ? "" : "s"}
          </span>
        </div>
        <DataPanel className="overflow-hidden">
          {recent_changes.length === 0 ? (
            <EmptyState>
              No file integrity changes recorded across any host. Either the
              agents just established their baselines or nothing has drifted.
            </EmptyState>
          ) : (
            <ChangesTable changes={recent_changes} />
          )}
        </DataPanel>
      </section>
    </>
  );
}

// =========================================================================
// hosts
// =========================================================================

function HostsTable({ hosts }: { hosts: FimHostRow[] }) {
  return (
    <ResizableTable tableId="fim-hosts">
    <table className="w-full table-fixed text-sm">
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-20 px-4 py-2 text-left font-normal">Env</th>
          <th className="w-32 px-4 py-2 text-left font-normal">Role</th>
          <th className="w-36 px-4 py-2 text-left font-normal">Instance</th>
          <th className="w-32 px-4 py-2 text-left font-normal">Hostname</th>
          <th className="w-20 px-4 py-2 text-right font-normal">Files</th>
          <th className="w-24 px-4 py-2 text-right font-normal">Paths</th>
          <th className="w-28 px-4 py-2 text-left font-normal">Real-time</th>
          <th className="w-28 px-4 py-2 text-left font-normal">Whodata</th>
          <th className="px-4 py-2 text-left font-normal">Last scan</th>
        </tr>
      </thead>
      <tbody>
        {hosts.map((h) => (
          <tr
            key={h.instance_id}
            className="border-b border-line-soft last:border-0 hover:bg-surface-2"
          >
            <td className="truncate px-4 py-2.5 text-xs text-fg">
              {h.tags?.env ?? "—"}
            </td>
            <td className="truncate px-4 py-2.5 text-xs text-fg">
              {h.tags?.role ?? "—"}
            </td>
            <td className="truncate px-4 py-2.5">
              <Link
                href={`/fim/${encodeURIComponent(h.instance_id)}`}
                className="font-mono text-xs text-fg transition-colors hover:text-signal"
              >
                {h.instance_id}
              </Link>
            </td>
            <td className="truncate px-4 py-2.5 text-xs text-fg-muted">
              {h.hostname ?? "—"}
            </td>
            <td className="px-4 py-2.5 text-right font-mono text-xs text-fg-muted">
              {h.files_tracked}
            </td>
            <td className="px-4 py-2.5 text-right font-mono text-xs text-fg-muted">
              {h.paths_configured}
            </td>
            <td className="px-4 py-2.5">
              <StatusPill
                ok={h.inotify_active}
                onLabel={`${h.inotify_watch_count} watches`}
                offLabel="inactive"
              />
            </td>
            <td className="px-4 py-2.5">
              <StatusPill
                ok={h.auditd_active}
                onLabel="auditd live"
                offLabel="not loaded"
              />
            </td>
            <td className="px-4 py-2.5">
              <LastScanCell value={h.last_full_scan_at} stale={h.stale} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </ResizableTable>
  );
}

function StatusPill({
  ok,
  onLabel,
  offLabel,
}: {
  ok: boolean;
  onLabel: string;
  offLabel: string;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        className={clsx(
          "h-1.5 w-1.5 rounded-full",
          ok ? "bg-sev-resolved" : "bg-sev-medium",
        )}
        aria-hidden
      />
      <span className={clsx(ok ? "text-fg-muted" : "text-fg")}>
        {ok ? onLabel : offLabel}
      </span>
    </span>
  );
}

function LastScanCell({
  value,
  stale,
}: {
  value: string | null;
  stale: boolean;
}) {
  if (!value) {
    return <span className="font-mono text-xs text-fg-disabled">—</span>;
  }
  const age = (Date.now() - new Date(value).getTime()) / 1000;
  return (
    <span className="font-mono text-xs">
      <span className="text-fg-muted">{humanAge(age)}</span>
      {stale && (
        <span className="ml-1.5 text-[10px] uppercase tracking-wider text-sev-medium">
          stale
        </span>
      )}
    </span>
  );
}

// =========================================================================
// recent changes (cross-host)
// =========================================================================

function ChangesTable({ changes }: { changes: FimChangeWithInstance[] }) {
  return (
    <ResizableTable tableId="fim-recent-changes">
    <table className="w-full table-fixed text-sm">
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-32 px-4 py-2 text-left font-normal">Time</th>
          <th className="w-24 px-4 py-2 text-left font-normal">Detected</th>
          <th className="w-24 px-4 py-2 text-left font-normal">Change</th>
          <th className="w-36 px-4 py-2 text-left font-normal">Host</th>
          <th className="px-4 py-2 text-left font-normal">Path</th>
          <th className="w-44 px-4 py-2 text-left font-normal">Who</th>
        </tr>
      </thead>
      <tbody>
        {changes.map((c, i) => (
          <tr
            key={c.event_id ?? `${c.instance_id}-${c.path}-${i}`}
            className="border-b border-line-soft last:border-0 hover:bg-surface-2"
          >
            <td className="px-4 py-2.5">
              {c.changed_at ? (
                <TimestampCell value={c.changed_at} />
              ) : (
                <span className="text-xs text-fg-disabled">—</span>
              )}
            </td>
            <td className="px-4 py-2.5">
              <DetectionPill detection={c.detection} />
            </td>
            <td className="px-4 py-2.5">
              <ChangeTypePill type={c.change_type} />
            </td>
            <td className="truncate px-4 py-2.5">
              <Link
                href={`/fim/${encodeURIComponent(c.instance_id)}`}
                className="font-mono text-xs text-fg-muted transition-colors hover:text-signal"
              >
                {c.instance_id}
              </Link>
            </td>
            <td className="truncate px-4 py-2.5">
              {c.event_id ? (
                <Link
                  href={`/events/${c.event_id}`}
                  className="font-mono text-xs text-fg transition-colors hover:text-signal"
                >
                  {c.path}
                </Link>
              ) : (
                <span className="font-mono text-xs text-fg">{c.path}</span>
              )}
            </td>
            <td className="truncate px-4 py-2.5">
              <ActorCell change={c} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </ResizableTable>
  );
}

function DetectionPill({
  detection,
}: {
  detection: "baseline" | "inotify" | "auditd" | null;
}) {
  if (detection === "inotify") {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span className="h-1.5 w-1.5 rounded-full bg-signal" aria-hidden />
        <span className="text-fg">real-time</span>
      </span>
    );
  }
  if (detection === "auditd") {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-fg-muted">
        <span className="h-1.5 w-1.5 rounded-full bg-sev-medium" aria-hidden />
        auditd
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-fg-muted">
      <span className="h-1.5 w-1.5 rounded-full bg-fg-disabled" aria-hidden />
      baseline
    </span>
  );
}

function ChangeTypePill({
  type,
}: {
  type: FimChangeWithInstance["change_type"];
}) {
  const COLOR: Record<typeof type, string> = {
    created: "bg-sev-medium",
    modified: "bg-sev-high",
    deleted: "bg-sev-medium",
    perm_changed: "bg-sev-medium",
    owner_changed: "bg-sev-medium",
  };
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className={clsx("h-1.5 w-1.5 rounded-full", COLOR[type])} aria-hidden />
      <span className="text-fg-muted">{type.replace("_", " ")}</span>
    </span>
  );
}

function ActorCell({ change }: { change: FimChangeWithInstance }) {
  if (change.actor_comm == null && change.actor_uid == null) {
    return <span className="text-xs text-fg-disabled">—</span>;
  }
  const comm = change.actor_comm ?? "?";
  const uid = change.actor_uid != null ? `uid=${change.actor_uid}` : null;
  return (
    <span
      className="text-xs text-fg"
      title={
        change.actor_proctitle ??
        [comm, uid, change.actor_pid != null ? `pid=${change.actor_pid}` : null]
          .filter(Boolean)
          .join(" · ")
      }
    >
      <span className="font-mono">{comm}</span>
      {uid && <span className="ml-1.5 text-fg-muted">{uid}</span>}
    </span>
  );
}

// =========================================================================
// helpers
// =========================================================================

function humanAge(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-6 py-12 text-center text-sm text-fg-muted">
      {children}
    </div>
  );
}
