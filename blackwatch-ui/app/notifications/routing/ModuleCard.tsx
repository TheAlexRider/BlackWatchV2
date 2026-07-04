"use client";

import Link from "next/link";
import clsx from "clsx";
import { useActionState, useEffect, useState } from "react";
import {
  Activity,
  Archive,
  BellOff,
  CheckCircle2,
  Database,
  Eye,
  KeyRound,
  Loader2,
  Network,
  Pencil,
  Server,
  Shield,
  XCircle,
} from "lucide-react";

import type {
  CardThresholdKey,
  NotificationCard,
  NotificationCardsResponse,
} from "@/lib/types";
import { DataPanel } from "@/components/layout/DataPanel";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Button } from "@/components/ui/Button";

import {
  saveCardAction,
  toggleCardAction,
  testCardAction,
  silenceCardAction,
  type ActionResult,
} from "./actions";

// One card per module. Fully client-side so form submits give inline
// feedback (inside the card) rather than a full-page refresh + top toast.
export function ModuleCard({
  card,
  channels,
  disabled,
}: {
  card: NotificationCard;
  channels: NotificationCardsResponse["channels"];
  disabled: boolean;
}) {
  const Icon = ICONS[card.icon] ?? Shield;
  const silencedUntil = card.silence_until ? new Date(card.silence_until).getTime() : 0;
  const isSilenced = silencedUntil > Date.now();
  const isRouted = !!card.channel;
  const isLive = isRouted && card.enabled && !isSilenced;

  // Four independent action states, one per button-form. The user gets
  // separate pending indicators for each.
  const [saveState, saveDispatch, savePending] = useActionState<ActionResult, FormData>(
    saveCardAction,
    null,
  );
  const [testState, testDispatch, testPending] = useActionState<ActionResult, FormData>(
    testCardAction,
    null,
  );
  const [silenceState, silenceDispatch, silencePending] = useActionState<ActionResult, FormData>(
    silenceCardAction,
    null,
  );
  const [toggleState, toggleDispatch, togglePending] = useActionState<ActionResult, FormData>(
    toggleCardAction,
    null,
  );

  // Latest result across all four actions — that's what we show as inline
  // feedback in the card. Pick by most recent `at` timestamp.
  const status = latest(saveState, testState, silenceState, toggleState);

  return (
    <DataPanel className="p-0">
      {/* Header row */}
      <div className="flex items-center justify-between border-b border-line-soft px-4 py-3">
        <div className="flex items-center gap-3">
          <span
            aria-hidden
            className={clsx(
              "flex h-8 w-8 items-center justify-center border",
              isLive
                ? "border-signal/30 bg-signal/5 text-signal"
                : "border-line-soft bg-surface-2 text-fg-muted",
            )}
          >
            <Icon size={14} />
          </span>
          <div>
            <div className="text-sm text-fg">{card.label}</div>
            <div className="font-mono text-[10px] text-fg-subtle">{card.module}</div>
          </div>
        </div>
        <StateBadge live={isLive} silenced={isSilenced} routed={isRouted} enabled={card.enabled} />
      </div>

      {/* Blurb */}
      <div className="px-4 pt-3 text-xs text-fg-muted">{card.blurb}</div>

      {/* Companion rules — flag hand-written rules that already fire on this
          module so the operator doesn't create a duplicate. */}
      {card.companion_rules.length > 0 && (
        <CompanionRulesNote rules={card.companion_rules} />
      )}

      {/* Save form. NOT wrapping other action buttons — nested forms are
          invalid HTML. */}
      <form action={saveDispatch} className="space-y-3 px-4 pb-3 pt-3">
        <input type="hidden" name="module" value={card.module} />
        <input type="hidden" name="enabled" value={card.enabled ? "on" : "off"} />

        <div className="space-y-1.5">
          <label className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            Send alerts to
          </label>
          <NativeSelect
            name="channel"
            defaultValue={card.channel ?? ""}
            disabled={disabled}
            className="w-full"
          >
            <option value="">— none (turn off) —</option>
            {channels.map((ch) => (
              <option key={ch.name} value={ch.name} disabled={!ch.enabled}>
                {ch.name} · {ch.type}
                {!ch.enabled ? " (disabled)" : ""}
              </option>
            ))}
          </NativeSelect>
        </div>

        <div className="space-y-1.5">
          <label className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            Alert me on
          </label>
          <ThresholdRadios name="threshold" current={card.threshold} />
        </div>

        <div className="flex justify-end pt-1">
          <Button
            type="submit"
            size="sm"
            variant="primary"
            disabled={disabled || savePending}
          >
            {savePending ? <PendingSpinner label="Saving…" /> : "Save"}
          </Button>
        </div>
      </form>

      {/* Inline status — replaces the old top-of-page FlashToast. Belongs
          to THIS card and only THIS card. Auto-clears after 5 s. */}
      {status && <InlineStatus status={status} />}

      {/* Footer actions — OUTSIDE the save form. */}
      <div className="flex flex-wrap items-center justify-end gap-1.5 border-t border-line-soft bg-surface-1 px-4 py-2">
        <form action={testDispatch} className="inline">
          <input type="hidden" name="module" value={card.module} />
          <Button
            type="submit"
            size="sm"
            variant="secondary"
            disabled={!isRouted || testPending}
          >
            {testPending ? <PendingSpinner label="Sending…" /> : "Test"}
          </Button>
        </form>

        {isRouted && (
          <form action={silenceDispatch} className="inline-flex items-center gap-1">
            <input type="hidden" name="module" value={card.module} />
            <NativeSelect name="hours" defaultValue={isSilenced ? "0" : "1"} className="h-7 text-xs">
              <option value="1">1h</option>
              <option value="4">4h</option>
              <option value="24">24h</option>
              <option value="0">clear</option>
            </NativeSelect>
            <Button type="submit" size="sm" variant="secondary" disabled={silencePending}>
              {silencePending ? (
                <PendingSpinner label="…" />
              ) : isSilenced ? (
                "Un-silence"
              ) : (
                "Silence"
              )}
            </Button>
          </form>
        )}

        {isRouted && (
          <form action={toggleDispatch} className="inline">
            <input type="hidden" name="module" value={card.module} />
            <input type="hidden" name="channel" value={card.channel ?? ""} />
            <input type="hidden" name="threshold" value={card.threshold} />
            <input type="hidden" name="target" value={card.enabled ? "off" : "on"} />
            <Button type="submit" size="sm" variant="secondary" disabled={togglePending}>
              {togglePending ? (
                <PendingSpinner label="…" />
              ) : card.enabled ? (
                "Turn off"
              ) : (
                "Turn on"
              )}
            </Button>
          </form>
        )}
      </div>

      {isRouted && (
        <CustomizeMessageLink channelName={card.channel!} channels={channels} />
      )}
    </DataPanel>
  );
}

