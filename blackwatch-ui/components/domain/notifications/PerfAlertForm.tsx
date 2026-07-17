"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Check } from "lucide-react";

import type {
  PerfAlertRule,
  PerfAlertInstance,
  PerfAlertChannel,
  PerfMetric,
  PerfComparison,
  PerfSeverity,
} from "@/lib/types";
import { hostLabel, type PerfPreviewContext } from "@/lib/api";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { SelectableCard } from "@/components/ui/SelectableCard";
import { Disclosure } from "@/components/ui/Disclosure";
import { SeverityChip } from "@/components/ui/SeverityChip";
import { ReviewGrid, ReviewLabel, ReviewValue } from "@/components/ui/ReviewGrid";
import { FieldStack } from "@/components/ui/FormSection";
import { Wizard, WizardStepHeader } from "@/components/ui/WizardShell";
import { TemplateEditor } from "@/components/domain/notifications/TemplateEditor";
import { TestSendButton } from "@/components/domain/notifications/TestSendButton";

// Flat vars the perf-alert render exposes. Passed to TemplateEditor so the
// chip picker offers the right vocabulary — hostname, threshold, current_value,
// etc — instead of the event-shaped defaults.
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
      "1-minute load average divided by CPU count. 100% = fully utilized.",
  },
  {
    value: "disk_pct_max",
    label: "Disk used % (worst mount)",
    blurb: "Highest used % across all mounted filesystems.",
  },
];

const SEVERITIES: PerfSeverity[] = [
  "informational",
  "low",
  "medium",
  "high",
  "critical",
];

const WIZARD_STEPS = [
  { n: 1, label: "Metric" },
  { n: 2, label: "Trigger" },
  { n: 3, label: "Where" },
  { n: 4, label: "Channel" },
  { n: 5, label: "Message" },
  { n: 6, label: "Review" },
];

type Step = 1 | 2 | 3 | 4 | 5 | 6;

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

type Scope = "instance" | "instances" | "tag" | "all";

