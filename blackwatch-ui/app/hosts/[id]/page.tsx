import Link from "next/link";
import clsx from "clsx";
import { ArrowLeft } from "lucide-react";

import { fetchHostDetail } from "@/lib/api";
import type {
  HostRecord,
  HostSnapshots,
  HostSession,
  EventEnvelope,
  FimCoverage,
  FimChange,
  FimConfiguredPaths,
} from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { KeyValueRow } from "@/components/layout/KeyValueRow";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { IpCell } from "@/components/domain/IpCell";
import {
  SeverityBadge,
  severityBorderBg,
} from "@/components/domain/SeverityBadge";

export default async function HostDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const data = await fetchHostDetail(id);
  const {
    host, snapshots, age_seconds, stale,
    auth_events, state_changes, alerts,
    fim_coverage, fim_recent_changes,
  } = data;

  return (
    <>
      <div className="mb-4">
        <Link
          href="/hosts"
          className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft size={12} /> back to hosts
        </Link>
      </div>

      <PageHeader
        title={id}
        subtitle={host?.hostname ?? "no hostname reported"}
      />

      {!host && (
        <DataPanel className="px-6 py-12 text-center text-sm text-fg-muted">
          No data for instance{" "}
          <code className="font-mono text-fg">{id}</code> yet. Has the agent
          ever reported?
        </DataPanel>
      )}

      {host && (
        <>
          <StatusSection host={host} ageSeconds={age_seconds} stale={stale} />

          {(host.extra?.active_sessions?.length ?? 0) > 0 && (
            <SessionsSection sessions={host.extra!.active_sessions!} />
          )}

          {alerts.length > 0 && (
            <AlertsSection alerts={alerts} />
          )}

          {(fim_coverage || fim_recent_changes.length > 0) && (
            <FimSection
              coverage={fim_coverage}
              changes={fim_recent_changes}
            />
          )}

          {(snapshots.disk?.length ?? 0) > 0 && (
            <DiskSection rows={snapshots.disk!} />
          )}

          <PortsSection rows={snapshots.ports ?? []} />

          {(snapshots.processes?.length ?? 0) > 0 && (
            <ProcessesSection rows={snapshots.processes!} />
          )}

          {(snapshots.users?.length ?? 0) > 0 && (
            <UsersSection rows={snapshots.users!} />
          )}

          {(snapshots.authorized_keys?.length ?? 0) > 0 && (
            <AuthorizedKeysSection rows={snapshots.authorized_keys!} />
          )}

          {snapshots.sudoers && Object.keys(snapshots.sudoers).length > 0 && (
            <FileHashSection
              title="sudoers files"
              data={snapshots.sudoers}
            />
          )}

          {snapshots.critical_files && Object.keys(snapshots.critical_files).length > 0 && (
            <FileHashSection
              title="critical files · FIM"
              data={snapshots.critical_files}
            />
          )}

          {snapshots.cron && Object.keys(snapshots.cron).length > 0 && (
            <FileHashSection title="cron files" data={snapshots.cron} />
          )}

          {(snapshots.systemd_units?.length ?? 0) > 0 && (
            <ScrollableList
              title="enabled systemd units"
              items={snapshots.systemd_units!}
            />
          )}

          {(snapshots.kernel_modules?.length ?? 0) > 0 && (
            <ScrollableList
              title="kernel modules"
              items={snapshots.kernel_modules!}
              columns={3}
            />
          )}

          {(snapshots.suid?.length ?? 0) > 0 && (
            <ScrollableList title="suid binaries" items={snapshots.suid!} />
          )}

          {(snapshots.packages?.length ?? 0) > 0 && (
            <ScrollableList
              title={`installed packages · showing first 100 of ${snapshots.packages!.length}`}
              items={snapshots.packages!.slice(0, 100)}
              columns={3}
            />
          )}

          {auth_events.length > 0 && (
            <EventsSection title="recent SSH / sudo" events={auth_events} />
          )}

          {state_changes.length > 0 && (
            <EventsSection title="recent state changes" events={state_changes} />
          )}
        </>
      )}
    </>
  );
}

// =========================================================================
// status
// =========================================================================

