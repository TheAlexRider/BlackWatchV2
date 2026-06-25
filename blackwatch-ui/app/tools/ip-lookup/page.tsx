import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import {
  IpLookupResult,
  type IpApiResponse,
} from "@/components/domain/IpLookupResult";

// Uses ip-api.com via the local /api/tools/ip-lookup route handler so the
// same code path serves both the modal and the standalone page.
async function lookup(ip: string): Promise<IpApiResponse | null> {
  try {
    const base = process.env.BW_PUBLIC_BASE_URL ?? "http://localhost:3000";
    const res = await fetch(
      `${base}/api/tools/ip-lookup?ip=${encodeURIComponent(ip)}`,
      { cache: "no-store" },
    );
    if (!res.ok) {
      const j = (await res.json().catch(() => null)) as IpApiResponse | null;
      return j ?? { status: "fail", message: `HTTP ${res.status}` };
    }
    return (await res.json()) as IpApiResponse;
  } catch (exc) {
    return { status: "fail", message: String(exc) };
  }
}

type SearchParams = { ip?: string };

export default async function IpLookupPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { ip } = await searchParams;
  const result = ip ? await lookup(ip.trim()) : null;

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
        title="IP lookup"
        subtitle="Geolocation, ISP, ASN, reverse DNS, proxy/hosting flags. Data from ip-api.com."
      />

      <form
        action="/tools/ip-lookup"
        method="GET"
        className="mb-6 flex items-center gap-2"
      >
        <Input
          name="ip"
          mono
          defaultValue={ip ?? ""}
          placeholder="8.8.8.8  or  example.com"
          className="w-80"
          autoFocus
        />
        <Button type="submit" variant="primary" size="sm">
          Lookup
        </Button>
        {ip && (
          <Link
            href="/tools/ip-lookup"
            className="ml-1 text-xs text-fg-muted hover:text-fg"
          >
            clear
          </Link>
        )}
      </form>

      {result && <IpLookupResult query={ip ?? ""} result={result} />}
    </>
  );
}
