"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import clsx from "clsx";

import type {
  PerfAlertRule,
  PerfAlertInstance,
  PerfAlertChannel,
  PerfMetric,
  PerfComparison,
  PerfSeverity,
} from "@/lib/types";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";

const METRIC_OPTIONS: Array<{
  value: PerfMetric;
  label: string;
  blurb: string;
}> = [
  {
    value: "memory_pct",
    label: "Memory used %",
    blurb: "Reports the percentage of total RAM in use right now.",
  },
  {
    value: "cpu_load_norm",
    label: "CPU load (normalized)",
    blurb:
      "1-minute load average divided by CPU count, expressed as a percentage. 100% = fully utilized.",
  },
  {
    value: "disk_pct_max",
    label: "Disk used % (worst mount)",
    blurb: "Highest used % across all mounted filesystems on the host.",
  },
];

const SEVERITIES: PerfSeverity[] = [
  "informational",
  "low",
  "medium",
  "high",
  "critical",
];

// Tag scope: collect unique k=v pairs the operator might want to target.
function uniqueTagPairs(instances: PerfAlertInstance[]): string[] {
  const set = new Set<string>();
  for (const i of instances) {
    if (!i.tags) continue;
    for (const [k, v] of Object.entries(i.tags)) {
      if (k && v != null) set.add(`${k}=${v}`);
    }
  }
  return Array.from(set).sort();
}

