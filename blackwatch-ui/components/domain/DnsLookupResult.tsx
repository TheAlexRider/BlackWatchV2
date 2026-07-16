import type { DnsLookupResponse } from "@/app/api/tools/dns-lookup/route";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";

// Plain-English description of what each record type tells you. Surfaced as
// a one-line caption under each block so the operator doesn't need to remember
// what "SOA" stands for at 2am.
const RECORD_NOTE: Record<string, string> = {
  A: "IPv4 addresses the host resolves to.",
  AAAA: "IPv6 addresses the host resolves to.",
  CNAME: "Alias — the host is an alias for another name.",
  MX: "Mail servers · lower priority wins.",
  TXT: "Arbitrary text · SPF, DMARC, verification records live here.",
  NS: "Authoritative name servers for the zone.",
  SOA: "Start of Authority · zone metadata.",
};

// Some flags worth highlighting when we see them in TXT records — quick visual
// cue for SPF / DMARC presence which are the records security folks actually
// care about.
function txtAnnotation(value: string): string | null {
  const v = value.toLowerCase();
  if (v.startsWith("v=spf1")) return "SPF";
  if (v.startsWith("v=dmarc1")) return "DMARC";
  if (v.startsWith("v=dkim1")) return "DKIM";
  if (v.includes("google-site-verification")) return "Google verify";
  if (v.includes("ms=ms")) return "MS verify";
  if (v.includes("apple-domain")) return "Apple verify";
  if (v.includes("atlassian-domain")) return "Atlassian verify";
  return null;
}

export function DnsLookupResult({ result }: { result: DnsLookupResponse }) {
  if (result.status === "fail") {
    return (
      <DataPanel className="p-4">
        <p className="text-sm text-fg">
          DNS lookup failed{" "}
          {result.message && (
            <span className="text-fg-muted">· {result.message}</span>
          )}
        </p>
      </DataPanel>
    );
  }

  return (
    <div className="space-y-4">
      <p className="font-mono text-xs text-fg-subtle">
        resolved → <span className="text-fg-muted">{result.query}</span>
      </p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {result.records.map((r) => (
          <RecordBlock key={r.type} record={r} />
        ))}
      </div>
    </div>
  );
}

function RecordBlock({
  record,
}: {
  record: DnsLookupResponse["records"][number];
}) {
  const note = RECORD_NOTE[record.type] ?? "";
  return (
    <DataPanel className="overflow-hidden">
      <div className="flex items-baseline justify-between border-b border-line-soft px-3 py-2">
        <SectionLabel>{record.type}</SectionLabel>
        {!record.ok && (
          <span className="font-mono text-[10px] text-fg-disabled">
            {record.error}
          </span>
        )}
      </div>
      <div className="px-3 py-2.5">
        {record.ok ? (
          record.values.length === 0 ? (
            <p className="text-xs text-fg-disabled">no records</p>
          ) : (
            <ul className="space-y-1.5">
              {record.values.map((v, i) => (
                <li
                  key={`${record.type}-${i}`}
                  className="flex flex-wrap items-baseline gap-2"
                >
                  <code className="break-all font-mono text-xs text-fg">{v}</code>
                  {record.type === "TXT" && txtAnnotation(v) && (
                    <span className="border border-signal/40 bg-signal/10 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-signal">
                      {txtAnnotation(v)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )
        ) : (
          <p className="text-xs text-fg-disabled">none</p>
        )}
        {note && <p className="mt-2 text-[11px] text-fg-subtle">{note}</p>}
      </div>
    </DataPanel>
  );
}