function initialScopeFor(rule?: PerfAlertRule): Scope {
  if (!rule) return "instance";
  if (rule.instance_ids && rule.instance_ids.length > 0) return "instances";
  if (rule.tag_key) return "tag";
  if (rule.instance_id) return "instance";
  return "all";
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
  // Edit mode jumps straight to Review — matches AlertWizard's behavior.
  const [step, setStep] = useState<Step>(rule ? 6 : 1);
  const [scope, setScope] = useState<Scope>(initialScopeFor(rule));
  const [instanceIds, setInstanceIds] = useState<string[]>(
    rule?.instance_ids ?? [],
  );
  const [metric, setMetric] = useState<PerfMetric>(
    (rule?.metric as PerfMetric) ?? "memory_pct",
  );
  const [comparison, setComparison] = useState<PerfComparison>(
    (rule?.comparison as PerfComparison) ?? "gte",
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
  const [severity, setSeverity] = useState<PerfSeverity>(
    (rule?.severity as PerfSeverity) ?? "high",
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
  const [templateValue, setTemplateValue] = useState<string>(
    rule?.message_template ?? "",
  );

  const tagPairs = useMemo(() => uniqueTagPairs(instances), [instances]);
  const enabledChannels = channels.filter((c) => c.enabled);
  const disabledChannelsCount = channels.length - enabledChannels.length;

  const suggestedName = useMemo(() => {
    const metricLabel = METRIC_OPTIONS.find((m) => m.value === metric)?.label ?? metric;
    const op = { gte: "≥", gt: ">", lte: "≤", lt: "<" }[comparison] ?? "≥";
    let scopeLabel: string | null = null;
    if (scope === "instance" && instanceId) {
      const i = instances.find((x) => x.instance_id === instanceId);
      scopeLabel = i ? hostLabel(i) : instanceId;
    } else if (scope === "instances" && instanceIds.length > 0) {
      scopeLabel = `${instanceIds.length} hosts`;
    } else if (scope === "tag" && tagSpec.includes("=")) {
      scopeLabel = tagSpec;
    } else if (scope === "all") {
      scopeLabel = "all hosts";
    }
    const base = `${metricLabel} ${op} ${threshold}% for ${windowMinutes}m`;
    return scopeLabel ? `${base} on ${scopeLabel}` : base;
  }, [metric, comparison, scope, instanceId, instanceIds, tagSpec, threshold, windowMinutes, instances]);

  const effectiveName = name.trim() || suggestedName;

  const scopeValid =
    scope === "all" ||
    (scope === "instance" && instanceId.trim() !== "") ||
    (scope === "instances" && instanceIds.length > 0) ||
    (scope === "tag" && tagSpec.includes("=") && tagSpec.split("=")[1].trim() !== "");
  const channelValid = selectedChannels.length > 0;
  const metricValid = !!metric;
  const triggerValid = threshold > 0 && windowMinutes >= 1;
  const formValid = metricValid && triggerValid && scopeValid && channelValid;

  const complete: Record<number, boolean> = {
    1: metricValid,
    2: triggerValid,
    3: scopeValid,
    4: channelValid,
    5: true,
  };
  const canGoTo = (n: Step): boolean => {
    if (n === 1) return true;
    if (n === 2) return complete[1];
    if (n === 3) return complete[1] && complete[2];
    if (n === 4) return complete[1] && complete[2] && complete[3];
    if (n === 5) return complete[1] && complete[2] && complete[3] && complete[4];
    if (n === 6) return complete[1] && complete[2] && complete[3] && complete[4];
    return false;
  };
  const canAdvance = complete[step];
  const isFinal = step === 6;

  const opText = { gte: "≥", gt: ">", lte: "≤", lt: "<" }[comparison] ?? "≥";
  const breachPct = Math.round(breachRatio * 100);
  const previewScope = (() => {
    if (scope === "all") return "all hosts";
    if (scope === "instance") {
      if (!instanceId) return "(no instance)";
      const i = instances.find((x) => x.instance_id === instanceId);
      return i ? hostLabel(i) : instanceId;
    }
    if (scope === "instances") {
      if (instanceIds.length === 0) return "(no instances)";
      const labels = instanceIds.map((id) => {
        const i = instances.find((x) => x.instance_id === id);
        return i ? hostLabel(i) : id;
      });
      if (labels.length <= 3) return labels.join(", ");
      return `${labels.slice(0, 3).join(", ")} +${labels.length - 3} more`;
    }
    return tagSpec.includes("=") ? tagSpec : "(no tag)";
  })();
  const metricLabel =
    METRIC_OPTIONS.find((m) => m.value === metric)?.label ?? metric;

  // For test-send we need a channel type. Perf-alerts fan out to N channels
  // of possibly different types — the button uses each channel's own configured
  // type (server looks it up), so we can leave channelType unset here.
  const firstEnabledChannel = enabledChannels.find((c) =>
    selectedChannels.includes(c.name),
  );

  // Build the live perf preview context from the wizard's form state so
  // preview + test-send show the exact rule being built (metric_label,
  // threshold, window, comparison, severity, scope). Scope flows through as
  // hostname/instance_id/tags so `{{ hostname }}` renders.
  const currentInstance = instances.find((i) => i.instance_id === instanceId);
  const firstMultiInstance = instances.find(
    (i) => instanceIds.length > 0 && i.instance_id === instanceIds[0],
  );
  const perfContext: PerfPreviewContext = useMemo(() => {
    const ctx: PerfPreviewContext = {
      metric,
      metric_label: metricLabel,
      threshold,
      window_minutes: windowMinutes,
      comparison,
      severity,
      rule_name: effectiveName,
    };
    // For each scope, pick a representative host so the preview has real
    // hostname/tags/instance_id to render. Multi-scope uses the first
    // selected instance; all-scope picks whatever's first in the list.
    let pick: PerfAlertInstance | undefined;
    if (scope === "instance") pick = currentInstance;
    else if (scope === "instances") pick = firstMultiInstance;
    else if (scope === "all") pick = instances[0];

    if (pick) {
      ctx.hostname = hostLabel(pick);
      ctx.instance_id = pick.instance_id;
      if (pick.tags && Object.keys(pick.tags).length > 0) {
        ctx.tags = pick.tags;
      }
    } else if (scope === "tag" && tagSpec.includes("=")) {
      const [k, ...vparts] = tagSpec.split("=");
      const v = vparts.join("=");
      if (k && v) ctx.tags = { [k]: v };
    }
    return ctx;
  }, [
    metric,
    metricLabel,
    threshold,
    windowMinutes,
    comparison,
    severity,
    effectiveName,
    scope,
    currentInstance,
    firstMultiInstance,
    instances,
    tagSpec,
  ]);

  return (
    <form action={action}>
      <input type="hidden" name="module" value="ec2.host" />
      <input type="hidden" name="scope" value={scope} />
      <input type="hidden" name="enabled" value="on" />
      <input type="hidden" name="name" value={effectiveName} />
      <input type="hidden" name="metric" value={metric} />
      <input type="hidden" name="comparison" value={comparison} />
      <input type="hidden" name="severity" value={severity} />
      <input type="hidden" name="min_breach_ratio" value={String(breachRatio)} />
      <input type="hidden" name="threshold" value={String(threshold)} />
      <input type="hidden" name="window_minutes" value={String(windowMinutes)} />
      <input type="hidden" name="throttle_minutes" value={String(throttleMinutes)} />
      {scope === "instance" && (
        <input type="hidden" name="instance_id" value={instanceId} />
      )}
      {scope === "instances" &&
        instanceIds.map((id) => (
          <input key={id} type="hidden" name="instance_ids" value={id} />
        ))}
      {scope === "tag" && (
        <input type="hidden" name="tag_spec" value={tagSpec} />
      )}
      {selectedChannels.map((c) => (
        <input key={c} type="hidden" name="channels" value={c} />
      ))}
      <input type="hidden" name="message_template" value={templateValue} />

      <Wizard
        backHref="/notifications"
        backLabel="back to notifications"
        title={mode === "edit" ? "Edit performance alert" : "Create performance alert"}
        subtitle={
          mode === "edit"
            ? "Change any part of this rule — threshold, scope, channels, message."
            : "Six steps: pick a metric, set the trigger, scope it, pick channels, tweak the message, then review."
        }
        steps={WIZARD_STEPS}
        current={step}
        completed={complete}
        onJump={(n) => canGoTo(n as Step) && setStep(n as Step)}
        onBack={() => setStep((s) => (s > 1 ? ((s - 1) as Step) : s))}
        onNext={() => setStep((s) => (s < 6 ? ((s + 1) as Step) : s))}
        canAdvance={canAdvance}
        isFinal={isFinal}
        finalNode={
          <Button
            type="submit"
            size="sm"
            variant="primary"
            disabled={!formValid}
          >
            <Check size={12} /> {mode === "edit" ? "Save changes" : "Create alert"}
          </Button>
        }
      >
        <div hidden={step !== 1}>
          <MetricStep metric={metric} onSelect={setMetric} />
        </div>
        <div hidden={step !== 2}>
          <TriggerStep
            comparison={comparison}
            onComparison={setComparison}
            threshold={threshold}
            onThreshold={setThreshold}
            windowMinutes={windowMinutes}
            onWindowMinutes={setWindowMinutes}
            severity={severity}
            onSeverity={setSeverity}
            throttleMinutes={throttleMinutes}
            onThrottleMinutes={setThrottleMinutes}
            breachPct={breachPct}
            onBreachPct={(p) => setBreachRatio(p / 100)}
          />
        </div>
        <div hidden={step !== 3}>
          <ScopeStep
            scope={scope}
            onScope={setScope}
            instanceId={instanceId}
            onInstanceId={setInstanceId}
            instanceIds={instanceIds}
            onInstanceIdsToggle={(id, next) =>
              setInstanceIds((prev) =>
                next ? [...prev, id] : prev.filter((x) => x !== id),
              )
            }
            onInstanceIdsSetAll={(all) =>
              setInstanceIds(all ? instances.map((i) => i.instance_id) : [])
            }
            instances={instances}
            tagSpec={tagSpec}
            onTagSpec={setTagSpec}
            tagPairs={tagPairs}
          />
        </div>
        <div hidden={step !== 4}>
          <ChannelStep
            enabledChannels={enabledChannels}
            disabledCount={disabledChannelsCount}
            selected={selectedChannels}
            onToggle={(name, next) =>
              setSelectedChannels((prev) =>
                next ? [...prev, name] : prev.filter((x) => x !== name),
              )
            }
          />
        </div>
        <div hidden={step !== 5}>
          <MessageStep
            channelType={firstEnabledChannel?.type ?? "slack"}
            defaultValue={rule?.message_template ?? ""}
            onValueChange={setTemplateValue}
            selectedChannels={selectedChannels}
            templateValue={templateValue}
            suggestedName={suggestedName}
            name={name}
            onName={setName}
            effectiveName={effectiveName}
            perfContext={perfContext}
          />
        </div>
        <div hidden={step !== 6}>
          <ReviewStep
            metricLabel={metricLabel}
            opText={opText}
            threshold={threshold}
            windowMinutes={windowMinutes}
            breachPct={breachPct}
            previewScope={previewScope}
            severity={severity}
            selectedChannels={selectedChannels}
            throttleMinutes={throttleMinutes}
            customTemplate={!!templateValue.trim()}
            effectiveName={effectiveName}
            channelType={firstEnabledChannel?.type ?? "slack"}
            templateValue={templateValue}
            formValid={formValid}
            perfContext={perfContext}
          />
        </div>
      </Wizard>
    </form>
  );
}

// =========================================================================
// Step 1 — Metric
// =========================================================================

function MetricStep({
  metric,
  onSelect,
}: {
  metric: PerfMetric;
  onSelect: (m: PerfMetric) => void;
}) {
  return (
    <div>
      <WizardStepHeader
        title="Which metric drives this alert?"
        subtitle="Pick the host signal you want to watch. All three come from every reporting EC2 agent."
      />
      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
        {METRIC_OPTIONS.map((m) => (
          <SelectableCard
            key={m.value}
            type="radio"
            name="metric-ui"
            value={m.value}
            checked={metric === m.value}
            onChange={() => onSelect(m.value)}
            title={m.label}
            description={m.blurb}
          />
        ))}
      </div>
    </div>
  );
}

// =========================================================================
// Step 2 — Trigger (threshold + window + advanced)
// =========================================================================

function TriggerStep({
  comparison,
  onComparison,
  threshold,
  onThreshold,
  windowMinutes,
  onWindowMinutes,
  severity,
  onSeverity,
  throttleMinutes,
  onThrottleMinutes,
  breachPct,
  onBreachPct,
}: {
  comparison: PerfComparison;
  onComparison: (c: PerfComparison) => void;
  threshold: number;
  onThreshold: (n: number) => void;
  windowMinutes: number;
  onWindowMinutes: (n: number) => void;
  severity: PerfSeverity;
  onSeverity: (s: PerfSeverity) => void;
  throttleMinutes: number;
  onThrottleMinutes: (n: number) => void;
  breachPct: number;
  onBreachPct: (n: number) => void;
}) {
  return (
    <div>
      <WizardStepHeader
        title="When should it fire?"
        subtitle="Set the comparison, threshold, and how long the metric must stay past it before you get paged."
      />

      <div className="space-y-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-fg-muted">Fire when value</span>
          <NativeSelect
            value={comparison}
            onChange={(e) => onComparison(e.target.value as PerfComparison)}
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
            min={0}
            max={100}
            step="0.1"
            value={threshold}
            onChange={(e) => onThreshold(Number(e.target.value))}
            className="w-24 text-right"
            required
            aria-label="Threshold value"
          />
          <span className="text-fg-muted">%</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-fg-muted">…sustained for at least</span>
          <Input
            type="number"
            min={1}
            max={1440}
            step="1"
            value={windowMinutes}
            onChange={(e) => onWindowMinutes(Number(e.target.value))}
            className="w-24 text-right"
            required
            aria-label="Window minutes"
          />
          <span className="text-fg-muted">minutes.</span>
        </div>
      </div>

      <div className="mt-6 border-t border-line-soft pt-5">
        <Disclosure label="Advanced — severity, cooldown, breach sensitivity">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <FieldStack label="Severity">
              <NativeSelect
                value={severity}
                onChange={(e) => onSeverity(e.target.value as PerfSeverity)}
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
                min={0}
                max={1440}
                step="1"
                value={throttleMinutes}
                onChange={(e) => onThrottleMinutes(Number(e.target.value))}
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
                onChange={(e) => onBreachPct(Number(e.target.value))}
                className="w-full accent-signal"
                aria-label={`Breach sensitivity, ${breachPct} percent`}
              />
            </FieldStack>
          </div>
        </Disclosure>
      </div>
    </div>
  );
}

// =========================================================================
// Step 3 — Scope (where)
// =========================================================================

function ScopeStep({
  scope,
  onScope,
  instanceId,
  onInstanceId,
  instanceIds,
  onInstanceIdsToggle,
  onInstanceIdsSetAll,
  instances,
  tagSpec,
  onTagSpec,
  tagPairs,
}: {
  scope: Scope;
  onScope: (s: Scope) => void;
  instanceId: string;
  onInstanceId: (id: string) => void;
  instanceIds: string[];
  onInstanceIdsToggle: (id: string, next: boolean) => void;
  onInstanceIdsSetAll: (all: boolean) => void;
  instances: PerfAlertInstance[];
  tagSpec: string;
  onTagSpec: (t: string) => void;
  tagPairs: string[];
}) {
  const allSelected =
    instances.length > 0 && instanceIds.length === instances.length;

  return (
    <div>
      <WizardStepHeader
        title="Where should this rule apply?"
        subtitle="One host, a set of hosts, everything with a tag, or the whole fleet. Instance names come from the hosts page; the ID is the fallback."
      />

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <SelectableCard
          type="radio"
          name="scope-ui"
          value="instance"
          checked={scope === "instance"}
          onChange={() => onScope("instance")}
          title="A specific instance"
          description="One host, pinned by name."
        />
        <SelectableCard
          type="radio"
          name="scope-ui"
          value="instances"
          checked={scope === "instances"}
          onChange={() => onScope("instances")}
          title="Multiple specific instances"
          description="Pick any set of hosts by name."
        />
        <SelectableCard
          type="radio"
          name="scope-ui"
          value="tag"
          checked={scope === "tag"}
          onChange={() => onScope("tag")}
          title="Instances matching a tag"
          description="Fleet-wide — every host with the tag pair."
        />
        <SelectableCard
          type="radio"
          name="scope-ui"
          value="all"
          checked={scope === "all"}
          onChange={() => onScope("all")}
          title="All instances"
          description="Every reporting host. Careful — this fires everywhere."
        />
      </div>

      <div className="mt-5">
        {scope === "instance" && (
          <>
            <p className="mb-1.5 text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              Instance
            </p>
            <NativeSelect
              value={instanceId}
              onChange={(e) => onInstanceId(e.target.value)}
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
              <p className="mt-2 text-[11px] text-fg-subtle">
                No instances reporting. Install the EC2 agent first.
              </p>
            )}
          </>
        )}

        {scope === "instances" && (
          <>
            <div className="mb-2 flex items-baseline justify-between">
              <p className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
                Instances ({instanceIds.length} selected)
              </p>
              {instances.length > 0 && (
                <button
                  type="button"
                  onClick={() => onInstanceIdsSetAll(!allSelected)}
                  className="text-[11px] text-signal hover:underline"
                >
                  {allSelected ? "Clear all" : "Select all"}
                </button>
              )}
            </div>
            {instances.length === 0 ? (
              <p className="text-[11px] text-fg-subtle">
                No instances reporting. Install the EC2 agent first.
              </p>
            ) : (
              <div className="grid max-h-72 grid-cols-1 gap-2 overflow-y-auto sm:grid-cols-2">
                {instances.map((i) => (
                  <SelectableCard
                    key={i.instance_id}
                    type="checkbox"
                    name="instance-multi-ui"
                    value={i.instance_id}
                    checked={instanceIds.includes(i.instance_id)}
                    onChange={(next) => onInstanceIdsToggle(i.instance_id, next)}
                    title={
                      <span className="flex items-center gap-2">
                        <span>{hostLabel(i)}</span>
                        {i.tags?.env && (
                          <code className="font-mono text-[10px] text-fg-subtle">
                            env={i.tags.env}
                          </code>
                        )}
                      </span>
                    }
                    description={
                      i.hostname && i.hostname !== hostLabel(i)
                        ? `${i.hostname} · ${i.instance_id}`
                        : i.instance_id
                    }
                  />
                ))}
              </div>
            )}
          </>
        )}

        {scope === "tag" && (
          <>
            <p className="mb-1.5 text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              Tag pair
            </p>
            <NativeSelect
              value={tagSpec}
              onChange={(e) => onTagSpec(e.target.value)}
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
              <p className="mt-2 text-[11px] text-fg-subtle">
                No tags discovered. Set{" "}
                <code>BLACKWATCH_TAGS=env=prod,role=api</code> on the agent
                (systemd env var) and reinstall.
              </p>
            )}
          </>
        )}

        {scope === "all" && (
          <div className="border border-sev-medium/30 bg-sev-medium/5 px-4 py-3 text-xs text-fg-muted">
            This rule will fire for every reporting host. Good for infra-wide
            SLOs (e.g. "any host at 95% memory"). For a smaller blast radius,
            pick a tag or a specific set of instances.
          </div>
        )}
      </div>
    </div>
  );
}

