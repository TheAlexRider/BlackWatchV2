"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import * as Dialog from "@radix-ui/react-dialog";
import { X, ExternalLink, Loader2 } from "lucide-react";

import {
  IpLookupResult,
  type IpApiResponse,
} from "./IpLookupResult";

interface IpLookupModalProps {
  ip: string | null;
  onClose: () => void;
}

// Opens an in-page IP lookup. No navigation, no page transition. Fetches via
// the Next.js /api/tools/ip-lookup route (which aggregates the fast lookup
// and optional threat-intelligence sources).
export function IpLookupModal({ ip, onClose }: IpLookupModalProps) {
  const open = !!ip;
  const [result, setResult] = useState<IpApiResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ip) {
      setResult(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setResult(null);
    fetch(`/api/tools/ip-lookup?ip=${encodeURIComponent(ip)}`, {
      cache: "no-store",
    })
      .then(async (res) => {
        const data = (await res.json()) as IpApiResponse;
        if (!cancelled) setResult(data);
      })
      .catch((exc) => {
        if (!cancelled) setError(String(exc));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ip]);

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-[2px]" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-[min(900px,95vw)] max-h-[90vh] -translate-x-1/2 -translate-y-1/2 overflow-y-auto overscroll-contain border border-line bg-canvas shadow-2xl"
          aria-describedby={undefined}
        >
          <div className="flex items-center justify-between border-b border-line-soft px-5 py-3">
            <Dialog.Title className="font-mono text-xs uppercase tracking-[0.08em] text-fg-subtle">
              IP lookup · {ip}
            </Dialog.Title>
            <div className="flex items-center gap-3">
              {ip && (
                <Link
                  href={`/tools/ip-lookup?ip=${encodeURIComponent(ip)}`}
                  className="inline-flex items-center gap-1 text-[11px] text-fg-muted hover:text-fg"
                  onClick={onClose}
                >
                  open full page <ExternalLink size={10} />
                </Link>
              )}
              <Dialog.Close asChild>
                <button
                  type="button"
                  aria-label="Close"
                  className="text-fg-subtle transition-colors hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal"
                >
                  <X size={14} />
                </button>
              </Dialog.Close>
            </div>
          </div>

          <div className="p-5">
            {loading && (
              <div className="flex items-center gap-2 py-6 text-sm text-fg-muted">
                <Loader2 size={14} className="animate-spin" />
                Looking up…
              </div>
            )}
            {error && !loading && (
              <div role="alert" aria-live="assertive" className="border border-sev-critical/40 bg-sev-critical/5 px-4 py-3 text-sm text-sev-critical">
                {error}
              </div>
            )}
            {result && !loading && (
              <IpLookupResult query={ip ?? ""} result={result} compact />
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