export function PerfAlertForm({
  mode,
  rule,
  instances,
  channels,
  action,
}: {
  mode: "create" | "edit";
  rule?: PerfAlertRule;
  instances: PerfAlertInstance[];
  channels: PerfAlertChannel[];
  action: (fd: FormData) => Promise<void>;
}) {
  // initial state — prefill from rule on edit
  const initialScope: "instance" | "tag" = rule?.tag_key ? "tag" : "instance";
  const [scope, setScope] = useState<"instance" | "tag">(initialScope);
  const [metric, setMetric] = useState<PerfMetric>(
    (rule?.metric as PerfMetric) ?? "memory_pct",
  );
  const [threshold, setThreshold] = useState<number>(rule?.threshold ?? 80);
  const [windowMinutes, setWindowMinutes] = useState<number>(
    Math.max(1, Math.round((rule?.window_seconds ?? 300) / 60)),
  );
  const [throttleMinutes, setThrottleMinutes] = useState<number>(
    Math.max(0, Math.round((rule?.throttle_seconds ?? 1800) / 60)),
  );
  const [breachRatio, setBreachRatio] = useState<number>(
    rule?.min_breach_ratio ?? 0.6,
  );
  const [messageTemplate, setMessageTemplate] = useState<string>(
    rule?.message_template ?? "",
  );
  const [advancedOpen, setAdvancedOpen] = useState<boolean>(false);
  const [templateOpen, setTemplateOpen] = useState<boolean>(
    !!rule?.message_template,
  );
  const [instanceId, setInstanceId] = useState<string>(rule?.instance_id ?? "");
  const [tagSpec, setTagSpec] = useState<string>(
    rule?.tag_key && rule?.tag_value != null
      ? `${rule.tag_key}=${rule.tag_value}`
      : "",
  );
  const [name, setName] = useState<string>(rule?.name ?? "");
  const [selectedChannels, setSelectedChannels] = useState<string[]>(
    rule?.channels ?? [],
  );

  const tagPairs = useMemo(() => uniqueTagPairs(instances), [instances]);

  // Auto-suggest name when user hasn't typed one. Omit scope entirely if
  // not yet picked instead of splicing a "(pick …)" placeholder mid-string.
  const suggestedName = useMemo(() => {
    const metricLabel = METRIC_OPTIONS.find((m) => m.value === metric)?.label ?? metric;
    const opText =
      { gte: "≥", gt: ">", lte: "≤", lt: "<" }[rule?.comparison ?? "gte"] ?? "≥";
    const scopeLabel =
      scope === "instance"
        ? instanceId
          ? instances.find((i) => i.instance_id === instanceId)?.hostname ?? instanceId
          : null
        : tagSpec.includes("=")
          ? tagSpec
          : null;
    const base = `${metricLabel} ${opText} ${threshold}% for ${windowMinutes}m`;
    return scopeLabel ? `${base} on ${scopeLabel}` : base;
  }, [metric, scope, instanceId, tagSpec, threshold, windowMinutes, instances, rule?.comparison]);

  const effectiveName = name.trim() || suggestedName;

  const scopeValid =
    (scope === "instance" && instanceId.trim() !== "") ||
    (scope === "tag" && tagSpec.includes("=") && tagSpec.split("=")[1].trim() !== "");
  const channelValid = selectedChannels.length > 0;
  const formValid = scopeValid && channelValid && threshold > 0 && windowMinutes >= 1;

  const enabledChannels = channels.filter((c) => c.enabled);
  const disabledChannelsCount = channels.length - enabledChannels.length;

  const breachPct = Math.round(breachRatio * 100);
  const opText =
    { gte: "≥", gt: ">", lte: "≤", lt: "<" }[rule?.comparison ?? "gte"] ??
    "≥";
  const previewScope =
    scope === "instance"
      ? instanceId
        ? instances.find((i) => i.instance_id === instanceId)?.hostname ??
          instanceId
        : "(no instance)"
      : tagSpec.includes("=")
        ? tagSpec
        : "(no tag)";
  const metricLabel =
    METRIC_OPTIONS.find((m) => m.value === metric)?.label ?? metric;

  return (
    <form action={action} className="space-y-5">
      {/* fixed values the action still expects */}
      <input type="hidden" name="module" value="ec2.host" />
      <input type="hidden" name="scope" value={scope} />
      <input type="hidden" name="enabled" value="on" />
      <input type="hidden" name="name" value={effectiveName} />
      <input type="hidden" name="min_breach_ratio" value={String(breachRatio)} />

      <DataPanel className="space-y-5 p-5">
        {/* ============ Metric (compact cards) ============================ */}
        <div className="space-y-2">
          <SectionLabel>Metric</SectionLabel>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {METRIC_OPTIONS.map((m) => {
              const active = metric === m.value;
              return (
                <label
                  key={m.value}
                  className={clsx(
                    "cursor-pointer rounded border p-3 transition-colors",
                    active
                      ? "border-sig-teal bg-surface-2"
                      : "border-line-soft hover:border-fg-subtle",
                  )}
                >
                  <input
                    type="radio"
                    name="metric"
                    value={m.value}
                    checked={active}
                    onChange={() => setMetric(m.value)}
                    className="sr-only"
                  />
                  <div className="text-sm text-fg">{m.label}</div>
                  <div className="mt-1 text-[11px] leading-snug text-fg-subtle">
                    {m.blurb}
                  </div>
                </label>
              );
            })}
          </div>
        </div>

        {/* ============ Trigger (single row, sentence-shape) ============== */}
        <div className="space-y-2">
          <SectionLabel>Trigger</SectionLabel>
          <div className="flex flex-wrap items-center gap-2 rounded border border-line-soft bg-canvas px-3 py-2.5 text-sm">
            <span className="text-fg-muted">Fire when value</span>
            <NativeSelect
              name="comparison"
              defaultValue={rule?.comparison ?? "gte"}
              className="w-28"
            >
              <option value="gte">≥</option>
              <option value="gt">&gt;</option>
              <option value="lte">≤</option>
              <option value="lt">&lt;</option>
            </NativeSelect>
            <Input
              type="number"
              name="threshold"
              min={0}
              max={100}
              step="0.1"
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="w-20 text-right"
              required
            />
            <span className="text-fg-muted">% for at least</span>
            <Input
              type="number"
              name="window_minutes"
              min={1}
              max={1440}
              step="1"
              value={windowMinutes}
              onChange={(e) => setWindowMinutes(Number(e.target.value))}
              className="w-20 text-right"
              required
            />
            <span className="text-fg-muted">min</span>
          </div>
        </div>

        {/* ============ Scope (radio + one selector) ====================== */}
        <div className="space-y-2">
          <SectionLabel>Where</SectionLabel>
          <div className="rounded border border-line-soft bg-canvas p-3">
            <div className="mb-2 flex gap-4 text-sm">
              <RadioOption
                checked={scope === "instance"}
                onChange={() => setScope("instance")}
                label="A specific instance"
              />
              <RadioOption
                checked={scope === "tag"}
                onChange={() => setScope("tag")}
                label="All instances matching a tag"
              />
            </div>
            {scope === "instance" ? (
              <>
                <NativeSelect
                  name="instance_id"
                  value={instanceId}
                  onChange={(e) => setInstanceId(e.target.value)}
                  className="w-full"
                >
                  <option value="">— choose instance —</option>
                  {instances.map((i) => (
                    <option key={i.instance_id} value={i.instance_id}>
                      {labelFor(i)}
                    </option>
                  ))}
                </NativeSelect>
                {instances.length === 0 && (
                  <p className="mt-1 text-[11px] text-fg-subtle">
                    No instances reporting. Install the EC2 agent first.
                  </p>
                )}
              </>
            ) : (
              <>
                <NativeSelect
                  name="tag_spec"
                  value={tagSpec}
                  onChange={(e) => setTagSpec(e.target.value)}
                  className="w-full"
                >
                  <option value="">— choose tag —</option>
                  {tagPairs.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </NativeSelect>
                {tagPairs.length === 0 && (
                  <p className="mt-1 text-[11px] text-fg-subtle">
                    No tags discovered. Set{" "}
                    <code>BLACKWATCH_TAGS=env=prod,role=api</code> on the
                    agent (systemd env var) and reinstall.
                  </p>
                )}
              </>
            )}
          </div>
        </div>

        {/* ============ Channels (checkboxes with type badges) ============ */}
        <div className="space-y-2">
          <SectionLabel>Deliver to</SectionLabel>
          <div className="rounded border border-line-soft bg-canvas p-1">
            {enabledChannels.length === 0 ? (
              <p className="p-3 text-sm text-fg-muted">
                No enabled channels.{" "}
                <Link
                  href="/notifications/channels/new"
                  className="text-signal hover:underline"
                >
                  Create one first.
                </Link>
              </p>
            ) : (
              enabledChannels.map((c) => {
                const checked = selectedChannels.includes(c.name);
                return (
                  <label
                    key={c.name}
                    className={clsx(
                      "flex cursor-pointer items-center gap-3 rounded px-3 py-2 text-sm transition-colors",
                      checked ? "bg-surface-2 text-fg" : "text-fg-muted hover:bg-surface-2",
                    )}
                  >
                    <input
                      type="checkbox"
                      name="channels"
                      value={c.name}
                      checked={checked}
                      onChange={(e) => {
                        setSelectedChannels((prev) =>
                          e.target.checked
                            ? [...prev, c.name]
                            : prev.filter((x) => x !== c.name),
                        );
                      }}
                      className="accent-signal"
                    />
                    <span className="flex-1">{c.name}</span>
                    <code className="rounded border border-line-soft px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-fg-subtle">
                      {c.type}
                    </code>
                  </label>
                );
              })
            )}
          </div>
          {disabledChannelsCount > 0 && (
            <p className="text-[11px] text-fg-subtle">
              {disabledChannelsCount} disabled channel
              {disabledChannelsCount === 1 ? "" : "s"} hidden.
            </p>
          )}
        </div>

        {/* ============ Advanced (collapsed by default) =================== */}
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => setAdvancedOpen((s) => !s)}
            className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.09em] text-fg-subtle transition-colors hover:text-fg"
          >
            <span
              className={clsx(
                "inline-block transition-transform",
                advancedOpen && "rotate-90",
              )}
            >
              ▸
            </span>
            Advanced (severity, cooldown, breach sensitivity)
          </button>
          {advancedOpen && (
            <div className="grid grid-cols-1 gap-3 rounded border border-line-soft bg-canvas p-3 sm:grid-cols-3">
              <label className="space-y-1">
                <span className="text-[11px] uppercase tracking-wider text-fg-subtle">
                  Severity
                </span>
                <NativeSelect
                  name="severity"
                  defaultValue={rule?.severity ?? "high"}
                  className="w-full"
                >
                  {SEVERITIES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </NativeSelect>
              </label>
              <label className="space-y-1">
                <span className="text-[11px] uppercase tracking-wider text-fg-subtle">
                  Cooldown (min)
                </span>
                <Input
                  type="number"
                  name="throttle_minutes"
                  min={0}
                  max={1440}
                  step="1"
                  value={throttleMinutes}
                  onChange={(e) =>
                    setThrottleMinutes(Number(e.target.value))
                  }
                  className="w-full"
                />
                <span className="block text-[10px] leading-tight text-fg-subtle">
                  Silence duplicate fires after the first alert.
                </span>
              </label>
              <label className="space-y-1">
                <span className="text-[11px] uppercase tracking-wider text-fg-subtle">
                  Breach sensitivity ({breachPct}%)
                </span>
                <input
                  type="range"
                  min={30}
                  max={100}
                  step={5}
                  value={breachPct}
                  onChange={(e) =>
                    setBreachRatio(Number(e.target.value) / 100)
                  }
                  className="w-full accent-sig-teal"
                />
                <span className="block text-[10px] leading-tight text-fg-subtle">
                  Fire when {breachPct}%+ of samples in the window breach.
                  Lower = looser, higher = strict.
                </span>
              </label>
            </div>
          )}
        </div>

        {/* ============ Custom message (optional) ========================= */}
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => setTemplateOpen((s) => !s)}
            className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.09em] text-fg-subtle transition-colors hover:text-fg"
          >
            <span
              className={clsx(
                "inline-block transition-transform",
                templateOpen && "rotate-90",
              )}
            >
              ▸
            </span>
            Custom message (optional)
          </button>
          {templateOpen && (
            <div className="space-y-2 rounded border border-line-soft bg-canvas p-3">
              <textarea
                name="message_template"
                value={messageTemplate}
                onChange={(e) => setMessageTemplate(e.target.value)}
                rows={4}
                placeholder="Leave blank for the default: 'Memory used % ≥ 80% for 15m (current: 92.3%)'"
                className="w-full rounded border border-line-soft bg-surface-1 px-2 py-1.5 font-mono text-xs text-fg placeholder:text-fg-disabled focus:border-sig-teal focus:outline-none"
              />
              <p className="text-[10px] leading-snug text-fg-subtle">
                Jinja template. Available fields:{" "}
                <code className="text-fg-muted">{"{{ hostname }}"}</code>{" "}
                <code className="text-fg-muted">{"{{ instance_id }}"}</code>{" "}
                <code className="text-fg-muted">{"{{ metric_label }}"}</code>{" "}
                <code className="text-fg-muted">{"{{ threshold }}"}</code>{" "}
                <code className="text-fg-muted">{"{{ current_value }}"}</code>{" "}
                <code className="text-fg-muted">{"{{ window_minutes }}"}</code>{" "}
                <code className="text-fg-muted">{"{{ severity }}"}</code>{" "}
                <code className="text-fg-muted">{"{{ rule_name }}"}</code>{" "}
                <code className="text-fg-muted">{"{{ tags.env }}"}</code>. If
                the template errors, we fall back to the default line — bad
                syntax will never break delivery.
              </p>
            </div>
          )}
          {/* Always submit the field (empty string when collapsed/blank
              persists NULL server-side). */}
          {!templateOpen && (
            <input type="hidden" name="message_template" value="" />
          )}
        </div>

        {/* ============ Name + preview ==================================== */}
        <div className="space-y-2 border-t border-line-soft pt-4">
          <SectionLabel>Name</SectionLabel>
          <Input
            type="text"
            placeholder={suggestedName || "auto-generated from rule"}
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full"
          />
          <p className="text-[11px] text-fg-subtle">
            Saved as: <span className="font-mono text-fg">{effectiveName}</span>
          </p>
        </div>

        {/* ============ Live rule preview ================================= */}
        <div className="rounded border border-sig-teal/40 bg-surface-2 px-3 py-2.5 text-[12px] leading-snug text-fg-muted">
          <div className="mb-1 text-[10px] uppercase tracking-[0.09em] text-sig-teal">
            Preview
          </div>
          {formValid ? (
            <>
              Fire a{" "}
              <span className="text-fg">
                {(rule?.severity ?? "high")}
              </span>{" "}
              alert on{" "}
              <span className="font-mono text-fg">
                {selectedChannels.join(", ")}
              </span>{" "}
              when{" "}
              <span className="text-fg">{metricLabel}</span> {opText}{" "}
              <span className="text-fg">{threshold}%</span> on{" "}
              <span className="font-mono text-fg">{previewScope}</span> for at
              least <span className="text-fg">{windowMinutes} min</span>{" "}
              ({breachPct}% of samples must breach). Silence duplicates for{" "}
              <span className="text-fg">{throttleMinutes} min</span>.
            </>
          ) : (
            <span className="text-fg-subtle">
              Pick a scope and at least one channel to see the summary.
            </span>
          )}
        </div>
      </DataPanel>

      <div className="flex items-center justify-end gap-2">
        <Button asChild variant="ghost" size="sm">
          <Link href="/notifications">Cancel</Link>
        </Button>
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={!formValid}
        >
          {mode === "create" ? "Create alert" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}

// ---------- subcomponents ---------------------------------------------------

function RadioOption({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2">
      <input
        type="radio"
        checked={checked}
        onChange={onChange}
        className="accent-signal"
      />
      <span className={clsx("text-sm", checked ? "text-fg" : "text-fg-muted")}>
        {label}
      </span>
    </label>
  );
}

function labelFor(i: PerfAlertInstance): string {
  const tag = i.tags?.role ?? i.tags?.env;
  const hostname = i.hostname ?? "";
  return [i.instance_id, hostname, tag].filter(Boolean).join("  ·  ");
}