// ---- Inline status ------------------------------------------------------

function InlineStatus({ status }: { status: NonNullable<ActionResult> }) {
  const [visible, setVisible] = useState(true);
  // Reset visibility + restart timer whenever a new status comes in.
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
        "flex items-start gap-2 border-t px-4 py-2 text-xs",
        status.ok
          ? "border-sev-resolved/30 bg-sev-resolved/5 text-fg"
          : "border-sev-critical/40 bg-sev-critical/5 text-fg",
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
      <span>{status.message}</span>
    </div>
  );
}

function PendingSpinner({ label }: { label: string }) {
  return (
    <>
      <Loader2 size={12} className="animate-spin" />
      <span>{label}</span>
    </>
  );
}

function latest(...results: (ActionResult | null)[]): NonNullable<ActionResult> | null {
  let best: NonNullable<ActionResult> | null = null;
  for (const r of results) {
    if (!r) continue;
    if (!best || r.at > best.at) best = r;
  }
  return best;
}

// ---- Companion rules ---------------------------------------------------

function CompanionRulesNote({
  rules,
}: {
  rules: NotificationCard["companion_rules"];
}) {
  const active = rules.filter((r) => r.enabled);
  const label =
    active.length === rules.length
      ? `${rules.length} other rule${rules.length === 1 ? "" : "s"} also fire${
          rules.length === 1 ? "s" : ""
        } on this module`
      : `${rules.length} other rule${rules.length === 1 ? "" : "s"} target this module (${active.length} enabled)`;
  return (
    <details className="mx-4 mt-3 border border-sev-medium/30 bg-sev-medium/5 px-3 py-2 text-xs">
      <summary className="cursor-pointer text-fg-muted">
        <span className="text-sev-medium">⚠</span> {label} — click to review
      </summary>
      <ul className="mt-2 space-y-1.5">
        {rules.map((r) => (
          <li
            key={r.id}
            className="flex items-center justify-between gap-2 border-t border-line-soft pt-1.5 first:border-t-0 first:pt-0"
          >
            <div className="min-w-0 truncate">
              <Link
                href={`/notifications/rules/${encodeURIComponent(r.id)}`}
                className="font-mono text-[11px] text-fg transition-colors hover:text-signal"
              >
                {r.name}
              </Link>
              <span className="ml-2 text-[10px] text-fg-subtle">
                → {r.channels.length === 0 ? "(no channel)" : r.channels.join(", ")}
              </span>
            </div>
            <span
              className={clsx(
                "shrink-0 text-[10px]",
                r.enabled ? "text-sev-resolved" : "text-fg-subtle",
              )}
            >
              {r.enabled ? "enabled" : "disabled"}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

// ---- Threshold radios --------------------------------------------------

const THRESHOLD_OPTIONS: Array<{ key: CardThresholdKey; label: string; hint: string }> = [
  { key: "critical", label: "Only critical", hint: "emergencies only" },
  { key: "high", label: "Critical + high", hint: "recommended" },
  { key: "medium", label: "≥ medium", hint: "medium and above" },
  { key: "low", label: "Everything except info", hint: "noisiest" },
];

function ThresholdRadios({ name, current }: { name: string; current: CardThresholdKey }) {
  // Selection styling follows real DOM checked state via `has-[]`, so
  // clicking a different radio moves the blue box without a re-render.
  return (
    <div className="grid grid-cols-2 gap-2">
      {THRESHOLD_OPTIONS.map((opt) => (
        <label
          key={opt.key}
          className={clsx(
            "flex cursor-pointer flex-col gap-0.5 border bg-surface-1 px-2.5 py-2 text-xs text-fg-muted transition-colors",
            "border-line-soft hover:bg-surface-2",
            "has-[input:checked]:border-signal/50 has-[input:checked]:bg-signal/5 has-[input:checked]:text-fg",
          )}
        >
          <span className="flex items-center gap-1.5">
            <input
              type="radio"
              name={name}
              value={opt.key}
              defaultChecked={opt.key === current}
              className="accent-signal"
            />
            <span>{opt.label}</span>
          </span>
          <span className="pl-5 text-[10px] text-fg-subtle">{opt.hint}</span>
        </label>
      ))}
    </div>
  );
}

// ---- State badges ------------------------------------------------------

function StateBadge({
  live,
  silenced,
  routed,
  enabled,
}: {
  live: boolean;
  silenced: boolean;
  routed: boolean;
  enabled: boolean;
}) {
  if (silenced)
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <BellOff size={11} className="text-sev-medium" aria-hidden />
        <span className="text-fg-muted">silenced</span>
      </span>
    );
  if (!routed)
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span className="h-1.5 w-1.5 rounded-full bg-fg-subtle" aria-hidden />
        <span className="text-fg-subtle">not set up</span>
      </span>
    );
  if (!enabled)
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span className="h-1.5 w-1.5 rounded-full bg-fg-subtle" aria-hidden />
        <span className="text-fg-subtle">disabled</span>
      </span>
    );
  if (live)
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span className="h-1.5 w-1.5 rounded-full bg-sev-resolved" aria-hidden />
        <span className="text-fg-muted">on</span>
      </span>
    );
  return null;
}

// ---- Bits ---------------------------------------------------------------

function CustomizeMessageLink({
  channelName,
  channels,
}: {
  channelName: string;
  channels: NotificationCardsResponse["channels"];
}) {
  const channel = channels.find((c) => c.name === channelName);
  if (!channel) return null;
  return (
    <div className="border-t border-line-soft bg-surface-1 px-4 py-2">
      <Link
        href={`/notifications/channels/${encodeURIComponent(channel.id)}`}
        className="inline-flex items-center gap-1.5 text-[11px] text-fg-subtle hover:text-signal"
      >
        <Pencil size={10} />
        <span>Customize message format for {channelName}</span>
      </Link>
    </div>
  );
}

const ICONS: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  database: Database,
  shield: Shield,
  archive: Archive,
  eye: Eye,
  network: Network,
  server: Server,
  activity: Activity,
  "key-round": KeyRound,
};
