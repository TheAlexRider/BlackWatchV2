"use client";

import Link from "next/link";
import clsx from "clsx";
import { useActionState, useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink, Trash2 } from "lucide-react";

import type { NotificationRule } from "@/lib/types";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Button } from "@/components/ui/Button";

import {
  setCustomRuleChannelAction,
  toggleCustomRuleAction,
  silenceCustomRuleAction,
  deleteCustomRuleAction,
  testChannelByNameAction,
  type LaneResult,
} from "./lane-actions";

import {
  CollapsedRow,
  ExpandedBody,
  LaneShell,
  LaneStatus,
  Spinner,
  computeLaneState,
  latestResult,
} from "./Lane";

export function CustomLane({
  rule,
  channels,
}: {
  rule: NotificationRule;
  channels: Array<{ id: string; name: string; type: string; enabled: boolean }>;
}) {
  const [open, setOpen] = useState(false);
  const [conditionOpen, setConditionOpen] = useState(false);

  const currentChannel = rule.channels[0] ?? null;
  const state = computeLaneState({
    hasChannel: !!currentChannel,
    enabled: rule.enabled,
    silenceUntilIso: rule.silence_until,
  });

  const [saveState, saveDispatch, savePending] = useActionState<LaneResult, FormData>(
    setCustomRuleChannelAction,
    null,
  );
  const [testState, testDispatch, testPending] = useActionState<LaneResult, FormData>(
    testChannelByNameAction,
    null,
  );
  const [silenceState, silenceDispatch, silencePending] = useActionState<LaneResult, FormData>(
    silenceCustomRuleAction,
    null,
  );
  const [toggleState, toggleDispatch, togglePending] = useActionState<LaneResult, FormData>(
    toggleCustomRuleAction,
    null,
  );
  const [deleteState, deleteDispatch, deletePending] = useActionState<LaneResult, FormData>(
    deleteCustomRuleAction,
    null,
  );
  const status = latestResult(
    saveState,
    testState,
    silenceState,
    toggleState,
    deleteState,
  );

  return (
    <LaneShell state={state}>
      <CollapsedRow
        open={open}
        onToggle={() => setOpen((v) => !v)}
        name={rule.name}
        channel={currentChannel}
        state={state}
        meta={<ConditionSummary match={rule.match} />}
      />

      {open && (
        <ExpandedBody>
          {/* Condition — read-only summary, expandable to raw. Editing the
              condition tree still goes to /rules/[id] (full form). */}
          <div className="mb-3 border border-line-soft bg-canvas">
            <button
              type="button"
              onClick={() => setConditionOpen((v) => !v)}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11px] uppercase tracking-[0.06em] text-fg-subtle hover:text-fg"
            >
              {conditionOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
              <span>Sends when</span>
              <span className="text-fg-muted normal-case tracking-normal">
                <ConditionSummary match={rule.match} />
              </span>
            </button>
            {conditionOpen && (
              <div className="border-t border-line-soft px-3 py-2">
                <pre className="max-h-60 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] text-fg-muted">
                  {JSON.stringify(rule.match, null, 2)}
                </pre>
                <Link
                  href={`/notifications/rules/${encodeURIComponent(rule.id)}`}
                  className="mt-2 inline-flex items-center gap-1 text-[11px] text-signal hover:underline"
                >
                  <ExternalLink size={10} />
                  Edit condition
                </Link>
              </div>
            )}
          </div>

          <form action={saveDispatch} className="space-y-3">
            <input type="hidden" name="id" value={rule.id} />
            <Field label="Send to">
              <NativeSelect
                name="channel"
                defaultValue={currentChannel ?? ""}
                className="w-full max-w-sm"
              >
                <option value="">— none —</option>
                {channels.map((ch) => (
                  <option key={ch.name} value={ch.name} disabled={!ch.enabled}>
                    {ch.name} · {ch.type}
                    {!ch.enabled ? " (disabled)" : ""}
                  </option>
                ))}
              </NativeSelect>
            </Field>

            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button
                type="submit"
                size="sm"
                variant="primary"
                disabled={savePending}
              >
                {savePending ? <Spinner label="Saving…" /> : "Save"}
              </Button>
              <span className="mx-1 h-4 w-px bg-line-soft" />

              <form action={testDispatch} className="inline">
                <input type="hidden" name="channel" value={currentChannel ?? ""} />
                <Button
                  type="submit"
                  size="sm"
                  variant="secondary"
                  disabled={!currentChannel || testPending}
                >
                  {testPending ? <Spinner label="Sending…" /> : "Test"}
                </Button>
              </form>

              <form action={silenceDispatch} className="inline-flex items-center gap-1">
                <input type="hidden" name="id" value={rule.id} />
                <NativeSelect
                  name="hours"
                  defaultValue={state === "silenced" ? "0" : "1"}
                  className="h-7 text-xs"
                >
                  <option value="1">1h</option>
                  <option value="4">4h</option>
                  <option value="24">24h</option>
                  <option value="0">clear</option>
                </NativeSelect>
                <Button
                  type="submit"
                  size="sm"
                  variant="secondary"
                  disabled={silencePending}
                >
                  {silencePending ? (
                    <Spinner label="…" />
                  ) : state === "silenced" ? (
                    "Un-silence"
                  ) : (
                    "Silence"
                  )}
                </Button>
              </form>

              <form action={toggleDispatch} className="inline">
                <input type="hidden" name="id" value={rule.id} />
                <input
                  type="hidden"
                  name="target"
                  value={rule.enabled ? "off" : "on"}
                />
                <Button
                  type="submit"
                  size="sm"
                  variant="secondary"
                  disabled={togglePending}
                >
                  {togglePending ? (
                    <Spinner label="…" />
                  ) : rule.enabled ? (
                    "Turn off"
                  ) : (
                    "Turn on"
                  )}
                </Button>
              </form>

              <form action={deleteDispatch} className="ml-auto inline">
                <input type="hidden" name="id" value={rule.id} />
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
          </form>

          {status && <LaneStatus status={status} />}
        </ExpandedBody>
      )}
    </LaneShell>
  );
}

