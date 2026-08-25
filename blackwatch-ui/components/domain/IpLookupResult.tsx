import clsx from "clsx";
import Link from "next/link";
import { ExternalLink } from "lucide-react";

import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { KeyValueRow } from "@/components/layout/KeyValueRow";
import { StatusPill } from "@/components/ui/StatusPill";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { SeverityBadge } from "@/components/domain/SeverityBadge";
import type {
  IpIndicator,
  IpLookupResponse,
  ProviderResult,
} from "@/lib/ip-intelligence";
import {
  groupIndicators,
  providerEvidence,
  providerStatusPresentation,
} from "@/lib/ip-intelligence-presentation";
import { investigationStartHref } from "@/lib/investigation-flow";

// Shared result type — used both by the standalone /tools/ip-lookup server
// component and by the IpLookupModal client component.
export type IpApiResponse = IpLookupResponse;

export function IpLookupResult({
  query,
  result,
  compact = false,
}: {
  query: string;
  result: IpApiResponse;
  /** Tighter spacing for the modal variant. */
  compact?: boolean;
}) {
  if (result.status === "fail") {
    return (
      <DataPanel className="px-6 py-6">
        <div className="flex items-center gap-2 text-sm">
          <span className="h-1.5 w-1.5 rounded-full bg-sev-critical" aria-hidden />
          <span className="text-sev-critical">Lookup failed</span>
          <span className="text-fg-muted">
            ·{" "}
            <code className="font-mono text-xs text-fg">
              {result.message ?? "unknown error"}
            </code>
          </span>
        </div>
        <p className="mt-3 text-xs text-fg-subtle">
          Common reasons: invalid IP/hostname, private/reserved range (10.x,
          192.168.x, 172.16-31.x, 127.x), or rate-limited (45 lookups/min on
          the free tier).
        </p>
      </DataPanel>
    );
  }

  const flags: { label: string; on: boolean }[] = [
    { label: "mobile", on: !!result.mobile },
    { label: "proxy / vpn", on: !!result.proxy },
    { label: "hosting / dc", on: !!result.hosting },
  ];

  const hasCoords = result.lat !== undefined && result.lon !== undefined;
  const gap = compact ? "gap-3" : "gap-4";

  return (
    <div className={clsx("space-y-4", compact && "space-y-3")}>
      {/* Header — IP + reverse + flags */}
      <DataPanel className={clsx(compact ? "px-4 py-3" : "px-6 py-5")}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            {result.query === query ? "Resolved IP" : "Looked up"}
          </div>
          <Link
            href={investigationStartHref(result.query ?? query)}
            className="inline-flex items-center gap-1 border border-signal/40 px-2 py-1 text-[11px] text-signal transition-colors hover:bg-signal/10"
          >
            open as investigation <ExternalLink size={10} aria-hidden />
          </Link>
        </div>
        <div
          className={clsx(
            "mt-1 font-mono tabular-nums text-fg",
            compact ? "text-xl" : "text-3xl",
          )}
        >
          {result.query ?? query}
        </div>
        {result.reverse && (
          <div className="mt-1 font-mono text-xs text-fg-muted">
            ↳ {result.reverse}
          </div>
        )}
        {flags.some((f) => f.on) && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {flags
              .filter((f) => f.on)
              .map((f) => (
                <span
                  key={f.label}
                  className="inline-flex items-center gap-1.5 border border-sev-medium/40 bg-sev-medium/5 px-2 py-0.5 text-[11px] uppercase tracking-wider text-sev-medium"
                >
                  <span
                    aria-hidden
                    className="h-1.5 w-1.5 rounded-full bg-sev-medium"
                  />
                  {f.label}
                </span>
              ))}
          </div>
        )}
      </DataPanel>

      <IntelligencePanel result={result} compact={compact} />

      {/* Info + map — side by side. Map sits as a fixed-size square so it
          doesn't dominate. On narrow viewports we stack. */}
      <div
        className={clsx(
          "grid",
          gap,
          hasCoords ? "lg:grid-cols-[1fr_320px]" : "grid-cols-1",
        )}
      >
        <div className={clsx(compact ? "space-y-3" : "space-y-4")}>
          <section className="space-y-2">
            <SectionLabel>location</SectionLabel>
            <DataPanel>
              <dl>
                <KeyValueRow label="Country">
                  <span className="text-fg">
                    {result.country ?? "—"}
                    {result.countryCode && (
                      <span className="ml-2 font-mono text-xs text-fg-subtle">
                        {result.countryCode}
                      </span>
                    )}
                  </span>
                </KeyValueRow>
                <KeyValueRow label="Region">
                  <span className="text-fg">
                    {result.regionName ?? "—"}
                    {result.region && (
                      <span className="ml-2 font-mono text-xs text-fg-subtle">
                        {result.region}
                      </span>
                    )}
                  </span>
                </KeyValueRow>
                <KeyValueRow label="City">
                  <span className="text-fg">{result.city ?? "—"}</span>
                </KeyValueRow>
                <KeyValueRow label="Postal code">
                  <span className="font-mono text-xs text-fg-muted">
                    {result.zip || "—"}
                  </span>
                </KeyValueRow>
                {hasCoords && (
                  <KeyValueRow label="Coordinates">
                    <span className="font-mono text-xs">
                      <span className="text-fg">
                        {result.lat!.toFixed(4)}, {result.lon!.toFixed(4)}
                      </span>
                      <a
                        href={`https://www.openstreetmap.org/?mlat=${result.lat}&mlon=${result.lon}&zoom=10`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="ml-3 inline-flex items-center gap-1 text-signal hover:underline"
                      >
                        open map <ExternalLink size={10} />
                      </a>
                    </span>
                  </KeyValueRow>
                )}
                <KeyValueRow label="Timezone">
                  <span className="font-mono text-xs text-fg-muted">
                    {result.timezone ?? "—"}
                  </span>
                </KeyValueRow>
              </dl>
            </DataPanel>
          </section>

          <section className="space-y-2">
            <SectionLabel>network</SectionLabel>
            <DataPanel>
              <dl>
                <KeyValueRow label="ISP">
                  <span className="text-fg">{result.isp ?? "—"}</span>
                </KeyValueRow>
                <KeyValueRow label="Organization">
                  <span className="text-fg">{result.org || "—"}</span>
                </KeyValueRow>
                <KeyValueRow label="AS">
                  <span className="font-mono text-xs text-fg">{result.as ?? "—"}</span>
                </KeyValueRow>
                <KeyValueRow label="Reverse DNS">
                  <span className="font-mono text-xs text-fg">
                    {result.reverse || (
                      <span className="text-fg-disabled">no PTR record</span>
                    )}
                  </span>
                </KeyValueRow>
              </dl>
            </DataPanel>
          </section>

          <section className="space-y-2">
            <SectionLabel>classification</SectionLabel>
            <DataPanel>
              <dl>
                <KeyValueRow label="Mobile network">
                  <FlagPill on={!!result.mobile} />
                </KeyValueRow>
                <KeyValueRow label="Proxy / VPN">
                  <FlagPill on={!!result.proxy} />
                </KeyValueRow>
                <KeyValueRow label="Hosting / data center">
                  <FlagPill on={!!result.hosting} />
                </KeyValueRow>
              </dl>
            </DataPanel>
          </section>
        </div>

        {hasCoords && (
          <section className="space-y-2">
            <SectionLabel>map</SectionLabel>
            <MapEmbed lat={result.lat!} lon={result.lon!} />
          </section>
        )}
      </div>
    </div>
  );
}