// =========================================================================
// Step 4 — Channel (deliver to)
// =========================================================================

function ChannelStep({
  enabledChannels,
  disabledCount,
  selected,
  onToggle,
}: {
  enabledChannels: PerfAlertChannel[];
  disabledCount: number;
  selected: string[];
  onToggle: (name: string, next: boolean) => void;
}) {
  return (
    <div>
      <WizardStepHeader
        title="Where should it be delivered?"
        subtitle="Pick one or more channels. The alert fans out to every one you select on every fire."
      />
      {enabledChannels.length === 0 ? (
        <div className="border border-sev-medium/30 bg-sev-medium/5 px-4 py-3 text-sm text-fg-muted">
          No enabled channels.{" "}
          <Link
            href="/notifications/channels/new"
            className="text-signal hover:underline"
          >
            Create one first →
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {enabledChannels.map((c) => (
            <SelectableCard
              key={c.name}
              type="checkbox"
              name="channels-ui"
              value={c.name}
              checked={selected.includes(c.name)}
              onChange={(next) => onToggle(c.name, next)}
              title={
                <span className="flex items-center gap-2">
                  <span>{c.name}</span>
                  <code className="border border-line-soft px-1 py-px font-mono text-[9px] uppercase tracking-wider text-fg-subtle">
                    {c.type}
                  </code>
                </span>
              }
            />
          ))}
        </div>
      )}
      {disabledCount > 0 && (
        <p className="mt-3 text-[11px] text-fg-subtle">
          {disabledCount} disabled channel
          {disabledCount === 1 ? "" : "s"} hidden.
        </p>
      )}
    </div>
  );
}

