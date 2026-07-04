"use client";

import Link from "next/link";
import clsx from "clsx";
import { useActionState, useEffect, useState } from "react";
import { CheckCircle2, ExternalLink, Loader2, Pencil, Trash2, X, XCircle } from "lucide-react";

import type { Route, RoutesResponse, SeverityKey } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";

import {
  saveRouteAction,
  toggleRouteAction,
  silenceRouteAction,
  deleteRouteAction,
  testRouteAction,
  type RouteResult,
} from "./route-actions";

const SEVERITIES: Array<{ key: SeverityKey; label: string; className: string }> = [
  { key: "critical", label: "critical", className: "text-sev-critical" },
  { key: "high", label: "high", className: "text-sev-high" },
  { key: "medium", label: "medium", className: "text-sev-medium" },
  { key: "low", label: "low", className: "text-sev-low" },
  { key: "informational", label: "info", className: "text-fg-subtle" },
];

// Table row for one alert route. Two visual states — collapsed row inside a
// standard table row layout, and expanded inline editor that spans the row.
// Keeps consistent column geometry with the rest of the tables on the page.
export function RouteRow({
  route,
  module,
  channels,
  isCustom,
}: {
  route: Route;
  module: string;
  channels: RoutesResponse["channels"];
  isCustom: boolean;
}) {
  const [open, setOpen] = useState(false);
  const stateInfo = computeState(route);

  return (
    <>
      <tr
        className="border-b border-line-soft last:border-0 hover:bg-surface-2"
        onClick={() => setOpen((v) => !v)}
        role="button"
        aria-expanded={open}
        style={{ cursor: "pointer" }}
      >
        <td className="w-[240px] px-4 py-2 align-middle">
          <SeverityChips severities={route.severities} isCustom={isCustom} match={route.match} />
        </td>
        <td className="w-[220px] px-4 py-2 align-middle font-mono text-xs text-fg-muted">
          {route.channel ? (
            <>
              <span className="text-fg-subtle">→ </span>
              {route.channel}
            </>
          ) : (
            <span className="text-fg-subtle">—</span>
          )}
        </td>
        <td className="w-[100px] px-4 py-2 align-middle">
          <span className={clsx("text-xs", stateInfo.className)}>
            {stateInfo.label}
          </span>
        </td>
        <td className="px-4 py-2 text-right align-middle">
          <span className="text-fg-subtle">{open ? <X size={12} /> : "⋮"}</span>
        </td>
      </tr>
      {open && (
        <tr className="border-b border-line-soft last:border-0 bg-surface-1">
          <td colSpan={4} className="px-4 py-3">
            <RouteEditor
              route={route}
              module={module}
              channels={channels}
              isCustom={isCustom}
              onClose={() => setOpen(false)}
            />
          </td>
        </tr>
      )}
    </>
  );
}

// The blank "+ add route" row that appears at the bottom of each module
// section — clicks expand into an inline creation form on the same row.
export function AddRouteRow({
  module,
  channels,
  moduleLabel,
}: {
  module: string;
  channels: RoutesResponse["channels"];
  moduleLabel: string;
}) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <tr
        className="border-b border-line-soft last:border-0 hover:bg-surface-2"
        onClick={() => setOpen(true)}
        role="button"
        style={{ cursor: "pointer" }}
      >
        <td colSpan={4} className="px-4 py-2 text-xs text-signal hover:underline">
          + add route to {moduleLabel}
        </td>
      </tr>
    );
  }
  return (
    <tr className="border-b border-line-soft last:border-0 bg-surface-1">
      <td colSpan={4} className="px-4 py-3">
        <RouteEditor
          route={null}
          module={module}
          channels={channels}
          isCustom={false}
          onClose={() => setOpen(false)}
        />
      </td>
    </tr>
  );
}

// ---------- editor ------------------------------------------------------

