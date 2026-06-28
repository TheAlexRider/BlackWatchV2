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

  // Auto-suggest name when user hasn't typed one.
  const suggestedName = useMemo(() => {
    const metricLabel = METRIC_OPTIONS.find((m) => m.value === metric)?.label ?? metric;
    const scopeLabel =
      scope === "instance"
        ? instanceId
          ? instances.find((i) => i.instance_id === instanceId)?.hostname ?? instanceId
          : "(pick an instance)"
        : tagSpec || "(pick a tag)";
    return `${metricLabel} ≥ ${threshold}% on ${scopeLabel} for ${windowMinutes}m`;
  }, [metric, scope, instanceId, tagSpec, threshold, windowMinutes, instances]);

  const effectiveName = name.trim() || suggestedName;

  const scopeValid =
    (scope === "instance" && instanceId.trim() !== "") ||
    (scope === "tag" && tagSpec.includes("=") && tagSpec.split("=")[1].trim() !== "");
  const channelValid = selectedChannels.length > 0;
  const formValid = scopeValid && channelValid && threshold > 0 && windowMinutes >= 1;

  const enabledChannels = channels.filter((c) => c.enabled);
  const disabledChannelsCount = channels.length - enabledChannels.length;

  return (
    <form action={action} className="space-y-6">
      {/* hidden defaults the action expects */}
      <input type="hidden" name="module" value="ec2.host" />
      <input type="hidden" name="scope" value={scope} />
      <input type="hidden" name="min_breach_ratio" value="0.6" />

      {/* Module — read-only for now (only EC2 supported) */}
      <Section label="Module">
        <DataPanel className="px-4 py-3">
          <div className="flex items-center gap-3">
            <input
              type="radio"
              name="module_display"
              defaultChecked
              disabled
              className="accent-signal"
            />
            <div>
              <div className="text-sm text-fg">EC2 host</div>
              <div className="text-[11px] text-fg-subtle">
                Reads metrics from the EC2 agent's heartbeat
              </div>
            </div>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-fg-disabled">
            <DisabledRadio label="RDS (AWS CloudWatch)" />
            <DisabledRadio label="ECS (AWS CloudWatch)" />
          </div>
        </DataPanel>
      </Section>

      {/* Scope */}
      <Section label="What to monitor">
        <DataPanel className="space-y-3 px-4 py-3">
          <div className="flex gap-4 text-sm">
            <RadioOption
              checked={scope === "instance"}
              onChange={() => setScope("instance")}
              label="A specific instance"
            />
            <RadioOption
              checked={scope === "tag"}
              onChange={() => setScope("tag")}
              label="All instances with a tag"
            />
          </div>

          {scope === "instance" ? (
            <div>
              <NativeSelect
                name="instance_id"
                value={instanceId}
                onChange={(e) => setInstanceId(e.target.value)}
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
                  No instances are reporting. Install the EC2 agent first.
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-1">
              <NativeSelect
                name="tag_spec"
                value={tagSpec}
                onChange={(e) => setTagSpec(e.target.value)}
              >
                <option value="">— choose tag —</option>
                {tagPairs.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </NativeSelect>
              {tagPairs.length === 0 && (
                <p className="text-[11px] text-fg-subtle">
                  No tags discovered. Set <code>BLACKWATCH_TAGS=env=prod,role=api</code>
                  {" "}on the agent (systemd env var) and reinstall.
                </p>
              )}
            </div>
          )}
        </DataPanel>
      </Section>

      {/* Metric */}
      <Section label="Metric">
        <DataPanel className="space-y-2 px-4 py-3">
          {METRIC_OPTIONS.map((m) => (
            <label
              key={m.value}
              className="flex cursor-pointer items-start gap-3 rounded border border-transparent p-2 transition-colors hover:bg-surface-2"
            >
              <input
                type="radio"
                name="metric"
                value={m.value}
                checked={metric === m.value}
                onChange={() => setMetric(m.value)}
                className="mt-1 accent-signal"
              />
              <div>
                <div className="text-sm text-fg">{m.label}</div>
                <div className="text-[11px] text-fg-subtle">{m.blurb}</div>
              </div>
            </label>
          ))}
        </DataPanel>
      </Section>

      {/* Trigger */}
      <Section label="Trigger condition">
        <DataPanel className="space-y-3 px-4 py-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-fg-muted">Fire when value is</span>
            <NativeSelect
              name="comparison"
              defaultValue={rule?.comparison ?? "gte"}
              className="w-32"
            >
              <option value="gte">≥ (at or above)</option>
              <option value="gt">&gt; (strictly above)</option>
              <option value="lte">≤ (at or below)</option>
              <option value="lt">&lt; (strictly below)</option>
            </NativeSelect>
            <Input
              type="number"
              name="threshold"
              min={0}
              max={100}
              step="0.1"
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="w-20"
              required
            />
            <span className="text-fg-muted">%</span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-fg-muted">for at least</span>
            <Input
              type="number"
              name="window_minutes"
              min={1}
              max={1440}
              step="1"
              value={windowMinutes}
              onChange={(e) => setWindowMinutes(Number(e.target.value))}
              className="w-20"
              required
            />
            <span className="text-fg-muted">minutes</span>
          </div>

          <p className="rounded border border-line-soft bg-surface-2 p-2 text-[11px] text-fg-subtle">
            Looser semantics: the rule fires when {">"} 60% of heartbeat
            samples in the window cross the threshold. One stray sample
            below threshold mid-window won&apos;t reset the alarm.
          </p>
        </DataPanel>
      </Section>

      {/* Notify */}
      <Section label="Notify on">
        <DataPanel className="space-y-2 px-4 py-3">
          {enabledChannels.length === 0 ? (
            <p className="text-sm text-fg-muted">
              No enabled channels.{" "}
              <Link href="/notifications" className="text-signal hover:underline">
                Create one first.
              </Link>
            </p>
          ) : (
            enabledChannels.map((c) => {
              const checked = selectedChannels.includes(c.name);
              return (
                <label
                  key={c.name}
                  className="flex cursor-pointer items-center gap-3 rounded border border-transparent p-2 transition-colors hover:bg-surface-2"
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
                  <div className="flex-1 text-sm text-fg">{c.name}</div>
                  <code className="text-[11px] text-fg-subtle">{c.type}</code>
                </label>
              );
            })
          )}
          {disabledChannelsCount > 0 && (
            <p className="text-[11px] text-fg-subtle">
              {disabledChannelsCount} channel{disabledChannelsCount === 1 ? " is" : "s are"}{" "}
              disabled and hidden.
            </p>
          )}
        </DataPanel>
      </Section>

      {/* Severity + throttle (grouped, less central) */}
      <Section label="Output options">
        <DataPanel className="space-y-3 px-4 py-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-fg-muted">Event severity:</span>
            <NativeSelect
              name="severity"
              defaultValue={rule?.severity ?? "high"}
              className="w-40"
            >
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-fg-muted">Don&apos;t re-alert for</span>
            <Input
              type="number"
              name="throttle_minutes"
              min={0}
              max={1440}
              step="1"
              value={throttleMinutes}
              onChange={(e) => setThrottleMinutes(Number(e.target.value))}
              className="w-20"
            />
            <span className="text-fg-muted">minutes after firing</span>
          </div>
        </DataPanel>
      </Section>

      {/* Name — visible input is display-only; the hidden field below
          carries the effective name (typed or auto-suggested) to the action.
          One submitted "name" field — no FormData collision. */}
      <Section label="Name">
        <DataPanel className="px-4 py-3">
          <Input
            type="text"
            placeholder={suggestedName}
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full"
          />
          <p className="mt-2 text-[11px] text-fg-subtle">
            Will be saved as: <span className="text-fg">{effectiveName}</span>
          </p>
        </DataPanel>
      </Section>

      <input type="hidden" name="enabled" value="on" />
      <input type="hidden" name="name" value={effectiveName} />

      <div className="flex items-center justify-end gap-2">
        <Button asChild variant="ghost" size="sm">
          <Link href="/notifications">Cancel</Link>
        </Button>
        <Button type="submit" variant="primary" size="sm" disabled={!formValid}>
          {mode === "create" ? "Create alert" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}

// ---------- subcomponents ---------------------------------------------------

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <SectionLabel>{label}</SectionLabel>
      {children}
    </section>
  );
}

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

function DisabledRadio({ label }: { label: string }) {
  return (
    <label className="flex cursor-not-allowed items-center gap-2">
      <input type="radio" disabled />
      <span>{label} (coming soon)</span>
    </label>
  );
}

function labelFor(i: PerfAlertInstance): string {
  const tag = i.tags?.role ?? i.tags?.env;
  const hostname = i.hostname ?? "";
  return [i.instance_id, hostname, tag].filter(Boolean).join("  ·  ");
}