// =========================================================================
// Step 5 — Message (template + presets + preview + test-send + name)
// =========================================================================

function MessageStep({
  channelType,
  defaultValue,
  onValueChange,
  selectedChannels,
  templateValue,
  suggestedName,
  name,
  onName,
  effectiveName,
  perfContext,
}: {
  channelType: string;
  defaultValue: string;
  onValueChange: (v: string) => void;
  selectedChannels: string[];
  templateValue: string;
  suggestedName: string;
  name: string;
  onName: (n: string) => void;
  effectiveName: string;
  perfContext: PerfPreviewContext;
}) {
  return (
    <div>
      <WizardStepHeader
        title="Message + name"
        subtitle="Pick a preset or write your own template. Live preview shows the final message. Send-test delivers to the picked channels so you can see the exact alert land."
      />

      <TemplateEditor
        name="_perf_template"
        channelType={channelType}
        defaultValue={defaultValue}
        variables={[...PERF_TEMPLATE_VARIABLES]}
        contextKind="perf"
        perfContext={perfContext}
        onValueChange={onValueChange}
      />

      <p className="mt-2 text-[11px] leading-snug text-fg-subtle">
        Bad Jinja syntax falls back to the default line — templates never break
        delivery.
      </p>

      <div className="mt-6 border-t border-line-soft pt-5">
        <p className="mb-2 text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          Test-send this alert
        </p>
        <p className="mb-2.5 text-[11px] text-fg-subtle">
          Fires the exact rendered message through your picked channel
          {selectedChannels.length === 1 ? "" : "s"} with sample host data.
          Nothing gets saved — this is just a smoke check.
        </p>
        <TestSendButton
          channelNames={selectedChannels}
          template={templateValue}
          channelType={channelType}
          contextKind="perf"
          sampleEvent="perf_alert"
          perfContext={perfContext}
        />
      </div>

      <div className="mt-6 border-t border-line-soft pt-5">
        <p className="mb-1.5 text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          Name
        </p>
        <Input
          type="text"
          placeholder={suggestedName || "auto-generated from rule"}
          value={name}
          onChange={(e) => onName(e.target.value)}
          className="w-full"
        />
        <p className="mt-2 text-[11px] text-fg-subtle">
          Saved as: <span className="font-mono text-fg">{effectiveName}</span>
        </p>
      </div>
    </div>
  );
}

