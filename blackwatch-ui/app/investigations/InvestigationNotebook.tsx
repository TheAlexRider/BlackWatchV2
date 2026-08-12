"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import type { InvestigationDetail, InvestigationStatus } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { IpCell } from "@/components/domain/IpCell";
import { formatStatus } from "./InvestigationList";

const STATUSES: InvestigationStatus[] = [
  "ready", "investigating", "contained", "confirmed_malicious",
  "confirmed_expected", "false_positive", "inconclusive", "closed",
];

export function InvestigationNotebook({ initial }: { initial: InvestigationDetail }) {
  const [data, setData] = useState(initial);
  const [note, setNote] = useState("");
  const [busy, startTransition] = useTransition();
  const [message, setMessage] = useState<string | null>(null);
  const ip = data.observables.find((value) => value.startsWith("ip:"))?.slice(3) ?? "";

  function request(path: string, init: RequestInit) {
    return fetch(`/api/investigations/${data.id}${path}`, {
      ...init,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    });
  }

  function scan() {
    setMessage(null);
    startTransition(async () => {
      const response = await request("/scan", { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) { setMessage(body.detail ?? "Investigation scan failed"); return; }
      const refreshed = await fetch(`/api/investigations/${data.id}`, { credentials: "include", cache: "no-store" });
      if (refreshed.ok) setData(await refreshed.json());
      setMessage(`Scan complete: ${body.result_count ?? 0} related events found.`);
    });
  }

  function changeStatus(status: InvestigationStatus) {
    startTransition(async () => {
      const response = await request("/status", { method: "PATCH", body: JSON.stringify({ status }) });
      if (response.ok) {
        const updated = await response.json();
        setData((current) => ({ ...current, ...updated }));
      }
    });
  }

  function addNote() {
    if (!note.trim()) return;
    startTransition(async () => {
      const response = await request("/notes", { method: "POST", body: JSON.stringify({ body: note }) });
      if (response.ok) {
        const created = await response.json();
        setData((current) => ({ ...current, notes: [created, ...current.notes] }));
        setNote("");
      }
    });
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link href="/investigations" className="text-xs text-fg-muted hover:text-signal">← investigations</Link>
          <h1 className="mt-3 text-2xl font-medium text-fg">{data.title}</h1>
          <p className="mt-1 font-mono text-xs text-fg-subtle">{data.id}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select value={data.status} onChange={(event) => changeStatus(event.target.value as InvestigationStatus)} className="h-8 border border-line bg-surface-1 px-2 text-xs text-fg" disabled={busy} aria-label="Investigation status">
            {STATUSES.map((status) => <option key={status} value={status}>{formatStatus(status)}</option>)}
          </select>
          <Button type="button" variant="primary" onClick={scan} disabled={busy || data.status === "closed"}>{busy ? "Scanning…" : "Run investigation"}</Button>
        </div>
      </div>

      {message && <div role="status" className="border border-line-soft bg-surface-1 px-3 py-2 text-xs text-fg-muted">{message}</div>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <section className="space-y-2">
          <SectionLabel>related evidence · {data.result_count}</SectionLabel>
          <DataPanel className="overflow-hidden">
            {data.results.length === 0 ? <p className="px-4 py-10 text-center text-sm text-fg-muted">Run the investigation to search BlackWatch events for this IP.</p> : (
              <div className="divide-y divide-line-soft">
                {data.results.map((result) => <EvidenceItem key={result.event_id} result={result} ip={ip} />)}
              </div>
            )}
          </DataPanel>
        </section>
        <aside className="space-y-4">
          <DataPanel className="space-y-3 p-4">
            <SectionLabel>observable</SectionLabel>
            <IpCell value={ip} className="text-sm text-fg" />
            <div className="text-xs text-fg-muted">{new Date(data.time_start).toLocaleString()} → {new Date(data.time_end).toLocaleString()}</div>
          </DataPanel>
          <DataPanel className="space-y-3 p-4">
            <SectionLabel>analyst notes</SectionLabel>
            <textarea value={note} onChange={(event) => setNote(event.target.value)} rows={4} maxLength={10000} placeholder="Record what you checked and why…" className="w-full resize-y border border-line bg-surface-1 p-2 text-xs text-fg placeholder:text-fg-disabled focus-visible:border-signal focus-visible:outline-none" />
            <Button type="button" size="sm" onClick={addNote} disabled={busy || !note.trim()}>Add note</Button>
            <div className="space-y-3">
              {data.notes.map((item) => <div key={item.id} className="border-t border-line-soft pt-2"><div className="text-[10px] text-fg-subtle">{item.author} · <TimestampCell value={item.created_at} /></div><p className="mt-1 whitespace-pre-wrap break-words text-xs text-fg-muted">{item.body}</p></div>)}
            </div>
          </DataPanel>
        </aside>
      </div>
    </div>
  );
}

function EvidenceItem({ result, ip }: { result: InvestigationDetail["results"][number]; ip: string }) {
  const event = result.event;
  const actorIp = event.actor?.source_ip;
  return (
    <article className="grid gap-2 px-4 py-3 md:grid-cols-[9rem_minmax(0,1fr)_10rem]">
      <TimestampCell value={event.event_time} />
      <div className="min-w-0 break-words">
        <div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs text-signal">{event.source?.module ?? "unknown"}</span><span className="font-mono text-xs text-fg">{event.action}</span></div>
        <div className="mt-1 break-words text-xs text-fg-muted">{event.target?.id ?? event.target?.name ?? "No target"}</div>
        <div className="mt-1 text-[10px] text-fg-subtle">Related because {actorIp === ip ? "actor.source_ip matches" : "the observable appears in event fields"} · {result.match_reason}</div>
      </div>
      <div className="text-right"><Link href={`/events/${result.event_id}`} className="text-xs text-signal hover:underline">open event</Link></div>
    </article>
  );
}
