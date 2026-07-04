"use client";

import clsx from "clsx";
import { useActionState, useEffect, useState } from "react";
import { CheckCircle2, Cpu, HardDrive, Loader2, MemoryStick, XCircle } from "lucide-react";

import type {
  PerfQuickCard,
  PerfQuickExistingRule,
  PerfQuickResponse,
} from "@/lib/types";
import { DataPanel } from "@/components/layout/DataPanel";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

import { savePerfQuickAction, type ActionResult } from "./actions";

const METRIC_ICONS: Record<string, React.ComponentType<{ size?: number }>> = {
  memory_pct: MemoryStick,
  cpu_load_norm: Cpu,
  disk_pct_max: HardDrive,
};

export function MetricCard({
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
  const Icon = METRIC_ICONS[card.metric] ?? Cpu;

  const existing: PerfQuickExistingRule | undefined = card.existing[0];
  const isLive = !!existing && existing.enabled;
  const currentThreshold = existing?.threshold ?? card.default_threshold;
  const currentWindowMin = existing
    ? Math.max(1, Math.round(existing.window_seconds / 60))
    : card.default_window_minutes;
  const currentScope: "all" | "instance" = existing?.instance_id ? "instance" : "all";
  const currentInstance = existing?.instance_id ?? "";
  const currentChannel = existing?.channels?.[0] ?? "";
  const currentSeverity = existing?.severity ?? card.default_severity;

  const [state, dispatch, pending] = useActionState<ActionResult, FormData>(
    savePerfQuickAction,
    null,
  );

  return (
    <DataPanel className="p-0">
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
            <div className="font-mono text-[10px] text-fg-subtle">{card.metric}</div>
          </div>
        </div>
        {existing ? (
          <StatePill enabled={existing.enabled} />
        ) : (
          <span className="text-xs text-fg-subtle">not set up</span>
        )}
      </div>

      <div className="px-4 pt-3 text-xs text-fg-muted">{card.blurb}</div>

      {/* Existing rules for this metric — flag duplicates so the user
          doesn't stack another one accidentally. */}
      {card.existing.length > 1 && (
        <ExistingRulesNote rules={card.existing} />
      )}

      <form action={dispatch} className="space-y-3 px-4 pb-3 pt-3">
        <input type="hidden" name="metric" value={card.metric} />

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              Alert when &gt;=
            </label>
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
          </div>
          <div className="space-y-1.5">
            <label className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              For at least
            </label>
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
          </div>
        </div>

        <div className="space-y-1.5">
          <label className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            On
          </label>
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
        </div>

        <div className="space-y-1.5">
          <label className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            Send alerts to
          </label>
          <NativeSelect
            name="channel"
            defaultValue={currentChannel}
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
            Severity
          </label>
          <NativeSelect name="severity" defaultValue={currentSeverity} className="w-32">
            <option value="informational">informational</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="critical">critical</option>
          </NativeSelect>
        </div>

        <input
          type="hidden"
          name="enabled"
          value={existing?.enabled === false ? "off" : "on"}
        />

        <div className="flex justify-end gap-2 pt-1">
          <Button
            type="submit"
            size="sm"
            variant="primary"
            disabled={disabled || pending}
          >
            {pending ? (
              <>
                <Loader2 size={12} className="animate-spin" />
                <span>Saving…</span>
              </>
            ) : (
              "Save"
            )}
          </Button>
        </div>
      </form>

      {state && <InlineStatus status={state} />}
    </DataPanel>
  );
}

function InlineStatus({ status }: { status: NonNullable<ActionResult> }) {
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

function ExistingRulesNote({ rules }: { rules: PerfQuickExistingRule[] }) {
  // Show ALL existing rules for this metric so the user knows there are
  // other scopes / thresholds already set. Editing the first one only
  // updates that specific scope.
  return (
    <details className="mx-4 mt-3 border border-sev-medium/30 bg-sev-medium/5 px-3 py-2 text-xs">
      <summary className="cursor-pointer text-fg-muted">
        <span className="text-sev-medium">⚠</span> {rules.length} rules already
        exist for this metric — click to review
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
                @ {r.threshold}% · {Math.max(1, Math.round(r.window_seconds / 60))}m
                {r.instance_id ? ` · ${r.instance_id}` : " · all hosts"}
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

function StatePill({ enabled }: { enabled: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        aria-hidden
        className={clsx(
          "h-1.5 w-1.5 rounded-full",
          enabled ? "bg-sev-resolved" : "bg-fg-subtle",
        )}
      />
      <span className="text-fg-muted">{enabled ? "on" : "off"}</span>
    </span>
  );
}
