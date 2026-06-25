// Next.js Route Handler — resolves DNS records using Node's built-in dns/promises.
// Same-origin endpoint so the standalone page (and any future modal) share one
// code path. No upstream API needed — Node ships its own resolver.

import { NextResponse } from "next/server";
import { promises as dns } from "node:dns";

// Record types we resolve in parallel for every query. The kitchen-sink approach
// is fine here — DNS lookups are fast and the operator wants everything in one
// view (especially TXT, where SPF / DMARC / verification records live).
const RECORD_TYPES = ["A", "AAAA", "CNAME", "MX", "TXT", "NS", "SOA"] as const;
type RecordType = (typeof RECORD_TYPES)[number];

type RecordResult =
  | { type: RecordType; ok: true; values: string[] }
  | { type: RecordType; ok: false; error: string };

export type DnsLookupResponse = {
  status: "ok" | "fail";
  query: string;
  records: RecordResult[];
  message?: string;
};

function resolveOne(host: string, type: RecordType): Promise<RecordResult> {
  // Each record type returns a different shape. Normalize them to string[] so
  // the UI can render them uniformly.
  return (async () => {
    try {
      switch (type) {
        case "A": {
          const v = await dns.resolve4(host);
          return { type, ok: true, values: v };
        }
        case "AAAA": {
          const v = await dns.resolve6(host);
          return { type, ok: true, values: v };
        }
        case "CNAME": {
          const v = await dns.resolveCname(host);
          return { type, ok: true, values: v };
        }
        case "NS": {
          const v = await dns.resolveNs(host);
          return { type, ok: true, values: v };
        }
        case "MX": {
          const v = await dns.resolveMx(host);
          return {
            type,
            ok: true,
            values: v
              .sort((a, b) => a.priority - b.priority)
              .map((m) => `${m.priority} ${m.exchange}`),
          };
        }
        case "TXT": {
          const v = await dns.resolveTxt(host);
          // TXT records can be chunked — join each chunk-array into a single string.
          return { type, ok: true, values: v.map((chunks) => chunks.join("")) };
        }
        case "SOA": {
          const v = await dns.resolveSoa(host);
          return {
            type,
            ok: true,
            values: [
              `${v.nsname} ${v.hostmaster} serial=${v.serial} refresh=${v.refresh} retry=${v.retry} expire=${v.expire} minttl=${v.minttl}`,
            ],
          };
        }
      }
    } catch (exc: unknown) {
      const code = (exc as NodeJS.ErrnoException)?.code ?? "";
      // ENODATA / ENOTFOUND are expected when a record type doesn't exist for
      // the host. Surface them quietly so the UI can grey them out instead of
      // looking like a failure.
      return { type, ok: false, error: code || String(exc) };
    }
  })();
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const raw = (searchParams.get("host") ?? "").trim().toLowerCase();
  if (!raw) {
    return NextResponse.json<DnsLookupResponse>(
      { status: "fail", query: "", records: [], message: "missing host query param" },
      { status: 400 },
    );
  }
  // Strip a scheme/path if the user pasted a URL, and any trailing dot.
  const host = raw
    .replace(/^https?:\/\//, "")
    .replace(/\/.*$/, "")
    .replace(/\.$/, "");

  try {
    const records = await Promise.all(RECORD_TYPES.map((t) => resolveOne(host, t)));
    return NextResponse.json<DnsLookupResponse>(
      { status: "ok", query: host, records },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (exc) {
    return NextResponse.json<DnsLookupResponse>(
      { status: "fail", query: host, records: [], message: String(exc) },
      { status: 502 },
    );
  }
}
