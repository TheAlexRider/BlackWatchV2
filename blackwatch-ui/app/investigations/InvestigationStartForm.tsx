"use client";

import { useState, useTransition } from "react";
import { ArrowRight, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { investigationDetailHref } from "@/lib/investigation-flow";

export function InvestigationStartForm({
  initialIp = "",
}: {
  initialIp?: string;
}) {
  const [ip, setIp] = useState(initialIp);
  const [error, setError] = useState<string | null>(null);
  const [busy, startTransition] = useTransition();

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = ip.trim();
    if (!value) {
      setError("Enter an IPv4 or IPv6 address to start an investigation.");
      return;
    }

    setError(null);
    startTransition(async () => {
      try {
        const response = await fetch("/api/investigations", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ip: value }),
        });
        const body = (await response.json().catch(() => ({}))) as {
          id?: string;
          detail?: string;
        };
        if (!response.ok || !body.id) {
          setError(body.detail ?? "Could not start the investigation.");
          return;
        }
        window.location.assign(investigationDetailHref(body.id));
      } catch {
        setError("Could not reach BlackWatch. Try again.");
      }
    });
  }

  return (
    <form onSubmit={submit} className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-start">
      <div className="min-w-0 sm:w-64">
        <label htmlFor="investigation-ip" className="sr-only">
          IP address to investigate
        </label>
        <Input
          id="investigation-ip"
          name="ip"
          value={ip}
          onChange={(event) => setIp(event.target.value)}
          placeholder="IP address to investigate"
          mono
          disabled={busy}
          aria-describedby={error ? "investigation-ip-error" : undefined}
        />
        {error && (
          <p id="investigation-ip-error" className="mt-1 text-[11px] text-sev-critical">
            {error}
          </p>
        )}
      </div>
      <Button type="submit" variant="primary" size="sm" disabled={busy}>
        {busy ? <Loader2 size={13} className="animate-spin" aria-hidden /> : <ArrowRight size={13} aria-hidden />}
        {busy ? "Starting…" : "Investigate IP"}
      </Button>
    </form>
  );
}