function StatusSection({
  host,
  ageSeconds,
  stale,
}: {
  host: HostRecord;
  ageSeconds: number | null;
  stale: boolean;
}) {
  const extra = host.extra ?? {};
  const reporting = host.active && !stale;
  const memory = extra.memory;
  const cpu = extra.cpu;
  const cpuAnomaly = extra._state?.cpu_anomaly_active === true;
  const baselineN = extra._baseline_cpu?.n ?? 0;

  return (
    <section className="space-y-2">
      <SectionLabel>status</SectionLabel>
      <DataPanel>
        <dl>
          <KeyValueRow label="Agent">
            <span className="inline-flex items-center gap-2">
              <span
                aria-hidden
                className={clsx(
                  "h-1.5 w-1.5 rounded-full",
                  reporting ? "bg-sev-resolved" : "bg-sev-critical",
                )}
              />
              <span className={clsx(reporting ? "text-fg" : "text-sev-critical")}>
                {reporting ? "reporting" : "stale / down"}
              </span>
            </span>
          </KeyValueRow>
          <KeyValueRow label="Last seen">
            {ageSeconds === null ? (
              <span className="text-fg-disabled">—</span>
            ) : (
              <span className="font-mono text-xs">
                <span className="text-fg-muted">{ageSeconds}s ago</span>
                {stale && (
                  <span className="ml-2 text-[10px] uppercase tracking-wider text-sev-medium">
                    stale
                  </span>
                )}
              </span>
            )}
          </KeyValueRow>
          <KeyValueRow label="Hostname">
            <span className="font-mono text-xs text-fg">{host.hostname ?? "—"}</span>
          </KeyValueRow>
          <KeyValueRow label="Account">
            <span className="font-mono text-xs text-fg-muted">{host.account ?? "—"}</span>
          </KeyValueRow>
          <KeyValueRow label="Region">
            <span className="font-mono text-xs text-fg-muted">{host.region ?? "—"}</span>
          </KeyValueRow>
          {extra.uptime_seconds != null && (
            <KeyValueRow label="Uptime">
              <span className="font-mono text-xs text-fg-muted">
                {extra.uptime_seconds}s
              </span>
            </KeyValueRow>
          )}
          {extra.agent_version && (
            <KeyValueRow label="Agent version">
              <span className="font-mono text-xs text-fg-muted">
                {extra.agent_version}
              </span>
            </KeyValueRow>
          )}
          {memory && memory.used_pct != null && (
            <KeyValueRow label="Memory">
              <span className="inline-flex items-baseline gap-2">
                <span className={clsx("font-mono", memoryColor(memory.used_pct))}>
                  {memory.used_pct}%
                </span>
                <span className="text-[11px] text-fg-subtle">
                  · {kbToMib(memory.used_kb)} / {kbToMib(memory.total_kb)} MiB
                </span>
              </span>
            </KeyValueRow>
          )}
          {cpu && (
            <KeyValueRow label="CPU load">
              <div className="space-y-1">
                <div className="font-mono text-xs">
                  <span className="text-fg">{cpu.load_1min}</span>
                  <span className="text-fg-subtle"> (1m) · </span>
                  <span className="text-fg">{cpu.load_5min}</span>
                  <span className="text-fg-subtle">
                    {" "}
                    (5m) · {cpu.cpu_count} CPUs · normalized {cpu.load_norm_1min}
                  </span>
                </div>
                {cpuAnomaly && (
                  <div className="inline-flex items-center gap-1.5 text-xs text-sev-critical">
                    <span
                      aria-hidden
                      className="h-1.5 w-1.5 rounded-full bg-sev-critical"
                    />
                    anomaly active
                  </div>
                )}
                {!cpuAnomaly && baselineN >= 60 && extra._baseline_cpu && (
                  <div className="text-[11px] text-fg-subtle">
                    baseline mean {extra._baseline_cpu.mean.toFixed(3)} ({baselineN}{" "}
                    samples)
                  </div>
                )}
              </div>
            </KeyValueRow>
          )}
          {extra.rpm_db_corrupted && (
            <KeyValueRow label="Package DB">
              <div className="space-y-1">
                <div className="inline-flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className="h-1.5 w-1.5 rounded-full bg-sev-critical"
                  />
                  <span className="text-sev-critical">CORRUPTED</span>
                  <span className="text-[11px] text-fg-subtle">
                    · {extra.rpm_db_corrupted.lock_count} stale lock file(s)
                  </span>
                </div>
                <div className="text-[11px] text-fg-subtle">
                  Fix:{" "}
                  <code className="text-fg">
                    sudo rm -f /var/lib/rpm/__db.* &amp;&amp; sudo rpm
                    --rebuilddb
                  </code>
                </div>
              </div>
            </KeyValueRow>
          )}
          {extra.tick_duration_ms != null && (
            <KeyValueRow label="Last tick">
              <span className="font-mono text-xs text-fg-muted">
                {extra.tick_duration_ms}ms
              </span>
            </KeyValueRow>
          )}
          {extra.tags && Object.keys(extra.tags).length > 0 && (
            <KeyValueRow label="Tags">
              <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-xs">
                {Object.entries(extra.tags).map(([k, v]) => (
                  <code key={k} className="text-fg-muted">
                    {k}={v}
                  </code>
                ))}
              </div>
            </KeyValueRow>
          )}
          {extra.collector_errors && Object.keys(extra.collector_errors).length > 0 && (
            <KeyValueRow label="Collector errors">
              <div className="space-y-1">
                {Object.entries(extra.collector_errors).map(([name, err]) => (
                  <div key={name} className="text-xs text-sev-critical">
                    <span className="font-mono">{name}</span>: {err}
                  </div>
                ))}
              </div>
            </KeyValueRow>
          )}
          {(extra.stalled_collectors?.length ?? 0) > 0 && (
            <KeyValueRow label="Stalled collectors">
              <div className="space-y-1">
                <div className="flex flex-wrap gap-1.5">
                  {extra.stalled_collectors!.map((name) => (
                    <span
                      key={name}
                      className="inline-flex items-center gap-1.5 border border-line px-1.5 py-0.5 font-mono text-[11px] text-fg"
                    >
                      <span
                        aria-hidden
                        className="h-1.5 w-1.5 rounded-full bg-sev-medium"
                      />
                      {name}
                    </span>
                  ))}
                </div>
                <div className="text-[11px] text-fg-subtle">
                  no successful run in 3× their interval
                </div>
              </div>
            </KeyValueRow>
          )}
        </dl>
      </DataPanel>
    </section>
  );
}

