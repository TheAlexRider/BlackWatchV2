import Link from "next/link";
import clsx from "clsx";
import { ArrowLeft } from "lucide-react";

import { fetchFimInstance } from "@/lib/api";
import type {
  FimChange,
  FimCoverage,
  FimPathSummary,
  FimStrayBaseline,
} from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { TimestampCell } from "@/components/domain/TimestampCell";

export default async function FimInstancePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const data = await fetchFimInstance(id);

  return (
    <>
      <AutoRefresh intervalMs={15_000} />
      <div className="mb-4">
        <Link
          href="/fim"
          className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft size={12} /> back to FIM
        </Link>
      </div>

      <PageHeader
        title={id}
        subtitle={
          data.coverage
            ? `${data.coverage.files_tracked} files tracked · ${data.coverage.paths_configured} paths configured`
            : "no coverage data yet"
        }
      />

      <CoverageSection coverage={data.coverage} />

      <PathsSection
        summary={data.paths_summary}
        instanceId={id}
      />

      {data.stray_count > 0 && (
        <StraySection
          stray={data.stray_baselines}
          count={data.stray_count}
        />
      )}

      <RecentChangesSection changes={data.recent_changes} />

      <ConfigurationHelpSection instanceId={id} />
    </>
  );
}

// =========================================================================
// coverage card
// =========================================================================

function CoverageSection({ coverage }: { coverage: FimCoverage | null }) {
  if (!coverage) {
    return (
      <section className="mt-6 space-y-2">
        <SectionLabel>coverage</SectionLabel>
        <DataPanel className="px-6 py-10 text-center text-sm text-fg-muted">
          Agent hasn&apos;t reported coverage data yet. Wait ~15 seconds after
          install for the first heartbeat.
        </DataPanel>
      </section>
    );
  }

  const lastScan = coverage.last_full_scan_at
    ? new Date(coverage.last_full_scan_at)
    : null;
  const lastScanAge = lastScan
    ? humanAge((Date.now() - lastScan.getTime()) / 1000)
    : "—";

  const realtime = coverage.inotify_active;
  const whodata = coverage.auditd_active;
  const realtimeValue = realtime
    ? `${coverage.inotify_watch_count} watches · sub-second`
    : "inactive";
  const whodataValue = whodata
    ? "auditd active · actor attribution on"
    : "inactive";

  return (
    <section className="mt-6 space-y-2">
      <SectionLabel>coverage</SectionLabel>
      <DataPanel className="space-y-3 px-4 py-3">
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-5">
          <Stat
            label="Real-time (inotify)"
            value={realtimeValue}
            tone={realtime ? "ok" : "warn"}
          />
          <Stat
            label="Whodata (auditd)"
            value={whodataValue}
            tone={whodata ? "ok" : "warn"}
          />
          <Stat label="Files tracked" value={String(coverage.files_tracked)} />
          <Stat label="Last full scan" value={lastScanAge} />
          <Stat
            label="Scan errors"
            value={String(coverage.scan_errors)}
            tone={coverage.scan_errors > 0 ? "warn" : undefined}
          />
        </div>
      </DataPanel>
    </section>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "warn" | "ok";
}) {
  return (
    <div className="space-y-0.5">
      <div className="text-[10px] uppercase tracking-[0.08em] text-fg-subtle">
        {label}
      </div>
      <div
        className={clsx(
          "font-mono text-sm",
          tone === "warn"
            ? "text-sev-medium"
            : tone === "ok"
            ? "text-sev-resolved"
            : "text-fg",
        )}
      >
        {value}
      </div>
    </div>
  );
}

// =========================================================================
// configured paths — grouped table with file counts
// =========================================================================