function IntelligencePanel({
  result,
  compact,
}: {
  result: IpLookupResponse;
  compact: boolean;
}) {
  const providers = result.providers ?? [];
  const indicators = (result.indicators ?? []).filter((indicator) => indicator.kind !== "event");
  const events = result.observedEvents ?? [];
  const indicatorGroups = groupIndicators(indicators);
  return (
    <section className={clsx("space-y-4", compact && "mt-1 space-y-3")}>
      <section className="space-y-2">
        <div className="flex items-baseline justify-between gap-3">
          <SectionLabel>intelligence sources</SectionLabel>
          <span className="font-mono text-[10px] text-fg-subtle">
            {providers.length} checked
          </span>
        </div>
        <DataPanel className="overflow-hidden">
          <div className="divide-y divide-line-soft">
            {providers.map((provider) => (
              <ProviderRow key={provider.id} provider={provider} />
            ))}
          </div>
        </DataPanel>
        {result.investigationMessage && (
          <p className="text-xs text-fg-subtle">
            {result.investigationMessage}
          </p>
        )}
      </section>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <section className="space-y-2">
          <div className="flex items-baseline justify-between gap-3">
            <SectionLabel>related indicators</SectionLabel>
            <span className="font-mono text-[10px] text-fg-subtle">
              {indicators.length} found
            </span>
          </div>
          <DataPanel className="overflow-hidden">
            {indicatorGroups.length > 0 ? (
              <div className="divide-y divide-line-soft">
                {indicatorGroups.map((group) => (
                  <IndicatorGroupRow key={group.kind} label={group.label} indicators={group.items} />
                ))}
              </div>
            ) : (
              <EmptyTrail> No related domains, URLs, hashes, or certificates were found.</EmptyTrail>
            )}
          </DataPanel>
        </section>

        <section className="space-y-2">
          <div className="flex items-baseline justify-between gap-3">
            <SectionLabel>matching events</SectionLabel>
            <span className="font-mono text-[10px] text-fg-subtle">
              {events.length} found
            </span>
          </div>
          <DataPanel className="overflow-hidden">
            {events.length > 0 ? (
              <div className="divide-y divide-line-soft">
                {events.slice(0, compact ? 4 : 12).map((event) => (
                  <EventTrailRow key={event.eventId} event={event} />
                ))}
              </div>
            ) : (
              <EmptyTrail>No matching BlackWatch events were found for this IP.</EmptyTrail>
            )}
          </DataPanel>
        </section>
      </div>
    </section>
  );
}

