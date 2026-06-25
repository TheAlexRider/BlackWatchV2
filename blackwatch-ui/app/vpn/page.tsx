import Link from "next/link";
import clsx from "clsx";

import { fetchVpn } from "@/lib/api";
import type {
  EventEnvelope,
  VpnCertificate,
  VpnClient,
  VpnServer,
} from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { AutoRefresh } from "@/components/layout/AutoRefresh";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { IpCell } from "@/components/domain/IpCell";
import { Button } from "@/components/ui/Button";
import { deleteVpnServerAction } from "./actions";

export default async function VpnPage() {
  const { servers, auth } = await fetchVpn();

  const activeCount = servers.filter((s) => s.active && !s.stale).length;
  const totalClients = servers.reduce((acc, s) => acc + s.client_count, 0);

  return (
    <>
      <AutoRefresh intervalMs={15_000} />

      <PageHeader
        title="VPN"
        subtitle={
          servers.length === 0
            ? "No VPN data yet."
            : `${activeCount}/${servers.length} server${servers.length === 1 ? "" : "s"} active · ${totalClients} client${totalClients === 1 ? "" : "s"} connected`
        }
      />

      {servers.length === 0 ? (
        <DataPanel className="px-6 py-12 text-center">
          <p className="text-sm text-fg-muted">
            No VPN data yet. Install the on-host agent (
            <code className="text-fg">deploy/vpn/</code>) and add the SQS
            connector with target module{" "}
            <code className="text-fg">vpn.openvpn</code>.
          </p>
        </DataPanel>
      ) : (
        <div className="space-y-6">
          {servers.map((s) => (
            <ServerPanel key={s.server} server={s} />
          ))}
        </div>
      )}

      <section className="mt-6 space-y-2">
        <SectionLabel>recent auth attempts</SectionLabel>
        <DataPanel className="overflow-hidden">
          {auth.length === 0 ? (
            <div className="px-6 py-10 text-center text-sm text-fg-muted">
              No auth attempts captured yet. Once anyone tries to log in to the
              VPN (success or failure), it appears here within a second or two.
            </div>
          ) : (
            <AuthTable rows={auth} />
          )}
        </DataPanel>
      </section>
    </>
  );
}

// =========================================================================
// per-server panel
// =========================================================================

function ServerPanel({ server: s }: { server: VpnServer }) {
  return (
    <section className="space-y-4">
      <div className="space-y-2">
        <div className="flex items-baseline justify-between">
          <div className="flex items-baseline gap-3">
            <SectionLabel>{s.server} · clients</SectionLabel>
            {s.stale && (
              <form action={deleteVpnServerAction} className="inline">
                <input type="hidden" name="server" value={s.server} />
                <Button
                  type="submit"
                  variant="ghost"
                  size="sm"
                  title={`Remove ${s.server} from the read model. Will reappear if an agent reports under this name again.`}
                  className="text-fg-subtle hover:text-sev-critical"
                >
                  remove
                </Button>
              </form>
            )}
          </div>
          <ServerStatusInline server={s} />
        </div>
        <DataPanel className="overflow-hidden">
          {s.clients.length === 0 ? (
            <div className="px-6 py-8 text-center text-sm text-fg-muted">
              No clients connected.
            </div>
          ) : (
            <ClientsTable clients={s.clients} />
          )}
        </DataPanel>
      </div>

      <CertsBlock server={s.server} certs={s.certs ?? []} />
    </section>
  );
}

// =========================================================================
// certs — the actual reason the cert/CRL watcher exists
// =========================================================================

function CertsBlock({
  server,
  certs,
}: {
  server: string;
  certs: VpnCertificate[];
}) {
  if (certs.length === 0) {
    return (
      <div className="space-y-2">
        <SectionLabel>{server} · certificates</SectionLabel>
        <DataPanel className="px-6 py-8 text-center text-sm text-fg-muted">
          Agent hasn&apos;t shipped a cert inventory yet. Upgrade the on-host
          agent to v0.4+ — once a heartbeat lands, this fills in.
        </DataPanel>
      </div>
    );
  }

  // Sort by days_remaining ascending — the most urgent rows ride at the top.
  // Errors (no days_remaining) get pushed to the bottom.
  const sorted = [...certs].sort((a, b) => {
    const ad = a.days_remaining ?? Number.POSITIVE_INFINITY;
    const bd = b.days_remaining ?? Number.POSITIVE_INFINITY;
    return ad - bd;
  });

  const counts = countByBand(certs);

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>
          {server} · certificates · {certs.length}{" "}
          {certs.length === 1 ? "entry" : "entries"}
        </SectionLabel>
        <span className="font-mono text-[11px] text-fg-subtle">
          {counts.expired > 0 && (
            <span className="mr-3 text-sev-critical">
              ● {counts.expired} expired
            </span>
          )}
          {counts.critical > 0 && (
            <span className="mr-3 text-sev-critical">
              ● {counts.critical} &lt;7d
            </span>
          )}
          {counts.high > 0 && (
            <span className="mr-3 text-sev-high">
              ● {counts.high} &lt;14d
            </span>
          )}
          {counts.warning > 0 && (
            <span className="mr-3 text-sev-medium">
              ● {counts.warning} &lt;30d
            </span>
          )}
          {counts.error > 0 && (
            <span className="mr-3 text-sev-medium">
              ● {counts.error} unreadable
            </span>
          )}
        </span>
      </div>
      <DataPanel className="overflow-hidden">
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              <th className="w-20 px-4 py-2 text-left font-normal">Source</th>
              <th className="w-24 px-4 py-2 text-left font-normal">Kind</th>
              <th className="w-56 px-4 py-2 text-left font-normal">Name</th>
              <th className="px-4 py-2 text-left font-normal">Subject / path</th>
              <th className="w-40 px-4 py-2 text-left font-normal">Not after</th>
              <th className="w-32 px-4 py-2 text-right font-normal">Days left</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((c) => (
              <CertRow key={`${c.source ?? "?"}-${c.kind}-${c.name}-${c.path ?? ""}`} cert={c} />
            ))}
          </tbody>
        </table>
      </DataPanel>
    </div>
  );
}