function PathsSection({
  summary,
  instanceId: _instanceId,
}: {
  summary: FimPathSummary[];
  instanceId: string;
}) {
  // Group by category for visual clarity. The API returns them in order
  // already, but we re-group so headers can render between blocks.
  const byCategory = new Map<string, FimPathSummary[]>();
  for (const p of summary) {
    if (!byCategory.has(p.category)) byCategory.set(p.category, []);
    byCategory.get(p.category)!.push(p);
  }

  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>monitored paths</SectionLabel>
        <span className="text-[11px] text-fg-subtle">
          file counts pulled live from the agent&apos;s baseline DB
        </span>
      </div>
      <DataPanel className="overflow-hidden">
        {summary.length === 0 ? (
          <div className="px-6 py-10 text-center text-sm text-fg-muted">
            No path summary available — coverage hasn&apos;t been reported yet.
          </div>
        ) : (
          <Table>
            <thead>
              <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
                <th className="w-44 px-4 py-2 text-left font-normal">Category</th>
                <th className="px-4 py-2 text-left font-normal">Path</th>
                <th className="w-28 px-4 py-2 text-right font-normal">Files</th>
                <th className="w-32 px-4 py-2 text-right font-normal">Total size</th>
              </tr>
            </thead>
            <tbody>
              {summary.map((p, i) => {
                const isFirstInCategory =
                  i === 0 || summary[i - 1].category !== p.category;
                return (
                  <tr
                    key={`${p.category}-${p.path}`}
                    className="border-b border-line-soft last:border-0 hover:bg-surface-2"
                  >
                    <td className="px-4 py-2.5 text-xs text-fg-muted">
                      {isFirstInCategory ? p.category_label : ""}
                    </td>
                    <td className="truncate px-4 py-2.5 font-mono text-xs text-fg">
                      {p.path}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-fg">
                      {p.file_count}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-fg-muted">
                      {formatBytes(p.total_size_bytes)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </DataPanel>
    </section>
  );
}

// =========================================================================
// stray baselines (in baseline DB but not under any configured path)
// =========================================================================

function StraySection({
  stray,
  count,
}: {
  stray: FimStrayBaseline[];
  count: number;
}) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>stray baselines · not under a configured path</SectionLabel>
        <span className="text-[11px] text-fg-subtle">
          {count} file{count === 1 ? "" : "s"}
          {count > stray.length && ` · showing first ${stray.length}`}
        </span>
      </div>
      <DataPanel className="overflow-hidden">
        <p className="px-4 pt-3 pb-2 text-xs text-fg-muted">
          These files were baselined under a path that&apos;s no longer in the
          agent&apos;s configuration. Usually means a path was removed from the
          config but the agent hasn&apos;t been restarted to clean up. The
          next periodic scan will detect deletions for files outside the
          current scan scope.
        </p>
        <Table>
          <thead>
            <tr className="border-y border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="px-4 py-2 text-left font-normal">Path</th>
              <th className="w-24 px-4 py-2 text-right font-normal">Size</th>
              <th className="w-20 px-4 py-2 text-right font-normal">Perm</th>
            </tr>
          </thead>
          <tbody>
            {stray.map((s) => (
              <tr
                key={s.path}
                className="border-b border-line-soft last:border-0 hover:bg-surface-2"
              >
                <td className="truncate px-4 py-2.5 font-mono text-xs text-fg">
                  {s.path}
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-xs text-fg-muted">
                  {formatBytes(s.size)}
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-xs text-fg-muted">
                  {s.perm.toString(8).padStart(4, "0")}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </DataPanel>
    </section>
  );
}

// =========================================================================
// recent changes (per-instance) — same shape as the global table
// =========================================================================

function RecentChangesSection({ changes }: { changes: FimChange[] }) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>recent file integrity events</SectionLabel>
        <span className="text-[11px] text-fg-subtle">
          last {changes.length} change{changes.length === 1 ? "" : "s"}
        </span>
      </div>
      <DataPanel className="overflow-hidden">
        {changes.length === 0 ? (
          <div className="px-6 py-10 text-center text-sm text-fg-muted">
            No file integrity events for this instance yet.
          </div>
        ) : (
          <ChangesTable changes={changes} />
        )}
      </DataPanel>
    </section>
  );
}

function ChangesTable({ changes }: { changes: FimChange[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-32 px-4 py-2 text-left font-normal">Time</th>
          <th className="w-24 px-4 py-2 text-left font-normal">Detected</th>
          <th className="w-24 px-4 py-2 text-left font-normal">Change</th>
          <th className="px-4 py-2 text-left font-normal">Path</th>
          <th className="w-44 px-4 py-2 text-left font-normal">Who</th>
          <th className="w-44 px-4 py-2 text-left font-normal">Diff</th>
        </tr>
      </thead>
      <tbody>
        {changes.map((c, i) => (
          <tr
            key={c.event_id ?? `${c.path}-${i}`}
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
            <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
              <DiffCell change={c} />
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function DetectionPill({
  detection,
}: {
  detection: FimChange["detection"];
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

function ChangeTypePill({ type }: { type: FimChange["change_type"] }) {
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

function ActorCell({ change }: { change: FimChange }) {
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

function DiffCell({ change }: { change: FimChange }) {
  if (change.change_type === "perm_changed") {
    return (
      <span>
        perm {toOctal(change.perm_before)} → {toOctal(change.perm_after)}
      </span>
    );
  }
  if (change.change_type === "owner_changed") {
    return (
      <span>
        {change.owner_before ?? "—"} → {change.owner_after ?? "—"}
      </span>
    );
  }
  if (change.change_type === "deleted") {
    return (
      <span>
        was {toOctal(change.perm_before)}, {change.size_before ?? 0} B
      </span>
    );
  }
  const before = change.sha256_before?.slice(0, 8) ?? "new";
  const after = change.sha256_after?.slice(0, 8) ?? "—";
  return <span>{before} → {after}</span>;
}

// =========================================================================
// Configuration / customization help
// =========================================================================

function ConfigurationHelpSection({ instanceId: _instanceId }: { instanceId: string }) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>configuration</SectionLabel>
        <span className="text-[11px] text-fg-subtle">
          live edit coming soon · today: env vars on the host
        </span>
      </div>
      <DataPanel className="space-y-3 px-4 py-4 text-xs text-fg-muted">
        <p className="text-fg">
          To add or remove monitored paths on this host today, edit the
          systemd unit&apos;s environment and restart the agent. Push-from-UI
          customization is planned for Phase 2 (SSM Parameter Store).
        </p>
        <div className="space-y-1 rounded border border-line-soft bg-surface-2 p-3 font-mono text-[11px]">
          <div className="text-fg-subtle">
            # on the host (root):
          </div>
          <div>sudo systemctl edit blackwatch-agent</div>
          <div className="text-fg-subtle"># add to [Service]:</div>
          <div>
            Environment=BLACKWATCH_FIM_EXTRA_FILES=/etc/redis/redis.conf,/etc/postgresql/postgresql.conf
          </div>
          <div>
            Environment=BLACKWATCH_FIM_EXTRA_DIRS=/etc/nginx,/etc/letsencrypt
          </div>
          <div className="text-fg-subtle"># then:</div>
          <div>sudo systemctl restart blackwatch-agent</div>
        </div>
        <p>
          Within ~15 seconds (first scan) the new paths appear in the
          &quot;Monitored paths&quot; table above with their file counts.
          Use the path summary above to verify the agent picked up your
          additions.
        </p>
      </DataPanel>
    </section>
  );
}

// =========================================================================
// helpers
// =========================================================================

function formatBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`;
  return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function toOctal(p: number | null): string {
  if (p === null) return "—";
  return p.toString(8).padStart(4, "0");
}

function humanAge(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}
