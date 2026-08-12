"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useTransition } from "react";
import type { InvestigationDetail, InvestigationResult, InvestigationStatus } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { IpCell } from "@/components/domain/IpCell";
import { formatStatus } from "./InvestigationList";

const STATUSES: InvestigationStatus[] = ["ready", "investigating", "contained", "confirmed_malicious", "confirmed_expected", "false_positive", "inconclusive", "closed"];
const PAGE_SIZE = 25;
type EvidenceSort = "time" | "category" | "module" | "severity";

export function InvestigationNotebook({ initial }: { initial: InvestigationDetail }) {
  const [data, setData] = useState(initial);
  const [note, setNote] = useState("");
  const [sort, setSort] = useState<EvidenceSort>("category");
  const [page, setPage] = useState(0);
  const [windowDays, setWindowDays] = useState(() => rangeDays(initial.time_start, initial.time_end));
  const [busy, startTransition] = useTransition();
  const [message, setMessage] = useState<string | null>(null);
  const ip = data.observables.find((value) => value.startsWith("ip:"))?.slice(3) ?? "";
  const scanning = data.scan?.status === "queued" || data.scan?.status === "running" || data.status === "investigating";

  useEffect(() => {
    if (!scanning) return;
    const timer = window.setInterval(async () => {
      const response = await fetch(`/api/investigations/${data.id}`, { credentials: "include", cache: "no-store" });
      if (response.ok) setData(await response.json());
    }, 1500);
    return () => window.clearInterval(timer);
  }, [data.id, scanning]);

  function request(path: string, init: RequestInit) {
    return fetch(`/api/investigations/${data.id}${path}`, { ...init, credentials: "include", headers: { "Content-Type": "application/json", ...(init.headers ?? {}) } });
  }

  function scan() {
    setMessage(null);
    startTransition(async () => {
      const response = await request("/scan", { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) { setMessage(body.detail ?? "Investigation scan failed"); return; }
      const refreshed = await fetch(`/api/investigations/${data.id}`, { credentials: "include", cache: "no-store" });
      if (refreshed.ok) setData(await refreshed.json());
      setMessage("Scan queued. This page will update as evidence is found.");
    });
  }

  function changeStatus(status: InvestigationStatus) {
    startTransition(async () => {
      const response = await request("/status", { method: "PATCH", body: JSON.stringify({ status }) });
      if (response.ok) { const updated = await response.json(); setData((current) => ({ ...current, ...updated })); }
    });
  }

  function changeWindow(days: number) {
    setWindowDays(days);
    const end = new Date();
    const start = new Date(end.getTime() - days * 86400000);
    startTransition(async () => {
      const response = await request("/range", { method: "PATCH", body: JSON.stringify({ time_start: start.toISOString(), time_end: end.toISOString() }) });
      if (response.ok) { const updated = await response.json(); setData((current) => ({ ...current, ...updated })); setPage(0); }
    });
  }

  function addNote() {
    if (!note.trim()) return;
    startTransition(async () => {
      const response = await request("/notes", { method: "POST", body: JSON.stringify({ body: note }) });
      if (response.ok) { const created = await response.json(); setData((current) => ({ ...current, notes: [created, ...current.notes] })); setNote(""); }
    });
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><Link href="/investigations" className="text-xs text-fg-muted hover:text-signal">← investigations</Link><h1 className="mt-3 text-2xl font-medium text-fg">{data.title}</h1><p className="mt-1 font-mono text-xs text-fg-subtle">{data.id}</p></div>
        <div className="flex flex-wrap items-center gap-2">
          <select value={data.status} onChange={(event) => changeStatus(event.target.value as InvestigationStatus)} className="h-8 border border-line bg-surface-1 px-2 text-xs text-fg" disabled={busy} aria-label="Investigation status">{STATUSES.map((status) => <option key={status} value={status}>{formatStatus(status)}</option>)}</select>
          <Button type="button" variant="primary" onClick={scan} disabled={busy || scanning || data.status === "closed"}>{scanning ? "Scanning…" : "Run investigation"}</Button>
        </div>
      </div>
      {message && <div role="status" className="border border-line-soft bg-surface-1 px-3 py-2 text-xs text-fg-muted">{message}</div>}
      {data.scan?.status === "failed" && <div role="alert" className="border border-red-500/40 bg-red-500/5 px-3 py-2 text-xs text-red-300">Scan failed: {data.scan.error ?? "unknown error"}</div>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <section className="min-w-0 space-y-4">
          <ActivityGraph results={data.results} />
          <EvidenceExplorer results={data.results} sort={sort} setSort={(value) => { setSort(value); setPage(0); }} page={page} setPage={setPage} />
        </section>
        <aside className="space-y-4">
          <DataPanel className="space-y-3 p-4"><SectionLabel>observable</SectionLabel><IpCell value={ip} className="text-sm text-fg" /><label className="block text-[10px] uppercase tracking-[0.12em] text-fg-subtle" htmlFor="investigation-window">timeline</label><select id="investigation-window" value={windowDays} onChange={(event) => changeWindow(Number(event.target.value))} className="h-9 w-full border border-line bg-surface-1 px-2 text-xs text-fg"><option value="1">Last 24 hours</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option><option value="365">Last year</option></select><div className="text-xs text-fg-muted">{new Date(data.time_start).toLocaleString()} → {new Date(data.time_end).toLocaleString()}</div></DataPanel>
          <DataPanel className="space-y-3 p-4"><SectionLabel>analyst notes</SectionLabel><textarea value={note} onChange={(event) => setNote(event.target.value)} rows={4} maxLength={10000} placeholder="Record what you checked and why…" className="w-full resize-y border border-line bg-surface-1 p-2 text-xs text-fg placeholder:text-fg-disabled focus-visible:border-signal focus-visible:outline-none" /><Button type="button" size="sm" onClick={addNote} disabled={busy || !note.trim()}>Add note</Button><div className="space-y-3">{data.notes.map((item) => <div key={item.id} className="border-t border-line-soft pt-2"><div className="text-[10px] text-fg-subtle">{item.author} · <TimestampCell value={item.created_at} /></div><p className="mt-1 whitespace-pre-wrap break-words text-xs text-fg-muted">{item.body}</p></div>)}</div></DataPanel>
        </aside>
      </div>
    </div>
  );
}

function EvidenceExplorer({ results, sort, setSort, page, setPage }: { results: InvestigationResult[]; sort: EvidenceSort; setSort: (value: EvidenceSort) => void; page: number; setPage: (value: number) => void }) {
  const sorted = useMemo(() => [...results].sort((a, b) => sort === "time" ? dateValue(b) - dateValue(a) : label(a, sort).localeCompare(label(b, sort))), [results, sort]);
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const visible = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const groups = sort === "time" ? [] : Array.from(new Map(visible.map((item) => [label(item, sort), [] as InvestigationResult[]])).keys()).map((key) => ({ key, items: visible.filter((item) => label(item, sort) === key) }));
  return <section className="space-y-2"><div className="flex flex-wrap items-center justify-between gap-3"><SectionLabel>related evidence · {results.length}</SectionLabel><label className="flex items-center gap-2 text-[10px] uppercase tracking-[0.12em] text-fg-subtle">sort by<select value={sort} onChange={(event) => setSort(event.target.value as EvidenceSort)} className="h-8 border border-line bg-surface-1 px-2 text-xs normal-case tracking-normal text-fg"><option value="category">Category</option><option value="time">Time</option><option value="module">Module</option><option value="severity">Severity</option></select></label></div><DataPanel className="overflow-hidden">{results.length === 0 ? <p className="px-4 py-10 text-center text-sm text-fg-muted">Run the investigation to search normalized events and projection tables.</p> : sort === "time" ? <EvidenceTable results={visible} /> : <div className="divide-y divide-line-soft">{groups.map((group) => <details key={group.key} open className="group"><summary className="cursor-pointer list-none border-b border-line-soft bg-surface-1 px-4 py-3 text-xs font-medium text-fg marker:hidden"><span className="mr-2 text-signal">▾</span>{group.key}<span className="ml-2 text-fg-subtle">{group.items.length}</span></summary><EvidenceTable results={group.items} /></details>)}</div>}<Pagination page={page} totalPages={totalPages} total={results.length} onPage={setPage} /></DataPanel></section>;
}

function EvidenceTable({ results }: { results: InvestigationResult[] }) {
  return <div className="overflow-x-auto"><table className="bw-table min-w-[760px] text-sm" aria-label="Related evidence"><thead><tr><th>Time</th><th>Source</th><th>Category</th><th>Match</th><th>Target</th><th>Details</th></tr></thead><tbody>{results.map((result, index) => { const event = result.event; return <tr key={`${result.event_id ?? result.source_label}-${index}`}><td><TimestampCell value={event.event_time ?? result.observed_at ?? ""} /></td><td className="font-mono text-xs text-signal">{result.source_label ?? event.source?.module ?? "unknown"}</td><td>{event.category ?? result.category ?? "—"}</td><td className="max-w-[18rem] break-words text-xs text-fg-muted">{result.match_reason}</td><td className="max-w-[18rem] break-words font-mono text-xs">{event.target?.id ?? event.target?.name ?? "—"}</td><td>{result.event_id ? <Link href={`/events/${result.event_id}`} className="text-xs text-signal hover:underline">open event</Link> : <span className="text-xs text-fg-subtle">projection</span>}</td></tr>; })}</tbody></table></div>;
}

function ActivityGraph({ results }: { results: InvestigationResult[] }) {
  const points = useMemo(() => { const counts = new Map<string, number>(); results.forEach((item) => { const value = item.event.event_time ?? item.observed_at; if (!value) return; const key = new Date(value).toISOString().slice(0, 10); counts.set(key, (counts.get(key) ?? 0) + 1); }); return Array.from(counts.entries()).sort(([a], [b]) => a.localeCompare(b)).slice(-14); }, [results]);
  const max = Math.max(1, ...points.map(([, count]) => count));
  return <DataPanel className="p-4"><div className="mb-3 flex items-center justify-between"><SectionLabel>activity · last 14 active days</SectionLabel><span className="text-xs text-fg-muted">{results.length} matches</span></div>{points.length === 0 ? <p className="text-xs text-fg-muted">Activity will appear after the first scan.</p> : <div className="flex h-24 items-end gap-1" role="img" aria-label="Evidence activity by day">{points.map(([day, count]) => <div key={day} className="flex min-w-0 flex-1 flex-col items-center gap-1"><span className="text-[10px] text-fg-subtle">{count}</span><div className="w-full max-w-8 bg-signal" style={{ height: `${Math.max(8, (count / max) * 64)}px` }} title={`${day}: ${count} matches`} /><span className="truncate text-[9px] text-fg-disabled">{day.slice(5)}</span></div>)}</div>}</DataPanel>;
}

function Pagination({ page, totalPages, total, onPage }: { page: number; totalPages: number; total: number; onPage: (value: number) => void }) { return <div className="flex items-center justify-between border-t border-line-soft px-4 py-3 text-xs text-fg-muted"><span>{total === 0 ? "0" : `${page * PAGE_SIZE + 1}–${Math.min((page + 1) * PAGE_SIZE, total)}`} of {total}</span><div className="flex items-center gap-2"><button type="button" className="border border-line px-2 py-1 disabled:cursor-not-allowed disabled:opacity-40" disabled={page === 0} onClick={() => onPage(page - 1)}>Previous</button><span>{page + 1} / {totalPages}</span><button type="button" className="border border-line px-2 py-1 disabled:cursor-not-allowed disabled:opacity-40" disabled={page >= totalPages - 1} onClick={() => onPage(page + 1)}>Next</button></div></div>; }

function label(result: InvestigationResult, sort: EvidenceSort) { const event = result.event; if (sort === "category") return String(event.category ?? result.category ?? "Uncategorized"); if (sort === "module") return String(result.source_label ?? event.source?.module ?? "Unknown source"); if (sort === "severity") return String(event.severity ?? "Unscored"); return String(event.event_time ?? result.observed_at ?? ""); }
function dateValue(result: InvestigationResult) { const value = result.event.event_time ?? result.observed_at; return value ? new Date(value).getTime() : 0; }
function rangeDays(start: string, end: string) { return Math.max(1, Math.min(365, Math.round((new Date(end).getTime() - new Date(start).getTime()) / 86400000))); }
