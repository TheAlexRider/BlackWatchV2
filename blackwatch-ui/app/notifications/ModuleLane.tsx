"use client";

import Link from "next/link";
import clsx from "clsx";
import { useActionState, useState } from "react";
import { Pencil } from "lucide-react";

import type {
  CardThresholdKey,
  NotificationCard,
  NotificationCardsResponse,
} from "@/lib/types";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Button } from "@/components/ui/Button";

import {
  saveCardAction,
  testCardAction,
  toggleCardAction,
  silenceCardAction,
  type ActionResult,
} from "./routing/actions";

import {
  CollapsedRow,
  ExpandedBody,
  LaneShell,
  LaneStatus,
  Spinner,
  computeLaneState,
  latestResult,
} from "./Lane";

const THRESHOLD_META: Record<CardThresholdKey, string> = {
  critical: "only critical",
  high: "crit + high",
  medium: "≥ medium",
  low: "everything except info",
};

const THRESHOLDS: Array<{ key: CardThresholdKey; label: string; hint: string }> = [
  { key: "critical", label: "Only critical", hint: "emergencies only" },
  { key: "high", label: "Critical + high", hint: "recommended" },
  { key: "medium", label: "≥ medium", hint: "medium and above" },
  { key: "low", label: "Everything except info", hint: "noisiest" },
];

export function ModuleLane({
  card,
  channels,
  disabled,
}: {
  card: NotificationCard;
  channels: NotificationCardsResponse["channels"];
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const state = computeLaneState({
    hasChannel: !!card.channel,
    enabled: card.enabled,
    silenceUntilIso: card.silence_until,
  });
  const meta = card.channel ? THRESHOLD_META[card.threshold] : "—";

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
  const status = latestResult(saveState, testState, silenceState, toggleState);

  const channel = channels.find((c) => c.name === card.channel);

  return (
    <LaneShell state={state}>
      <CollapsedRow
        open={open}
        onToggle={() => setOpen((v) => !v)}
        name={card.label}
        hint={card.module}
        channel={card.channel}
        state={state}
        meta={meta}
        disabled={disabled}
      />

      {open && (
        <ExpandedBody>
          <p className="mb-3 text-xs text-fg-muted">{card.blurb}</p>

          {/* Companion rules — warn if other rules already fire on this
              module so the operator doesn't create a duplicate. */}
          {card.companion_rules.length > 0 && (
            <CompanionNote rules={card.companion_rules} />
          )}

          <form action={saveDispatch} className="space-y-3">
            <input type="hidden" name="module" value={card.module} />
            <input type="hidden" name="enabled" value={card.enabled ? "on" : "off"} />

            <Field label="Send to">
              <NativeSelect
                name="channel"
                defaultValue={card.channel ?? ""}
                disabled={disabled}
                className="w-full max-w-sm"
              >
                <option value="">— none (turn off) —</option>
                {channels.map((ch) => (
                  <option key={ch.name} value={ch.name} disabled={!ch.enabled}>
                    {ch.name} · {ch.type}
                    {!ch.enabled ? " (disabled)" : ""}
                  </option>
                ))}
              </NativeSelect>
            </Field>

            <Field label="Alert me on">
              <ThresholdRadios name="threshold" current={card.threshold} />
            </Field>

            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button
                type="submit"
                size="sm"
                variant="primary"
                disabled={disabled || savePending}
              >
                {savePending ? <Spinner label="Saving…" /> : "Save"}
              </Button>
              <span className="mx-1 h-4 w-px bg-line-soft" />

              {/* Other actions: separate forms so they submit independently. */}
              <TestForm
                module={card.module}
                dispatch={testDispatch}
                pending={testPending}
                disabled={!card.channel}
              />
              <SilenceForm
                module={card.module}
                currentlySilenced={state === "silenced"}
                dispatch={silenceDispatch}
                pending={silencePending}
              />
              <ToggleForm
                module={card.module}
                channel={card.channel}
                threshold={card.threshold}
                enabled={card.enabled}
                dispatch={toggleDispatch}
                pending={togglePending}
              />
              {channel && (
                <Link
                  href={`/notifications/channels/${encodeURIComponent(channel.id)}`}
                  className="inline-flex items-center gap-1 text-[11px] text-fg-subtle hover:text-signal"
                >
                  <Pencil size={10} />
                  <span>Customize message</span>
                </Link>
              )}
            </div>
          </form>

          {status && <LaneStatus status={status} />}
        </ExpandedBody>
      )}
    </LaneShell>
  );
}

// ---------- inline sub-forms ---------------------------------------------
// These render OUTSIDE the outer save form so nested-form validation stays
// clean and their submits are independent.

function TestForm({
  module,
  dispatch,
  pending,
  disabled,
}: {
  module: string;
  dispatch: (fd: FormData) => void;
  pending: boolean;
  disabled: boolean;
}) {
  return (
    <form action={dispatch} className="inline">
      <input type="hidden" name="module" value={module} />
      <Button
        type="submit"
        size="sm"
        variant="secondary"
        disabled={disabled || pending}
      >
        {pending ? <Spinner label="Sending…" /> : "Test"}
      </Button>
    </form>
  );
}

function SilenceForm({
  module,
  currentlySilenced,
  dispatch,
  pending,
}: {
  module: string;
  currentlySilenced: boolean;
  dispatch: (fd: FormData) => void;
  pending: boolean;
}) {
  return (
    <form action={dispatch} className="inline-flex items-center gap-1">
      <input type="hidden" name="module" value={module} />
      <NativeSelect
        name="hours"
        defaultValue={currentlySilenced ? "0" : "1"}
        className="h-7 text-xs"
      >
        <option value="1">1h</option>
        <option value="4">4h</option>
        <option value="24">24h</option>
        <option value="0">clear</option>
      </NativeSelect>
      <Button type="submit" size="sm" variant="secondary" disabled={pending}>
        {pending ? <Spinner label="…" /> : currentlySilenced ? "Un-silence" : "Silence"}
      </Button>
    </form>
  );
}

function ToggleForm({
  module,
  channel,
  threshold,
  enabled,
  dispatch,
  pending,
}: {
  module: string;
  channel: string | null;
  threshold: CardThresholdKey;
  enabled: boolean;
  dispatch: (fd: FormData) => void;
  pending: boolean;
}) {
  if (!channel) return null;
  return (
    <form action={dispatch} className="inline">
      <input type="hidden" name="module" value={module} />
      <input type="hidden" name="channel" value={channel} />
      <input type="hidden" name="threshold" value={threshold} />
      <input type="hidden" name="target" value={enabled ? "off" : "on"} />
      <Button type="submit" size="sm" variant="secondary" disabled={pending}>
        {pending ? <Spinner label="…" /> : enabled ? "Turn off" : "Turn on"}
      </Button>
    </form>
  );
}

// ---------- companion-rule warning ---------------------------------------

function CompanionNote({
  rules,
}: {
  rules: NotificationCard["companion_rules"];
}) {
  return (
    <details className="mb-3 border border-sev-medium/40 bg-sev-medium/5 px-3 py-2 text-xs">
      <summary className="cursor-pointer text-fg-muted">
        <span className="text-sev-medium">⚠</span> {rules.length} other rule
        {rules.length === 1 ? "" : "s"} already target this module
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

// ---------- threshold radios ---------------------------------------------

function ThresholdRadios({
  name,
  current,
}: {
  name: string;
  current: CardThresholdKey;
}) {
  return (
    <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
      {THRESHOLDS.map((opt) => (
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

// ---------- shared little bits -------------------------------------------

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
        {label}
      </div>
      {children}
    </div>
  );
}
