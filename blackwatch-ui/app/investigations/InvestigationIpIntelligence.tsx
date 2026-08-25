"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import {
  IpLookupResult,
  type IpApiResponse,
} from "@/components/domain/IpLookupResult";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { investigationIpLookupHref } from "@/lib/investigation-flow";

export function InvestigationIpIntelligence({ ip }: { ip: string }) {
  const [result, setResult] = useState<IpApiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ip) return;
    let cancelled = false;
    setResult(null);
    setError(null);

    fetch(investigationIpLookupHref(ip), {
      credentials: "include",
      cache: "no-store",
    })
      .then(async (response) => {
        const body = (await response.json().catch(() => null)) as IpApiResponse | null;
        if (!response.ok) {
          throw new Error(body?.message ?? `IP intelligence failed: ${response.status}`);
        }
        if (!cancelled) setResult(body);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "IP intelligence failed");
      });

    return () => {
      cancelled = true;
    };
  }, [ip]);

  if (!ip) return null;

  return (
    <section className="space-y-2">
      <SectionLabel>automatic IP intelligence</SectionLabel>
      {error && (
        <div role="alert" className="border border-sev-critical/40 bg-sev-critical/5 px-4 py-3 text-xs text-sev-critical">
          {error}
        </div>
      )}
      {!result && !error && (
        <div className="flex items-center gap-2 border border-line-soft bg-surface-1 px-4 py-4 text-xs text-fg-muted">
          <Loader2 size={13} className="animate-spin" aria-hidden />
          Looking up provider intelligence for <span className="font-mono text-fg">{ip}</span>…
        </div>
      )}
      {result && <IpLookupResult query={ip} result={result} compact />}
    </section>
  );
}