// =========================================================================
// sessions
// =========================================================================

function SessionsSection({ sessions }: { sessions: HostSession[] }) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>currently logged in</SectionLabel>
        <span className="text-[11px] text-fg-subtle">
          {sessions.length} session{sessions.length === 1 ? "" : "s"}
        </span>
      </div>
      <DataPanel className="overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="w-32 px-4 py-2 text-left font-normal">User</th>
              <th className="w-24 px-4 py-2 text-left font-normal">TTY</th>
              <th className="w-44 px-4 py-2 text-left font-normal">Source IP</th>
              <th className="px-4 py-2 text-left font-normal">Login</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s, i) => (
              <tr
                key={`${s.user}-${s.tty}-${i}`}
                className="border-b border-line-soft last:border-0"
              >
                <td className="px-4 py-2 text-fg">{s.user}</td>
                <td className="px-4 py-2 font-mono text-xs text-fg-muted">{s.tty}</td>
                <td className="px-4 py-2 text-xs">
                  {s.source ? (
                    <IpCell value={s.source} className="text-xs text-fg" />
                  ) : (
                    <span className="text-fg-subtle">local</span>
                  )}
                </td>
                <td className="px-4 py-2 font-mono text-xs text-fg-muted">
                  {s.login}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataPanel>
    </section>
  );
}

// =========================================================================
// alerts
// =========================================================================

