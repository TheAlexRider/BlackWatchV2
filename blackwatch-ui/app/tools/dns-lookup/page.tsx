import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { DnsLookupResult } from "@/components/domain/DnsLookupResult";
import type { DnsLookupResponse } from "@/app/api/tools/dns-lookup/route";

// Uses Node's built-in dns/promises via our local /api/tools/dns-lookup route
// handler. Same-origin so this page can be SSR'd and shared with any future
// modal-based use.
async function lookup(host: string): Promise<DnsLookupResponse | null> {
  try {
    const base = process.env.BW_PUBLIC_BASE_URL ?? "http://localhost:3000";
    const res = await fetch(
      `${base}/api/tools/dns-lookup?host=${encodeURIComponent(host)}`,
      { cache: "no-store" },
    );
    if (!res.ok) {
      const j = (await res.json().catch(() => null)) as DnsLookupResponse | null;
      return (
        j ?? {
          status: "fail",
          query: host,
          records: [],
          message: `HTTP ${res.status}`,
        }
      );
    }
    return (await res.json()) as DnsLookupResponse;
  } catch (exc) {
    return { status: "fail", query: host, records: [], message: String(exc) };
  }
}

type SearchParams = { host?: string };

export default async function DnsLookupPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { host } = await searchParams;
  const result = host ? await lookup(host.trim()) : null;

  return (
    <>
      <div className="mb-4">
        <Link
          href="/tools"
          className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft size={12} /> back to tools
        </Link>
      </div>

      <PageHeader
        title="DNS lookup"
        subtitle="A, AAAA, MX, TXT, CNAME, NS, SOA — all in one pass. Resolved by the local Node resolver."
      />

      <form
        action="/tools/dns-lookup"
        method="GET"
        className="mb-6 flex items-center gap-2"
      >
        <Input
          name="host"
          mono
          defaultValue={host ?? ""}
          placeholder="example.com"
          className="w-80"
          autoFocus
        />
        <Button type="submit" variant="primary" size="sm">
          Lookup
        </Button>
        {host && (
          <Link
            href="/tools/dns-lookup"
            className="ml-1 text-xs text-fg-muted hover:text-fg"
          >
            clear
          </Link>
        )}
      </form>

      {result && <DnsLookupResult result={result} />}
    </>
  );
}