function RouteEditor({
  route,
  module,
  channels,
  isCustom,
  onClose,
}: {
  route: Route | null;
  module: string;
  channels: RoutesResponse["channels"];
  isCustom: boolean;
  onClose: () => void;
}) {
  const [saveState, saveDispatch, savePending] = useActionState<RouteResult, FormData>(
    saveRouteAction,
    null,
  );
  const [testState, testDispatch, testPending] = useActionState<RouteResult, FormData>(
    testRouteAction,
    null,
  );
  const [silenceState, silenceDispatch, silencePending] = useActionState<RouteResult, FormData>(
    silenceRouteAction,
    null,
  );
  const [toggleState, toggleDispatch, togglePending] = useActionState<RouteResult, FormData>(
    toggleRouteAction,
    null,
  );
  const [deleteState, deleteDispatch, deletePending] = useActionState<RouteResult, FormData>(
    deleteRouteAction,
    null,
  );
  const status = latest(saveState, testState, silenceState, toggleState, deleteState);

  const initialSev = new Set(route?.severities ?? ["critical", "high"]);
  const currentChannel = route?.channel ?? "";
  const stateInfo = route ? computeState(route) : null;

  // Custom rules can't be re-edited via this mini-form because their match
  // tree contains conditions the mini-form can't express (action-contains,
  // multiple modules, negations, etc). We show a read-only summary + a link
  // to the full editor.
  if (isCustom && route) {
    return (
      <div className="space-y-3">
        <button
          type="button"
          onClick={onClose}
          className="float-right text-fg-subtle hover:text-fg"
          aria-label="Close"
        >
          <X size={12} />
        </button>
        <div>
          <div className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            Custom condition
          </div>
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words border border-line-soft bg-canvas px-2 py-1 font-mono text-[10px] text-fg-muted">
            {JSON.stringify(route.match, null, 2)}
          </pre>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild size="sm" variant="secondary">
            <Link href={`/notifications/rules/${encodeURIComponent(route.id)}`}>
              <ExternalLink size={11} /> Edit full rule
            </Link>
          </Button>

          <form action={testDispatch} className="inline">
            <input type="hidden" name="channel" value={route.channel ?? ""} />
            <Button
              type="submit"
              size="sm"
              variant="secondary"
              disabled={!route.channel || testPending}
            >
              {testPending ? <Spinner label="Sending…" /> : "Test"}
            </Button>
          </form>

          <ToggleForm
            id={route.id}
            enabled={route.enabled}
            dispatch={toggleDispatch}
            pending={togglePending}
          />

          <form action={deleteDispatch} className="ml-auto inline">
            <input type="hidden" name="id" value={route.id} />
            <Button
              type="submit"
              size="sm"
              variant="danger"
              disabled={deletePending}
            >
              {deletePending ? (
                <Spinner label="…" />
              ) : (
                <>
                  <Trash2 size={11} /> Delete
                </>
              )}
            </Button>
          </form>
        </div>
        {status && <InlineStatus status={status} />}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={onClose}
        className="float-right text-fg-subtle hover:text-fg"
        aria-label="Close"
      >
        <X size={12} />
      </button>

      <form action={saveDispatch} className="space-y-3">
        {route && <input type="hidden" name="id" value={route.id} />}
        <input type="hidden" name="module" value={module} />
        <input
          type="hidden"
          name="enabled"
          value={route?.enabled === false ? "off" : "on"}
        />

        <Field label="Trigger on severity">
          <SeverityCheckboxes name="severity" initialSelected={initialSev} />
        </Field>

        <Field label="Send to channel">
          <NativeSelect
            name="channel"
            defaultValue={currentChannel}
            className="w-full max-w-sm"
          >
            <option value="">— pick a channel —</option>
            {channels.map((ch) => (
              <option key={ch.name} value={ch.name} disabled={!ch.enabled}>
                {ch.name} · {ch.type}
                {!ch.enabled ? " (disabled)" : ""}
              </option>
            ))}
          </NativeSelect>
        </Field>

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button type="submit" size="sm" variant="primary" disabled={savePending}>
            {savePending ? <Spinner label="Saving…" /> : route ? "Save" : "Add route"}
          </Button>

          <span className="mx-1 h-4 w-px bg-line-soft" />

          <form action={testDispatch} className="inline">
            <input type="hidden" name="channel" value={route?.channel ?? ""} />
            <Button
              type="submit"
              size="sm"
              variant="secondary"
              disabled={!route?.channel || testPending}
            >
              {testPending ? <Spinner label="Sending…" /> : "Test"}
            </Button>
          </form>

          {route && (
            <>
              <SilenceForm
                id={route.id}
                silenced={stateInfo?.label === "silenced"}
                dispatch={silenceDispatch}
                pending={silencePending}
              />
              <ToggleForm
                id={route.id}
                enabled={route.enabled}
                dispatch={toggleDispatch}
                pending={togglePending}
              />
              <form action={deleteDispatch} className="ml-auto inline">
                <input type="hidden" name="id" value={route.id} />
                <Button
                  type="submit"
                  size="sm"
                  variant="danger"
                  disabled={deletePending}
                >
                  {deletePending ? (
                    <Spinner label="…" />
                  ) : (
                    <>
                      <Trash2 size={11} /> Delete
                    </>
                  )}
                </Button>
              </form>
            </>
          )}
        </div>
      </form>

      {status && <InlineStatus status={status} />}
    </div>
  );
}

// ---------- form bits ---------------------------------------------------

function SeverityCheckboxes({
  name,
  initialSelected,
}: {
  name: string;
  initialSelected: Set<string>;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {SEVERITIES.map((s) => (
        <label
          key={s.key}
          className={clsx(
            "flex cursor-pointer items-center gap-1.5 border px-2 py-1 text-xs transition-colors",
            "border-line-soft bg-canvas text-fg-muted hover:bg-surface-2",
            "has-[input:checked]:border-signal/50 has-[input:checked]:bg-signal/5 has-[input:checked]:text-fg",
          )}
        >
          <input
            type="checkbox"
            name={name}
            value={s.key}
            defaultChecked={initialSelected.has(s.key)}
            className="accent-signal"
          />
          <span className={s.className}>{s.label}</span>
        </label>
      ))}
    </div>
  );
}

function SeverityChips({
  severities,
  isCustom,
  match,
}: {
  severities: SeverityKey[];
  isCustom: boolean;
  match: Record<string, unknown>;
}) {
  if (isCustom) {
    const summary = customConditionSummary(match);
    return <span className="text-xs text-fg-muted">{summary}</span>;
  }
  if (severities.length === 0) {
    return <span className="text-xs text-fg-subtle">any severity</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {severities.map((s) => {
        const meta = SEVERITIES.find((x) => x.key === s);
        return (
          <span
            key={s}
            className={clsx(
              "border border-line-soft bg-canvas px-1.5 py-0.5 font-mono text-[10px]",
              meta?.className ?? "text-fg-muted",
            )}
          >
            {meta?.label ?? s}
          </span>
        );
      })}
    </div>
  );
}

function customConditionSummary(match: Record<string, unknown>): string {
  const parts: string[] = [];
  const walk = (m: unknown): void => {
    if (!m || typeof m !== "object") return;
    const node = m as Record<string, unknown>;
    if (Array.isArray(node.all)) node.all.forEach(walk);
    if (Array.isArray(node.any)) node.any.forEach(walk);
    if (node.field === "action" && node.op === "icontains") {
      parts.push(`action ~ "${node.value}"`);
    } else if (node.field === "source.module" && Array.isArray(node.value)) {
      parts.push(`from ${(node.value as string[]).join(" or ")}`);
    } else if (node.field === "category" && Array.isArray(node.value)) {
      parts.push(`category ${(node.value as string[]).join(" or ")}`);
    }
  };
  walk(match);
  return parts.length > 0 ? parts.join(" · ") : "custom condition";
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
        {label}
      </div>
      {children}
    </div>
  );
}