// One-line plain-English summary of the rule's Condition. Mirrors the
// vocabulary in the old /notifications rules table so the eye recognizes it.
function ConditionSummary({ match }: { match: Record<string, unknown> }) {
  const parts: string[] = [];
  let sawUnknown = false;

  const all =
    (match.all as unknown[]) ?? (Object.keys(match ?? {}).length > 0 ? [match] : []);

  for (const p of all) {
    if (typeof p !== "object" || p === null) {
      sawUnknown = true;
      continue;
    }
    const part = p as Record<string, unknown>;
    const inList: string[] | null =
      Array.isArray(part.in)
        ? (part.in as string[])
        : part.op === "in" && Array.isArray(part.value)
        ? (part.value as string[])
        : null;
    const iContainsValue: string | null =
      typeof part.icontains === "string"
        ? (part.icontains as string)
        : part.op === "icontains" && typeof part.value === "string"
        ? (part.value as string)
        : null;
    const equalsValue: string | null =
      part.op === "equals" && typeof part.value === "string"
        ? (part.value as string)
        : null;

    if (part.field === "severity" && inList) parts.push(severityPhrase(inList));
    else if (part.field === "category" && inList) parts.push(`in ${inList.join(" or ")}`);
    else if (part.field === "source.module" && inList) parts.push(`from ${inList.join(" or ")}`);
    else if (part.field === "source.module" && equalsValue)
      parts.push(`from ${equalsValue}`);
    else if (part.field === "action" && iContainsValue !== null)
      parts.push(`action ~ "${iContainsValue}"`);
    else sawUnknown = true;
  }

  const text = parts.length > 0 ? parts.join(" · ") : "everything";
  return (
    <span className={clsx("text-xs", parts.length === 0 && "text-fg-subtle")}>
      {text}
      {sawUnknown && (
        <span className="ml-1.5 text-[10px] text-fg-subtle">(custom)</span>
      )}
    </span>
  );
}

function severityPhrase(sevs: string[]): string {
  const set = new Set(sevs);
  if (set.size === 1 && set.has("critical")) return "critical only";
  if (set.size === 2 && set.has("critical") && set.has("high")) return "crit + high";
  if (set.size === 3 && set.has("critical") && set.has("high") && set.has("medium"))
    return "≥ medium";
  if (
    set.size === 4 &&
    set.has("critical") &&
    set.has("high") &&
    set.has("medium") &&
    set.has("low")
  )
    return "except info";
  return sevs.join(" / ");
}

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
