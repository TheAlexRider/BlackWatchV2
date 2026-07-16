"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type {
  PerfAlertRule,
  PerfAlertInstance,
  PerfAlertChannel,
  PerfMetric,
  PerfComparison,
  PerfSeverity,
} from "@/lib/types";
import { DataPanel } from "@/components/layout/DataPanel";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { SelectableCard } from "@/components/ui/SelectableCard";
import { Disclosure } from "@/components/ui/Disclosure";
import { SeverityChip } from "@/components/ui/SeverityChip";
import { ReviewGrid, ReviewLabel, ReviewValue } from "@/components/ui/ReviewGrid";
import { FormSection, FieldStack } from "@/components/ui/FormSection";
import { TemplateEditor } from "@/components/domain/notifications/TemplateEditor";

const PERF_TEMPLATE_VARIABLES = [
  { name: "Hostname",       path: "hostname",       example: "Dev-NAT" },
  { name: "Instance",       path: "instance_id",    example: "i-08ba0757a3aa1c5e0" },
  { name: "Metric",         path: "metric_label",   example: "CPU load (normalized)" },
  { name: "Threshold %",    path: "threshold",      example: "80" },
  { name: "Current %",      path: "current_value",  example: "92.3" },
  { name: "Window (min)",   path: "window_minutes", example: "15" },
  { name: "Severity",       path: "severity",       example: "high" },
  { name: "Rule name",      path: "rule_name",      example: "CPU > 80% prod" },
  { name: "Env tag",        path: "tags.env",       example: "prod" },
] as const;

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
    <form action={action} className="space-y-8">
      <input type="hidden" name="module" value="ec2.host" />
      <input type="hidden" name="scope" value={scope} />
      <input type="hidden" name="enabled" value="on" />
      <input type="hidden" name="name" value={effectiveName} />
      <input type="hidden" name="min_breach_ratio" value={String(breachRatio)} />

      <DataPanel scrollX={false}>
        <div className="divide-y divide-line-soft">
          {/* ============ Metric ========================================== */}
          <div className="p-6">
            <FormSection
              label="Metric"
              hint="What signal drives this alert."
            >
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                {METRIC_OPTIONS.map((m) => (
                  <SelectableCard
                    key={m.value}
                    type="radio"
                    name="metric"
                    value={m.value}
                    checked={metric === m.value}
                    onChange={() => setMetric(m.value)}
                    title={m.label}
                    description={m.blurb}
                  />
                ))}
              </div>
            </FormSection>
          </div>

          {/* ============ Trigger ========================================= */}
          <div className="p-6">
            <FormSection
              label="Trigger"
              hint="Fire when the metric holds above the threshold long enough."
            >
              <div className="space-y-3 text-sm">
                <div className="flex items-center gap-2">
                  <span className="text-fg-muted">Fire when value</span>
                  <NativeSelect
                    name="comparison"
                    defaultValue={rule?.comparison ?? "gte"}
                    className="w-24"
                    aria-label="Comparison operator"
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
                    aria-label="Threshold value"
                  />
                  <span className="text-fg-muted">%</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-fg-muted">Sustained for at least</span>
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
                    aria-label="Window minutes"
                  />
                  <span className="text-fg-muted">minutes</span>
                </div>
              </div>
            </FormSection>
          </div>

          {/* ============ Where =========================================== */}
          <div className="p-6">
            <FormSection
              label="Where"
              hint="Scope this rule to one instance or a fleet by tag."
            >
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <SelectableCard
                  type="radio"
                  name="scope_ui"
                  value="instance"
                  checked={scope === "instance"}
                  onChange={() => setScope("instance")}
                  title="A specific instance"
                  description="One box, pinned by instance id."
                />
                <SelectableCard
                  type="radio"
                  name="scope_ui"
                  value="tag"
                  checked={scope === "tag"}
                  onChange={() => setScope("tag")}
                  title="Instances matching a tag"
                  description="Fleet-wide — any host with this tag pair."
                />
              </div>
              <div className="mt-3">
                {scope === "instance" ? (
                  <>
                    <NativeSelect
                      name="instance_id"
                      value={instanceId}
                      onChange={(e) => setInstanceId(e.target.value)}
                      className="w-full"
                      aria-label="Instance"
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
                      aria-label="Tag"
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
            </FormSection>
          </div>

          {/* ============ Deliver to ====================================== */}
          <div className="p-6">
            <FormSection
              label="Deliver to"
              hint="Fires on every matching heartbeat. Pick one or more."
            >
              {enabledChannels.length === 0 ? (
                <p className="text-sm text-fg-muted">
                  No enabled channels.{" "}
                  <Link
                    href="/notifications/channels/new"
                    className="text-sig-teal hover:underline"
                  >
                    Create one first.
                  </Link>
                </p>
              ) : (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {enabledChannels.map((c) => {
                    const checked = selectedChannels.includes(c.name);
                    return (
                      <SelectableCard
                        key={c.name}
                        type="checkbox"
                        name="channels"
                        value={c.name}
                        checked={checked}
                        onChange={(next) => {
                          setSelectedChannels((prev) =>
                            next
                              ? [...prev, c.name]
                              : prev.filter((x) => x !== c.name),
                          );
                        }}
                        title={
                          <span className="flex items-center gap-2">
                            <span>{c.name}</span>
                            <code className="rounded border border-line-soft px-1 py-px font-mono text-[9px] uppercase tracking-wider text-fg-subtle">
                              {c.type}
                            </code>
                          </span>
                        }
                      />
                    );
                  })}
                </div>
              )}
              {disabledChannelsCount > 0 && (
                <p className="mt-2 text-[11px] text-fg-subtle">
                  {disabledChannelsCount} disabled channel
                  {disabledChannelsCount === 1 ? "" : "s"} hidden.
                </p>
              )}
            </FormSection>
          </div>

          {/* ============ Advanced (collapsed) ============================ */}
          <div className="p-6">
            <Disclosure label="Advanced — severity, cooldown, breach sensitivity">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <FieldStack label="Severity">
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
                </FieldStack>
                <FieldStack
                  label="Cooldown (min)"
                  hint="Silence duplicate fires after the first alert."
                >
                  <Input
                    type="number"
                    name="throttle_minutes"
                    min={0}
                    max={1440}
                    step="1"
                    value={throttleMinutes}
                    onChange={(e) => setThrottleMinutes(Number(e.target.value))}
                    className="w-full"
                  />
                </FieldStack>
                <FieldStack
                  label={`Breach sensitivity — ${breachPct}%`}
                  hint="Lower = looser (one spike is enough). Higher = strict (sustained breach)."
                >
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
                    aria-label={`Breach sensitivity, ${breachPct} percent`}
                  />
                </FieldStack>
              </div>
            </Disclosure>
          </div>

          {/* ============ Custom message (collapsed) ====================== */}
          <div className="p-6">
            <Disclosure
              label="Custom message — override the default alert body"
              defaultOpen={!!rule?.message_template}
            >
              <TemplateEditor
                name="message_template"
                channelType="slack"
                defaultValue={rule?.message_template ?? ""}
                variables={[...PERF_TEMPLATE_VARIABLES]}
                hidePresets
                hideLivePreview
              />
              <p className="mt-2 text-[11px] leading-snug text-fg-subtle">
                Bad Jinja syntax falls back to the default line — templates never
                break delivery.
              </p>
            </Disclosure>
          </div>

          {/* ============ Name ============================================ */}
          <div className="p-6">
            <FormSection
              label="Name"
              hint="Auto-generated from the rule shape. Override to rename."
            >
              <Input
                type="text"
                placeholder={suggestedName || "auto-generated from rule"}
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full"
              />
              <p className="mt-2 text-[11px] text-fg-subtle">
                Saved as: <span className="font-mono text-fg">{effectiveName}</span>
              </p>
            </FormSection>
          </div>
        </div>
      </DataPanel>

      {/* ============ Review ============================================== */}
      <DataPanel className="space-y-4 p-6" scrollX={false}>
        <div>
          <h2 className="text-sm text-fg">Review your alert</h2>
          <p className="mt-0.5 text-xs text-fg-muted">
            Make sure everything looks right, then save.
          </p>
        </div>

        <ReviewGrid>
          <ReviewLabel>Metric</ReviewLabel>
          <ReviewValue className="text-fg">{metricLabel}</ReviewValue>

          <ReviewLabel>Trigger</ReviewLabel>
          <ReviewValue className="font-mono text-xs text-fg-muted">
            {opText} <span className="text-fg">{threshold}%</span>{" "}
            for <span className="text-fg">{windowMinutes} min</span>
            <span className="text-fg-subtle"> · {breachPct}% of samples must breach</span>
          </ReviewValue>

          <ReviewLabel>Where</ReviewLabel>
          <ReviewValue className="font-mono text-xs text-fg-muted">{previewScope}</ReviewValue>

          <ReviewLabel>Severity</ReviewLabel>
          <ReviewValue>
            <SeverityChip severity={rule?.severity ?? "high"} />
          </ReviewValue>

          <ReviewLabel>Channels</ReviewLabel>
          <ReviewValue className="font-mono text-xs text-fg-muted">
            {selectedChannels.length > 0
              ? selectedChannels.map((c, i) => (
                  <span key={c}>
                    {i > 0 && ", "}
                    <span className="text-fg-subtle">&rarr; </span>
                    {c}
                  </span>
                ))
              : "—"}
          </ReviewValue>

          <ReviewLabel>Cooldown</ReviewLabel>
          <ReviewValue className="font-mono text-xs text-fg-muted">
            {throttleMinutes} min after firing
          </ReviewValue>

          <ReviewLabel>Message</ReviewLabel>
          <ReviewValue className="text-xs text-fg-muted">
            {rule?.message_template ? (
              <span className="text-fg">Custom template for this rule</span>
            ) : (
              <span className="text-fg-muted">Uses the default line</span>
            )}
          </ReviewValue>

          {!formValid && (
            <>
              <ReviewLabel>
                <span className="text-sev-medium">Missing</span>
              </ReviewLabel>
              <ReviewValue className="text-xs text-sev-medium">
                Pick a scope and at least one channel before saving.
              </ReviewValue>
            </>
          )}
        </ReviewGrid>
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

function labelFor(i: PerfAlertInstance): string {
  const tag = i.tags?.role ?? i.tags?.env;
  const hostname = i.hostname ?? "";
  return [i.instance_id, hostname, tag].filter(Boolean).join("  ·  ");
}
