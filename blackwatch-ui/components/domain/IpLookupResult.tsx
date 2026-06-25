import clsx from "clsx";
import { ExternalLink } from "lucide-react";

import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { KeyValueRow } from "@/components/layout/KeyValueRow";

// Shared result type — used both by the standalone /tools/ip-lookup server
// component and by the IpLookupModal client component.
export interface IpApiResponse {
  status: "success" | "fail";
  message?: string;
  query?: string;
  country?: string;
  countryCode?: string;
  region?: string;
  regionName?: string;
  city?: string;
  zip?: string;
  lat?: number;
  lon?: number;
  timezone?: string;
  isp?: string;
  org?: string;
  as?: string;
  asname?: string;
  reverse?: string;
  mobile?: boolean;
  proxy?: boolean;
  hosting?: boolean;
}

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