function ToggleForm({
  id,
  enabled,
  dispatch,
  pending,
}: {
  id: string;
  enabled: boolean;
  dispatch: (fd: FormData) => void;
  pending: boolean;
}) {
  return (
    <form action={dispatch} className="inline">
      <input type="hidden" name="id" value={id} />
      <input type="hidden" name="target" value={enabled ? "off" : "on"} />
      <Button type="submit" size="sm" variant="secondary" disabled={pending}>
        {pending ? <Spinner label="…" /> : enabled ? "Turn off" : "Turn on"}
      </Button>
    </form>
  );
}

function SilenceForm({
  id,
  silenced,
  dispatch,
  pending,
}: {
  id: string;
  silenced: boolean;
  dispatch: (fd: FormData) => void;
  pending: boolean;
}) {
  return (
    <form action={dispatch} className="inline-flex items-center gap-1">
      <input type="hidden" name="id" value={id} />
      <NativeSelect
        name="hours"
        defaultValue={silenced ? "0" : "1"}
        className="h-7 text-xs"
      >
        <option value="1">1h</option>
        <option value="4">4h</option>
        <option value="24">24h</option>
        <option value="0">clear</option>
      </NativeSelect>
      <Button type="submit" size="sm" variant="secondary" disabled={pending}>
        {pending ? <Spinner label="…" /> : silenced ? "Un-silence" : "Silence"}
      </Button>
    </form>
  );
}

// ---------- shared ------------------------------------------------------

function InlineStatus({ status }: { status: NonNullable<RouteResult> }) {
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    setVisible(true);
    const t = setTimeout(() => setVisible(false), 5000);
    return () => clearTimeout(t);
  }, [status.at]);
  if (!visible) return null;
  const Icon = status.ok ? CheckCircle2 : XCircle;
  return (
    <div
      className={clsx(
        "mt-2 flex items-start gap-2 border-l-2 px-3 py-2 text-xs",
        status.ok
          ? "border-sev-resolved/60 bg-sev-resolved/5"
          : "border-sev-critical/60 bg-sev-critical/5",
      )}
    >
      <Icon
        size={13}
        className={clsx(
          "mt-0.5 shrink-0",
          status.ok ? "text-sev-resolved" : "text-sev-critical",
        )}
        aria-hidden
      />
      <span className="text-fg">{status.message}</span>
    </div>
  );
}

function Spinner({ label }: { label: string }) {
  return (
    <>
      <Loader2 size={12} className="animate-spin" />
      <span>{label}</span>
    </>
  );
}

function computeState(route: Route): { label: string; className: string } {
  if (!route.channel) return { label: "no channel", className: "text-fg-subtle" };
  if (route.silenced) return { label: "silenced", className: "text-sev-medium" };
  if (!route.enabled) return { label: "off", className: "text-fg-subtle" };
  return { label: "on", className: "text-signal" };
}

function latest(
  ...results: (RouteResult | null)[]
): NonNullable<RouteResult> | null {
  let best: NonNullable<RouteResult> | null = null;
  for (const r of results) {
    if (!r) continue;
    if (!best || r.at > best.at) best = r;
  }
  return best;
}
