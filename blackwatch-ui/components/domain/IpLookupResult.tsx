import clsx from "clsx";
import { ExternalLink } from "lucide-react";

import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { KeyValueRow } from "@/components/layout/KeyValueRow";
import type {
  IpIndicator,
  IpLookupResponse,
  ProviderResult,
} from "@/lib/ip-intelligence";

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
        <div className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          {result.query === query ? "Resolved IP" : "Looked up"}
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
  const indicators = result.indicators ?? [];
  const events = result.observedEvents ?? [];
  return (
    <section className={clsx("space-y-2", compact && "mt-1")}>
      <SectionLabel>intelligence sources</SectionLabel>
      <DataPanel className={compact ? "px-4 py-3" : undefined}>
        <div className="grid gap-2 md:grid-cols-2">
          {providers.map((provider) => (
            <ProviderCard key={provider.id} provider={provider} />
          ))}
        </div>
        {result.investigationMessage && (
          <p className="mt-3 border-t border-line-soft pt-3 text-xs text-fg-muted">
            {result.investigationMessage}
          </p>
        )}
      </DataPanel>

      {(indicators.length > 0 || events.length > 0) && (
        <>
          <SectionLabel>investigation trail</SectionLabel>
          <DataPanel className={compact ? "px-4 py-3" : undefined}>
            {indicators.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {indicators.map((indicator) => (
                  <IndicatorPill key={`${indicator.kind}:${indicator.value}`} indicator={indicator} />
                ))}
              </div>
            )}
            {events.length > 0 && (
              <div className={clsx("space-y-2", indicators.length > 0 && "mt-4 border-t border-line-soft pt-3")}>
                <div className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
                  matching BlackWatch events
                </div>
                {events.slice(0, compact ? 4 : 12).map((event) => (
                  <div key={event.eventId} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs">
                    <a href={`/events/${encodeURIComponent(event.eventId)}`} className="font-mono text-signal hover:underline">
                      {event.action}
                    </a>
                    <span className="text-fg-muted">{event.summary}</span>
                    <span className="font-mono text-[10px] text-fg-subtle">{event.module}</span>
                  </div>
                ))}
              </div>
            )}
          </DataPanel>
        </>
      )}
    </section>
  );
}

function ProviderCard({ provider }: { provider: ProviderResult }) {
  const status = {
    success: { label: "available", dot: "bg-sev-low", text: "text-sev-low" },
    not_configured: { label: "optional", dot: "bg-fg-subtle", text: "text-fg-muted" },
    rate_limited: { label: "rate limited", dot: "bg-sev-medium", text: "text-sev-medium" },
    error: { label: "unavailable", dot: "bg-sev-critical", text: "text-sev-critical" },
  }[provider.status];
  const details = [provider.reputation, provider.classification]
    .filter((value): value is string => !!value);
  const timing = [
    provider.firstSeen ? `first seen: ${provider.firstSeen}` : null,
    provider.lastSeen ? `last seen: ${provider.lastSeen}` : null,
    provider.asn ? `AS${provider.asn}` : null,
    provider.organization,
  ].filter((value): value is string => !!value);
  return (
    <div className="border border-line-soft px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-fg">{provider.label}</span>
        <span className={clsx("inline-flex items-center gap-1 text-[10px] uppercase tracking-wider", status.text)}>
          <span aria-hidden className={clsx("h-1.5 w-1.5 rounded-full", status.dot)} />
          {status.label}
        </span>
      </div>
      {details.length > 0 && <div className="mt-1 text-xs text-fg-muted">{details.join(" · ")}</div>}
      {timing.length > 0 && <div className="mt-1 text-[11px] text-fg-subtle">{timing.join(" · ")}</div>}
      {provider.confidence !== null && provider.confidence !== undefined && (
        <div className="mt-1 text-[11px] text-fg-subtle">confidence: {provider.confidence}%</div>
      )}
      {provider.message && <div className="mt-1 text-[11px] text-fg-subtle">{provider.message}</div>}
      <a
        href={provider.source}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-1 inline-flex items-center gap-1 text-[10px] text-signal hover:underline"
      >
        source <ExternalLink size={9} />
      </a>
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
    <span className="inline-flex max-w-full items-center gap-1 border border-line-soft bg-surface-2 px-2 py-1 text-[10px] text-fg-muted">
      <span className="uppercase text-fg-subtle">{indicator.kind}</span>
      <span className="max-w-64 truncate font-mono">{indicator.value}</span>
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
