import Link from "next/link";
import { Globe, Network, ShieldCheck } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";

const TOOLS = [
  {
    href: "/tools/ip-lookup",
    title: "IP intelligence & lookup",
    blurb: "Geolocation, ISP, ASN, reverse DNS, and proxy/hosting classification for an IP.",
    icon: Globe,
  },
  {
    href: "/events",
    title: "Event threat intelligence",
    blurb: "Review Tor, Bogon, and threat-feed enrichment attached to ingested events.",
    icon: ShieldCheck,
  },
  {
    href: "/tools/dns-lookup",
    title: "DNS lookup",
    blurb: "A, AAAA, MX, TXT, CNAME, NS, SOA — and SPF/DMARC highlighting on TXT.",
    icon: Network,
  },
];

export default function ToolsPage() {
  return (
    <>
      <PageHeader
        title="Tools"
        subtitle="Look up an observable or review the intelligence attached to collected events."
      />
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {TOOLS.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            className="group flex flex-col gap-2 border border-line-soft bg-surface-1 px-4 py-4 transition-colors hover:border-line hover:bg-surface-2"
          >
            <div className="flex items-center gap-2">
              <t.icon
                size={14}
                strokeWidth={1.5}
                className="text-fg-subtle group-hover:text-signal"
              />
              <span className="text-sm text-fg">{t.title}</span>
            </div>
            <p className="text-xs text-fg-muted">{t.blurb}</p>
          </Link>
        ))}
      </div>
      <p className="mt-5 max-w-3xl text-xs leading-5 text-fg-subtle">
        IP lookup uses the configured lookup provider for network context. Tor,
        Bogon, and feed matches are shown from BlackWatch event enrichment when
        that evidence exists; they are not silently inferred from the lookup.
      </p>
    </>
  );
}