function CertRow({ cert }: { cert: VpnCertificate }) {
  const band = bandFor(cert);
  return (
    <tr className="group relative border-b border-line-soft last:border-0 hover:bg-surface-2">
      <td className="relative px-4 py-2.5">
        <span
          aria-hidden
          className={clsx(
            "pointer-events-none absolute left-0 top-0 h-full w-0.5",
            band.borderClass,
          )}
        />
        <SourcePill source={cert.source} />
      </td>
      <td className="px-4 py-2.5">
        <KindPill kind={cert.kind} revoked={cert.revoked} />
      </td>
      <td className="truncate px-4 py-2.5 font-mono text-xs text-fg">
        {cert.name}
      </td>
      <td className="truncate px-4 py-2.5 font-mono text-[11px] text-fg-muted" title={cert.path ?? ""}>
        {cert.error ? (
          <span className="text-sev-critical">{cert.error}</span>
        ) : (
          cert.subject ?? cert.path ?? "—"
        )}
      </td>
      <td className="px-4 py-2.5 font-mono text-[11px] text-fg-muted">
        {cert.not_after ? formatAbsolute(cert.not_after) : "—"}
      </td>
      <td
        className={clsx(
          "px-4 py-2.5 text-right font-mono text-xs tabular-nums",
          band.textClass,
        )}
      >
        {cert.days_remaining === null || cert.days_remaining === undefined
          ? "—"
          : `${cert.days_remaining.toFixed(1)}d`}
      </td>
    </tr>
  );
}

function SourcePill({ source }: { source?: string | null }) {
  const label = source ?? "?";
  const tone =
    source === "pki"
      ? "border-signal/30 text-signal"
      : source === "live"
        ? "border-line text-fg"
        : "border-line-soft text-fg-subtle";
  return (
    <span
      className={clsx(
        "inline-flex items-center border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
        tone,
      )}
      title={source === "pki" ? "easy-rsa source of truth" : source === "live" ? "what OpenVPN actually reads" : ""}
    >
      {label}
    </span>
  );
}

function KindPill({
  kind,
  revoked,
}: {
  kind: string;
  revoked?: boolean;
}) {
  const label = revoked ? "revoked" : kind;
  const tone =
    kind === "ca"
      ? "border-line text-fg"
      : kind === "server"
        ? "border-signal/40 text-signal"
        : kind === "crl"
          ? "border-line text-fg-muted"
          : revoked
            ? "border-line text-fg-disabled"
            : "border-line-soft text-fg-muted";
  return (
    <span
      className={clsx(
        "inline-flex items-center border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
        tone,
      )}
    >
      {label}
    </span>
  );
}

function bandFor(cert: VpnCertificate): {
  borderClass: string;
  textClass: string;
} {
  if (cert.error) {
    return { borderClass: "bg-sev-medium", textClass: "text-sev-medium" };
  }
  const d = cert.days_remaining;
  if (d == null) {
    return { borderClass: "bg-fg-subtle", textClass: "text-fg-disabled" };
  }
  if (d < 0) return { borderClass: "bg-sev-critical", textClass: "text-sev-critical" };
  if (d < 7) return { borderClass: "bg-sev-critical", textClass: "text-sev-critical" };
  if (d < 14) return { borderClass: "bg-sev-high", textClass: "text-sev-high" };
  if (d < 30) return { borderClass: "bg-sev-medium", textClass: "text-sev-medium" };
  return { borderClass: "bg-transparent", textClass: "text-fg-muted" };
}

function countByBand(certs: VpnCertificate[]) {
  const c = { expired: 0, critical: 0, high: 0, warning: 0, error: 0 };
  for (const cert of certs) {
    if (cert.error) {
      c.error++;
      continue;
    }
    const d = cert.days_remaining;
    if (d == null) continue;
    if (d < 0) c.expired++;
    else if (d < 7) c.critical++;
    else if (d < 14) c.high++;
    else if (d < 30) c.warning++;
  }
  return c;
}