// =========================================================================
// Step 6 — Review
// =========================================================================

function ReviewStep({
  metricLabel,
  opText,
  threshold,
  windowMinutes,
  breachPct,
  previewScope,
  severity,
  selectedChannels,
  throttleMinutes,
  customTemplate,
  effectiveName,
  channelType,
  templateValue,
  formValid,
  perfContext,
}: {
  metricLabel: string;
  opText: string;
  threshold: number;
  windowMinutes: number;
  breachPct: number;
  previewScope: string;
  severity: PerfSeverity;
  selectedChannels: string[];
  throttleMinutes: number;
  customTemplate: boolean;
  effectiveName: string;
  channelType: string;
  templateValue: string;
  formValid: boolean;
  perfContext: PerfPreviewContext;
}) {
  return (
    <div>
      <WizardStepHeader
        title="Review your alert"
        subtitle="Make sure everything looks right, then save."
      />

      <ReviewGrid>
        <ReviewLabel>Name</ReviewLabel>
        <ReviewValue className="font-mono text-xs text-fg">{effectiveName}</ReviewValue>

        <ReviewLabel>Metric</ReviewLabel>
        <ReviewValue className="text-fg">{metricLabel}</ReviewValue>

        <ReviewLabel>Trigger</ReviewLabel>
        <ReviewValue className="font-mono text-xs text-fg-muted">
          {opText} <span className="text-fg">{threshold}%</span> for{" "}
          <span className="text-fg">{windowMinutes} min</span>
          <span className="text-fg-subtle">
            {" "}
            · {breachPct}% of samples must breach
          </span>
        </ReviewValue>

        <ReviewLabel>Where</ReviewLabel>
        <ReviewValue className="font-mono text-xs text-fg-muted">
          {previewScope}
        </ReviewValue>

        <ReviewLabel>Severity</ReviewLabel>
        <ReviewValue>
          <SeverityChip severity={severity} />
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
          {customTemplate ? (
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

      {selectedChannels.length > 0 && (
        <div className="mt-6 border-t border-line-soft pt-5">
          <p className="mb-1 text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            One-shot test
          </p>
          <p className="mb-2.5 text-[11px] text-fg-subtle">
            Fires the alert with sample data through every picked channel right
            now — same call the wizard uses in the Message step.
          </p>
          <TestSendButton
            channelNames={selectedChannels}
            template={templateValue}
            channelType={channelType}
            contextKind="perf"
            sampleEvent="perf_alert"
            perfContext={perfContext}
          />
        </div>
      )}
    </div>
  );
}

function labelFor(i: PerfAlertInstance): string {
  // Primary label: display_name > hostname > id. Tag suffix for disambiguation
  // when the same role is spread across env/prod/staging.
  const primary = hostLabel(i);
  const tag = i.tags?.role ?? i.tags?.env;
  const parts = [primary];
  if (i.hostname && i.hostname !== primary) parts.push(i.hostname);
  parts.push(i.instance_id);
  if (tag) parts.push(tag);
  return parts.filter(Boolean).join("  ·  ");
}