function ProviderRow({ provider }: { provider: ProviderResult }) {
  const status = providerStatusPresentation(provider.status);
  const evidence = providerEvidence(provider);
  return (
    <div className="grid gap-3 px-4 py-3 md:grid-cols-[minmax(10rem,0.8fr)_minmax(0,2fr)_auto] md:items-center">
      <div className="min-w-0">
        <div className="truncate text-sm text-fg">{provider.label}</div>
        <StatusPill label={status.label} severity={status.severity} className="mt-1" />
      </div>
      <div className="min-w-0">
        {evidence.length > 0 ? (
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-muted">
            {evidence.map((line) => <span key={line}>{line}</span>)}
          </div>
        ) : (
          <span className="text-xs text-fg-subtle">{provider.message ?? "No provider output."}</span>
        )}
        {evidence.length > 0 && provider.message && (
          <div className="mt-1 text-[11px] text-fg-subtle">{provider.message}</div>
        )}
      </div>
      <a
        href={provider.source}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`Open ${provider.label} provenance`}
        title={`Open ${provider.label} provenance`}
        className="inline-flex h-7 w-7 items-center justify-center text-fg-subtle transition-colors hover:text-signal"
      >
        <ExternalLink size={12} />
      </a>
    </div>
  );
}

function IndicatorGroupRow({ label, indicators }: { label: string; indicators: IpIndicator[] }) {
  return (
    <div className="px-4 py-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="text-xs text-fg-muted">{label}</span>
        <span className="font-mono text-[10px] text-fg-subtle">{indicators.length}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {indicators.map((indicator) => (
          <IndicatorPill key={`${indicator.kind}:${indicator.value}`} indicator={indicator} />
        ))}
      </div>
    </div>
  );
}

function IndicatorPill({ indicator }: { indicator: IpIndicator }) {
  const isUrl = indicator.kind === "url";
  const href = isUrl
    ? indicator.value
    : indicator.kind === "domain"
      ? `https://${indicator.value}`
      : undefined;
  const content = (
    <span className="inline-flex max-w-full items-center gap-2 border border-line-soft bg-surface-2 px-2 py-1 text-[10px] text-fg-muted transition-colors hover:border-signal/50 hover:text-fg">
      <span className="max-w-64 truncate font-mono">{indicator.value}</span>
      {href && <ExternalLink size={9} className="shrink-0 text-fg-subtle" />}
    </span>
  );
  return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer" title={`${indicator.relation} · ${indicator.source}`}>
      {content}
    </a>
  ) : (
    <span title={`${indicator.relation} · ${indicator.source}`}>{content}</span>
  );
}

function EventTrailRow({ event }: { event: IpLookupResponse["observedEvents"][number] }) {
  return (
    <a
      href={`/events/${encodeURIComponent(event.eventId)}`}
      className="grid gap-2 px-4 py-3 transition-colors hover:bg-surface-2 md:grid-cols-[7rem_5.5rem_minmax(0,1fr)_8rem] md:items-start"
    >
      <span>{event.eventTime ? <TimestampCell value={event.eventTime} /> : <span className="font-mono text-xs text-fg-disabled">—</span>}</span>
      <SeverityBadge severity={event.severity} />
      <span className="min-w-0">
        <span className="block truncate font-mono text-xs text-fg">{event.action}</span>
        <span className="mt-1 block text-xs text-fg-muted">{event.summary}</span>
      </span>
      <span className="font-mono text-[10px] text-fg-subtle">{event.module}</span>
    </a>
  );
}

function EmptyTrail({ children }: { children: React.ReactNode }) {
  return <p className="px-4 py-5 text-xs text-fg-subtle">{children}</p>;
}

function FlagPill({ on }: { on: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        aria-hidden
        className={clsx(
          "h-1.5 w-1.5 rounded-full",
          on ? "bg-sev-medium" : "bg-fg-subtle",
        )}
      />
      <span className={on ? "text-fg" : "text-fg-subtle"}>
        {on ? "yes" : "no"}
      </span>
    </span>
  );
}

// Square map. 320x320 fits next to the info panels without dominating.
// OpenStreetMap embed iframe — free, no key, no JS dep.
function MapEmbed({ lat, lon }: { lat: number; lon: number }) {
  const span = 0.4;
  const bbox = [
    (lon - span).toFixed(4),
    (lat - span).toFixed(4),
    (lon + span).toFixed(4),
    (lat + span).toFixed(4),
  ].join("%2C");
  const src = `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat}%2C${lon}`;
  return (
    <div className="aspect-square w-full overflow-hidden border border-line-soft">
      <iframe
        src={src}
        title={`Map centered on ${lat}, ${lon}`}
        loading="lazy"
        referrerPolicy="no-referrer-when-downgrade"
        className="block h-full w-full"
        style={{ background: "var(--color-canvas)" }}
      />
    </div>
  );
}