function AlertsSection({ alerts }: { alerts: EventEnvelope[] }) {
  return (
    <section className="mt-6 space-y-2">
      <SectionLabel>recent notable activity · high / critical</SectionLabel>
      <DataPanel className="overflow-hidden">
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="w-40 px-4 py-2 text-left font-normal">Time</th>
              <th className="w-24 px-4 py-2 text-left font-normal">Severity</th>
              <th className="px-4 py-2 text-left font-normal">Action</th>
              <th className="w-48 px-4 py-2 text-left font-normal">Actor</th>
            </tr>
          </thead>
          <tbody>
            {alerts.map((a) => (
              <tr
                key={a.event_id}
                className="group relative border-b border-line-soft last:border-0 hover:bg-surface-2"
              >
                <td className="relative px-4 py-2.5">
                  <span
                    aria-hidden
                    className={clsx(
                      "pointer-events-none absolute left-0 top-0 h-full w-0.5",
                      severityBorderBg(a.severity as string | null | undefined),
                    )}
                  />
                  <TimestampCell value={a.event_time} />
                </td>
                <td className="px-4 py-2.5">
                  <SeverityBadge severity={(a.severity as string) ?? null} />
                </td>
                <td className="truncate px-4 py-2.5">
                  <Link
                    href={`/events/${a.event_id}`}
                    className="font-mono text-xs text-fg transition-colors hover:text-signal"
                  >
                    {a.action}
                  </Link>
                </td>
                <td className="truncate px-4 py-2.5 text-xs text-fg-muted">
                  {a.actor?.principal ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataPanel>
    </section>
  );
}

// =========================================================================
// File Integrity Monitoring (FIM)  — Part 1: periodic baseline
// =========================================================================

function FimSection({
  coverage,
  changes,
}: {
  coverage: FimCoverage | null;
  changes: FimChange[];
}) {
  const realtime = coverage?.inotify_active ?? false;
  const whodata = coverage?.auditd_active ?? false;
  let subtitle: string;
  if (realtime && whodata) {
    subtitle = "real-time · inotify + auditd whodata + 6h baseline scan";
  } else if (realtime) {
    subtitle = "real-time · inotify + 6h baseline scan (whodata off)";
  } else {
    subtitle = "periodic baseline · 6h scan (inotify inactive)";
  }

  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>file integrity</SectionLabel>
        <span className="text-[11px] text-fg-subtle">{subtitle}</span>
      </div>

      <FimCoverageCard coverage={coverage} />

      <DataPanel className="overflow-hidden">
        {changes.length === 0 ? (
          <div className="px-6 py-10 text-center text-sm text-fg-muted">
            No file integrity changes recorded. The agent will start emitting
            events once it detects drift from the established baseline.
          </div>
        ) : (
          <FimChangesTable changes={changes} />
        )}
      </DataPanel>

      {coverage?.configured_paths && (
        <FimWatchedPaths paths={coverage.configured_paths} />
      )}
    </section>
  );
}

function FimWatchedPaths({ paths }: { paths: FimConfiguredPaths }) {
  return (
    <DataPanel className="space-y-3 px-4 py-3 text-xs">
      <div className="text-[10px] uppercase tracking-[0.08em] text-fg-subtle">
        watched paths · what FIM is monitoring on this host
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <PathColumn label="Critical files" paths={paths.critical_files} />
        <PathColumn label="Critical directories" paths={paths.critical_dirs} />
        <PathColumn label="Binary directories" paths={paths.binary_dirs} />
      </div>
      <div className="border-t border-line-soft pt-2 text-[10px] text-fg-subtle">
        Real-time (inotify): files + critical directories · Periodic (6h):
        everything · Auditd whodata: write &amp; attribute changes
      </div>
    </DataPanel>
  );
}

function PathColumn({
  label,
  paths,
}: {
  label: string;
  paths: string[];
}) {
  return (
    <div>
      <div className="mb-1 text-[10px] uppercase tracking-[0.08em] text-fg-subtle">
        {label} <span className="text-fg-disabled">({paths.length})</span>
      </div>
      <ul className="space-y-0.5">
        {paths.map((p) => (
          <li key={p} className="font-mono text-[11px] text-fg-muted">
            {p}
          </li>
        ))}
      </ul>
    </div>
  );
}

function FimCoverageCard({ coverage }: { coverage: FimCoverage | null }) {
  if (!coverage) {
    return (
      <DataPanel className="px-4 py-3 text-xs text-fg-muted">
        Coverage data not reported yet. Agent will report after its first scan
        (~15 seconds after start, then every 6 hours).
      </DataPanel>
    );
  }
  const lastScan = coverage.last_full_scan_at
    ? new Date(coverage.last_full_scan_at)
    : null;
  const lastScanAge = lastScan
    ? humanAge((Date.now() - lastScan.getTime()) / 1000)
    : "—";

  // Real-time + whodata indicators are the two things an auditor / SRE wants
  // to see at a glance: "is detection live?" and "do we know who changed it?"
  const realtime = coverage.inotify_active;
  const whodata = coverage.auditd_active;
  const realtimeValue = realtime
    ? `${coverage.inotify_watch_count} paths · sub-second`
    : "inactive";
  const whodataValue = whodata
    ? "auditd active · actor attribution on"
    : "inactive";

  return (
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
      <div className="border-t border-line-soft pt-2 text-[10px] uppercase tracking-[0.08em] text-fg-subtle">
        Paths configured: <span className="text-fg-muted normal-case">{coverage.paths_configured}</span>
        {coverage.paths_inotify > 0 && (
          <>
            {" · "}real-time scope:{" "}
            <span className="text-fg-muted normal-case">{coverage.paths_inotify}</span>
          </>
        )}
        {coverage.paths_baseline_only > 0 && (
          <>
            {" · "}baseline-only:{" "}
            <span className="text-fg-muted normal-case">{coverage.paths_baseline_only}</span>
          </>
        )}
      </div>
    </DataPanel>
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

function FimChangesTable({ changes }: { changes: FimChange[] }) {
  return (
    <table className="w-full table-fixed text-sm">
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
              <TimestampCell value={c.changed_at} />
            </td>
            <td className="px-4 py-2.5">
              <FimDetectionPill detection={c.detection} />
            </td>
            <td className="px-4 py-2.5">
              <FimChangePill type={c.change_type} />
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
              <FimActorCell change={c} />
            </td>
            <td className="truncate px-4 py-2.5 font-mono text-xs text-fg-muted">
              <FimDiff change={c} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function FimActorCell({ change }: { change: FimChange }) {
  if (change.actor_comm == null && change.actor_uid == null) {
    return (
      <span className="text-xs text-fg-disabled">—</span>
    );
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
      {uid && (
        <span className="ml-1.5 text-fg-muted">{uid}</span>
      )}
    </span>
  );
}

function FimDetectionPill({
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
  // baseline or unknown (older rows pre-Part 2 won't have the field)
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-fg-muted">
      <span className="h-1.5 w-1.5 rounded-full bg-fg-disabled" aria-hidden />
      baseline
    </span>
  );
}

function FimChangePill({ type }: { type: FimChange["change_type"] }) {
  // Color encodes how alarming the change is at a glance. Modified content
  // (new sha256) is the most-actionable signal.
  const COLOR: Record<FimChange["change_type"], string> = {
    created:        "bg-sev-medium",
    modified:       "bg-sev-high",
    deleted:        "bg-sev-medium",
    perm_changed:   "bg-sev-medium",
    owner_changed:  "bg-sev-medium",
  };
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        className={clsx("h-1.5 w-1.5 rounded-full", COLOR[type])}
        aria-hidden
      />
      <span className="text-fg-muted">{type.replace("_", " ")}</span>
    </span>
  );
}

function FimDiff({ change }: { change: FimChange }) {
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
    return <span>was {toOctal(change.perm_before)}, {change.size_before ?? 0} B</span>;
  }
  // created or modified — show sha256 prefix diff. Full 64-char hash is in
  // the event detail; 8 chars is enough for at-a-glance distinction.
  const before = change.sha256_before?.slice(0, 8) ?? "new";
  const after = change.sha256_after?.slice(0, 8) ?? "—";
  return <span>{before} → {after}</span>;
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

// =========================================================================
// disk, ports, processes, users, keys
// =========================================================================

function DiskSection({
  rows,
}: {
  rows: NonNullable<HostSnapshots["disk"]>;
}) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>disk usage</SectionLabel>
        <span className="text-[11px] text-fg-subtle">
          {rows.length} mount{rows.length === 1 ? "" : "s"}
        </span>
      </div>
      <DataPanel className="overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="w-64 px-4 py-2 text-left font-normal">Mount</th>
              <th className="w-32 px-4 py-2 text-left font-normal">FS</th>
              <th className="w-24 px-4 py-2 text-left font-normal">Used %</th>
              <th className="px-4 py-2 text-left font-normal">Used / Total</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr
                key={d.mount}
                className="border-b border-line-soft last:border-0"
              >
                <td className="px-4 py-2 font-mono text-xs text-fg">{d.mount}</td>
                <td className="px-4 py-2 font-mono text-xs text-fg-muted">{d.fs_type}</td>
                <td className={clsx("px-4 py-2 font-mono text-xs", memoryColor(d.used_pct))}>
                  {d.used_pct}%
                </td>
                <td className="px-4 py-2 font-mono text-xs text-fg-muted">
                  {d.used} / {d.total} KB
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataPanel>
    </section>
  );
}

function PortsSection({
  rows,
}: {
  rows: NonNullable<HostSnapshots["ports"]>;
}) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>listening ports</SectionLabel>
        <span className="text-[11px] text-fg-subtle">{rows.length}</span>
      </div>
      <DataPanel className="overflow-hidden">
        {rows.length === 0 ? (
          <div className="px-6 py-8 text-center text-sm text-fg-muted">
            No port snapshot yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
                <th className="w-20 px-4 py-2 text-left font-normal">Proto</th>
                <th className="w-44 px-4 py-2 text-left font-normal">Address</th>
                <th className="w-24 px-4 py-2 text-left font-normal">Port</th>
                <th className="px-4 py-2 text-left font-normal">Process</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p, i) => (
                <tr
                  key={`${p.proto}-${p.port}-${i}`}
                  className="border-b border-line-soft last:border-0"
                >
                  <td className="px-4 py-2 font-mono text-xs text-fg-muted">{p.proto}</td>
                  <td className="px-4 py-2 font-mono text-xs text-fg-muted">{p.address}</td>
                  <td className="px-4 py-2 font-mono text-xs text-fg">{p.port}</td>
                  <td className="px-4 py-2 font-mono text-xs text-fg-muted">
                    {p.process ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </DataPanel>
    </section>
  );
}

function ProcessesSection({
  rows,
}: {
  rows: NonNullable<HostSnapshots["processes"]>;
}) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>running processes</SectionLabel>
        <span className="text-[11px] text-fg-subtle">{rows.length}</span>
      </div>
      <DataPanel className="max-h-[380px] overflow-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="sticky top-0 border-b border-line-soft bg-surface-1 text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="w-32 px-4 py-2 text-left font-normal">User</th>
              <th className="w-20 px-4 py-2 text-left font-normal">PID</th>
              <th className="w-44 px-4 py-2 text-left font-normal">Command</th>
              <th className="px-4 py-2 text-left font-normal">Args</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.pid} className="border-b border-line-soft last:border-0">
                <td className="px-4 py-1.5 font-mono text-xs text-fg-muted">{p.user}</td>
                <td className="px-4 py-1.5 font-mono text-xs text-fg-muted">{p.pid}</td>
                <td className="px-4 py-1.5 font-mono text-xs text-fg">{p.comm}</td>
                <td className="px-4 py-1.5 truncate font-mono text-[11px] text-fg-subtle">
                  {p.args}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataPanel>
    </section>
  );
}

function UsersSection({
  rows,
}: {
  rows: NonNullable<HostSnapshots["users"]>;
}) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>users</SectionLabel>
        <span className="text-[11px] text-fg-subtle">{rows.length}</span>
      </div>
      <DataPanel className="max-h-[280px] overflow-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="sticky top-0 border-b border-line-soft bg-surface-1 text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="w-44 px-4 py-2 text-left font-normal">Name</th>
              <th className="w-20 px-4 py-2 text-left font-normal">UID</th>
              <th className="px-4 py-2 text-left font-normal">Shell</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((u) => (
              <tr key={u.name} className="border-b border-line-soft last:border-0">
                <td className="px-4 py-1.5 text-xs text-fg">{u.name}</td>
                <td className="px-4 py-1.5 font-mono text-xs text-fg-muted">{u.uid}</td>
                <td className="px-4 py-1.5 font-mono text-xs text-fg-muted">{u.shell}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataPanel>
    </section>
  );
}

function AuthorizedKeysSection({
  rows,
}: {
  rows: NonNullable<HostSnapshots["authorized_keys"]>;
}) {
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>authorized SSH keys</SectionLabel>
        <span className="text-[11px] text-fg-subtle">{rows.length}</span>
      </div>
      <DataPanel className="overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="w-32 px-4 py-2 text-left font-normal">User</th>
              <th className="w-72 px-4 py-2 text-left font-normal">Fingerprint</th>
              <th className="px-4 py-2 text-left font-normal">Preview</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((k, i) => (
              <tr
                key={`${k.user}-${k.fingerprint}-${i}`}
                className="border-b border-line-soft last:border-0"
              >
                <td className="px-4 py-2 text-fg">{k.user}</td>
                <td className="px-4 py-2 font-mono text-[11px] text-fg-muted">
                  {k.fingerprint}
                </td>
                <td className="truncate px-4 py-2 font-mono text-[11px] text-fg-subtle">
                  {k.preview}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataPanel>
    </section>
  );
}

// =========================================================================
// generic file-hash table + scrollable mono list
// =========================================================================

function FileHashSection({
  title,
  data,
}: {
  title: string;
  data: Record<string, string>;
}) {
  const rows = Object.entries(data);
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>{title}</SectionLabel>
        <span className="text-[11px] text-fg-subtle">{rows.length}</span>
      </div>
      <DataPanel className="overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="px-4 py-2 text-left font-normal">Path</th>
              <th className="w-44 px-4 py-2 text-left font-normal">sha256</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([path, h]) => (
              <tr key={path} className="border-b border-line-soft last:border-0">
                <td className="truncate px-4 py-2 font-mono text-xs text-fg">{path}</td>
                <td className="px-4 py-2 font-mono text-[11px] text-fg-muted">
                  {h.slice(0, 16)}…
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataPanel>
    </section>
  );
}

function ScrollableList({
  title,
  items,
  columns = 1,
}: {
  title: string;
  items: string[];
  columns?: 1 | 2 | 3;
}) {
  const colClass =
    columns === 3 ? "columns-3" : columns === 2 ? "columns-2" : "columns-1";
  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>{title}</SectionLabel>
        <span className="text-[11px] text-fg-subtle">{items.length}</span>
      </div>
      <DataPanel className="max-h-[240px] overflow-auto p-4">
        <div className={clsx("gap-x-6 font-mono text-xs text-fg-muted", colClass)}>
          {items.map((item, i) => (
            <div key={i} className="break-all">
              {item}
            </div>
          ))}
        </div>
      </DataPanel>
    </section>
  );
}

// =========================================================================
// generic events table (used twice: SSH/sudo + state changes)
// =========================================================================

function EventsSection({
  title,
  events,
}: {
  title: string;
  events: EventEnvelope[];
}) {
  return (
    <section className="mt-6 space-y-2">
      <SectionLabel>{title}</SectionLabel>
      <DataPanel className="overflow-hidden">
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="w-40 px-4 py-2 text-left font-normal">Time</th>
              <th className="w-28 px-4 py-2 text-left font-normal">Severity</th>
              <th className="w-56 px-4 py-2 text-left font-normal">Action</th>
              <th className="px-4 py-2 text-left font-normal">Actor / Detail</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
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
                  <Link
                    href={`/events/${e.event_id}`}
                    className="font-mono text-xs text-fg transition-colors hover:text-signal"
                  >
                    {e.action}
                  </Link>
                </td>
                <td className="truncate px-4 py-2.5 text-xs text-fg-muted">
                  {e.actor?.principal ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataPanel>
    </section>
  );
}

// =========================================================================
// helpers
// =========================================================================

function memoryColor(pct: number): string {
  if (pct >= 95) return "text-sev-critical";
  if (pct >= 90) return "text-sev-medium";
  return "text-fg";
}

function kbToMib(kb: number | null | undefined): string {
  if (kb == null) return "—";
  return Math.round(kb / 1024).toString();
}
