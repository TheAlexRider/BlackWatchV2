import Link from "next/link";
import { Globe, Network } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";

const TOOLS = [
  {
    href: "/tools/ip-lookup",
    title: "IP lookup",
    blurb: "Geolocation, ISP, ASN, reverse DNS, and proxy/hosting flags for any IP.",
    icon: Globe,
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
        subtitle="Small utilities the operator reaches for. More land here as we need them."
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
    </>
  );
}
