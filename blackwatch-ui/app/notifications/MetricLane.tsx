"use client";

import { useActionState, useState } from "react";

import type {
  PerfQuickCard,
  PerfQuickExistingRule,
  PerfQuickResponse,
} from "@/lib/types";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

import { savePerfQuickAction, type ActionResult } from "./perf-alerts/quick/actions";

import {
  CollapsedRow,
  ExpandedBody,
  LaneShell,
  LaneStatus,
  Spinner,
  computeLaneState,
} from "./Lane";

export function MetricLane({
  card,
  channels,
  instances,
  disabled,
}: {
  card: PerfQuickCard;
  channels: PerfQuickResponse["channels"];
  instances: PerfQuickResponse["instances"];
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  // Only the primary (first) rule per metric is surfaced on the lane.
  // Anything additional is shown in the expanded editor's warning block.
  const existing: PerfQuickExistingRule | undefined = card.existing[0];
  const state = computeLaneState({
    hasChannel: !!existing?.channels?.[0],
    enabled: !!existing?.enabled,
  });
  const channelName = existing?.channels?.[0] ?? null;
  const meta = existing
    ? formatMeta(existing)
    : "—";

  const [saveState, saveDispatch, savePending] = useActionState<ActionResult, FormData>(
    savePerfQuickAction,
    null,
  );

  const currentThreshold = existing?.threshold ?? card.default_threshold;
  const currentWindowMin = existing
    ? Math.max(1, Math.round(existing.window_seconds / 60))
    : card.default_window_minutes;
  const currentScope: "all" | "instance" = existing?.instance_id ? "instance" : "all";
  const currentInstance = existing?.instance_id ?? "";
  const currentSeverity = existing?.severity ?? card.default_severity;

  return (
    <LaneShell state={state}>
      <CollapsedRow
        open={open}
        onToggle={() => setOpen((v) => !v)}
        name={card.label}
        hint={card.metric}
        channel={channelName}
        state={state}
        meta={meta}
        disabled={disabled}
      />

      {open && (
        <ExpandedBody>
          <p className="mb-3 text-xs text-fg-muted">{card.blurb}</p>

          {card.existing.length > 1 && (
            <ExistingNote rules={card.existing} />
          )}

          <form action={saveDispatch} className="space-y-3">
            <input type="hidden" name="metric" value={card.metric} />
            <input
              type="hidden"
              name="enabled"
              value={existing?.enabled === false ? "off" : "on"}
            />

            <div className="grid grid-cols-2 gap-3">
              <Field label="Alert when ≥">
                <div className="flex items-center gap-1.5">
                  <Input
                    name="threshold"
                    type="number"
                    min={0}
                    max={100}
                    defaultValue={currentThreshold}
                    className="w-20"
                    mono
                  />
                  <span className="text-xs text-fg-muted">%</span>
                </div>
              </Field>
              <Field label="For at least">
                <div className="flex items-center gap-1.5">
                  <Input
                    name="window_minutes"
                    type="number"
                    min={1}
                    max={120}
                    defaultValue={currentWindowMin}
                    className="w-20"
                    mono
                  />
                  <span className="text-xs text-fg-muted">minutes</span>
                </div>
              </Field>
            </div>

            <Field label="On">
              <div className="flex flex-col gap-1.5">
                <label className="flex items-center gap-2 text-xs">
                  <input
                    type="radio"
                    name="scope"
                    value="all"
                    defaultChecked={currentScope === "all"}
                    className="accent-signal"
                  />
                  <span className="text-fg-muted">all hosts</span>
                </label>
                <label className="flex items-center gap-2 text-xs">
                  <input
                    type="radio"
                    name="scope"
                    value="instance"
                    defaultChecked={currentScope === "instance"}
                    className="accent-signal"
                  />
                  <span className="text-fg-muted">just this host</span>
                  <NativeSelect
                    name="instance_id"
                    defaultValue={currentInstance}
                    className="h-7 text-xs"
                  >
                    <option value="">— pick host —</option>
                    {instances.map((i) => (
                      <option key={i.instance_id} value={i.instance_id}>
                        {i.hostname ?? i.instance_id}
                      </option>
                    ))}
                  </NativeSelect>
                </label>
              </div>
            </Field>

            <Field label="Send to">
              <NativeSelect
                name="channel"
                defaultValue={channelName ?? ""}
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

            <Field label="Severity">
              <NativeSelect
                name="severity"
                defaultValue={currentSeverity}
                className="w-32"
              >
                <option value="informational">informational</option>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
                <option value="critical">critical</option>
              </NativeSelect>
            </Field>

            <div className="flex items-center gap-2 pt-1">
              <Button
                type="submit"
                size="sm"
                variant="primary"
                disabled={disabled || savePending}
              >
                {savePending ? <Spinner label="Saving…" /> : "Save"}
              </Button>
            </div>
          </form>

          {saveState && <LaneStatus status={saveState} />}
        </ExpandedBody>
      )}
    </LaneShell>
  );
}

function formatMeta(rule: PerfQuickExistingRule): string {
  const minutes = Math.max(1, Math.round(rule.window_seconds / 60));
  const scope = rule.instance_id ?? "all hosts";
  return `≥ ${rule.threshold}% / ${minutes}m · ${scope}`;
}

function ExistingNote({ rules }: { rules: PerfQuickExistingRule[] }) {
  return (
    <details className="mb-3 border border-sev-medium/40 bg-sev-medium/5 px-3 py-2 text-xs">
      <summary className="cursor-pointer text-fg-muted">
        <span className="text-sev-medium">⚠</span> {rules.length} rules already
        exist for this metric — different scopes / thresholds
      </summary>
      <ul className="mt-2 space-y-1.5">
        {rules.map((r) => (
          <li
            key={r.id}
            className="flex items-center justify-between gap-2 border-t border-line-soft pt-1.5 first:border-t-0 first:pt-0"
          >
            <div className="min-w-0 truncate font-mono text-[11px] text-fg">
              {r.name}
              <span className="ml-2 text-[10px] text-fg-subtle">
                @ {r.threshold}% ·{" "}
                {Math.max(1, Math.round(r.window_seconds / 60))}m
                {r.instance_id ? ` · ${r.instance_id}` : " · all hosts"}
              </span>
            </div>
            <span className="shrink-0 text-[10px] text-fg-subtle">
              {r.enabled ? "enabled" : "disabled"}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
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