function formatAbsolute(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    // YYYY-MM-DD HH:mm UTC — concise, tabular, time-zone-stable.
    return d.toISOString().slice(0, 16).replace("T", " ") + "Z";
  } catch {
    return iso;
  }
}

function ServerStatusInline({ server: s }: { server: VpnServer }) {
  const ok = s.active && !s.stale;
  return (
    <span className="flex items-center gap-2 font-mono text-[11px] text-fg-muted">
      <span
        aria-hidden
        className={clsx(
          "h-1.5 w-1.5 rounded-full",
          ok ? "bg-sev-resolved" : "bg-sev-critical",
        )}
      />
      <span className={ok ? "text-fg" : "text-sev-critical"}>
        {ok ? "active" : "down"}
      </span>
      {s.age_seconds !== null && (
        <>
          <span className="text-fg-subtle">·</span>
          <span className="text-fg-subtle">
            updated {s.age_seconds}s ago
          </span>
        </>
      )}
      {s.stale && (
        <span className="text-[10px] uppercase tracking-wider text-sev-medium">
          stale
        </span>
      )}
      <span className="text-fg-subtle">· {s.client_count} client{s.client_count === 1 ? "" : "s"}</span>
    </span>
  );
}

function ClientsTable({ clients }: { clients: VpnClient[] }) {
  return (
    <table className="w-full table-fixed text-sm">
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-44 px-4 py-2 text-left font-normal">Common name</th>
          <th className="w-32 px-4 py-2 text-left font-normal">User</th>
          <th className="w-40 px-4 py-2 text-left font-normal">Real IP</th>
          <th className="w-32 px-4 py-2 text-left font-normal">Virtual IP</th>
          <th className="w-40 px-4 py-2 text-left font-normal">Connected since</th>
          <th className="px-4 py-2 text-right font-normal">Bytes rx / tx</th>
        </tr>
      </thead>
      <tbody>
        {clients.map((c, i) => (
          <tr key={i} className="border-b border-line-soft last:border-0">
            <td className="truncate px-4 py-2 font-mono text-xs text-fg">
              {c.common_name ?? "—"}
            </td>
            <td className="truncate px-4 py-2 text-xs text-fg-muted">
              {c.username ?? "—"}
            </td>
            <td className="px-4 py-2 text-xs text-fg-muted">
              <IpCell value={c.real_ip} className="text-xs text-fg-muted" />
            </td>
            <td className="px-4 py-2 text-xs text-fg-muted">
              <IpCell value={c.virtual_address} className="text-xs text-fg-muted" />
            </td>
            <td className="truncate px-4 py-2 font-mono text-[11px] text-fg-subtle">
              {c.connected_since ?? "—"}
            </td>
            <td className="px-4 py-2 text-right font-mono text-[11px] text-fg-muted">
              {fmtBytes(c.bytes_received)} / {fmtBytes(c.bytes_sent)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// =========================================================================
// auth attempts
// =========================================================================

function AuthTable({ rows }: { rows: EventEnvelope[] }) {
  return (
    <table className="w-full table-fixed text-sm">
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-40 px-4 py-2 text-left font-normal">Time</th>
          <th className="w-24 px-4 py-2 text-left font-normal">Result</th>
          <th className="w-44 px-4 py-2 text-left font-normal">User</th>
          <th className="px-4 py-2 text-left font-normal">Source IP</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((a) => {
          const ok = a.outcome === "success";
          return (
            <tr
              key={a.event_id}
              className="border-b border-line-soft last:border-0 hover:bg-surface-2"
            >
              <td className="px-4 py-2">
                <TimestampCell value={a.event_time} />
              </td>
              <td className="px-4 py-2">
                <span className="inline-flex items-center gap-1.5 text-xs">
                  <span
                    aria-hidden
                    className={clsx(
                      "h-1.5 w-1.5 rounded-full",
                      ok ? "bg-sev-resolved" : "bg-sev-critical",
                    )}
                  />
                  <span className={clsx(ok ? "text-fg-muted" : "text-fg")}>
                    {ok ? "success" : "FAILED"}
                  </span>
                </span>
              </td>
              <td className="truncate px-4 py-2 text-xs text-fg">
                <Link
                  href={`/events/${a.event_id}`}
                  className="hover:text-signal"
                >
                  {a.actor?.principal ?? "—"}
                </Link>
              </td>
              <td className="px-4 py-2 text-xs">
                <IpCell
                  value={(a.actor as { source_ip?: string } | undefined)?.source_ip}
                  className="text-xs text-fg-muted"
                />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function fmtBytes(b: number | null | undefined): string {
  if (b == null) return "?";
  if (b < 1024) return `${b}B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)}KB`;
  if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)}MB`;
  return `${(b / 1024 / 1024 / 1024).toFixed(2)}GB`;
}
