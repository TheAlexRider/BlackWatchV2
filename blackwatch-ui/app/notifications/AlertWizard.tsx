"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Check } from "lucide-react";

import type {
  ModuleCatalogEntry,
  Route,
  SeverityKey,
} from "@/lib/types";

import { Button } from "@/components/ui/Button";
import { SelectableCard } from "@/components/ui/SelectableCard";
import { SeverityChip } from "@/components/ui/SeverityChip";
import { ReviewGrid, ReviewLabel, ReviewValue } from "@/components/ui/ReviewGrid";
import { Wizard, WizardStepHeader } from "@/components/ui/WizardShell";
import { TemplateEditor } from "@/components/domain/notifications/TemplateEditor";
import {
  TestSendButton,
  type SampleOption,
} from "@/components/domain/notifications/TestSendButton";

// Which sample events make sense per module. When the operator picks
// ecs.probe, the test button offers service.down / .degraded / .up / stale
// so they can preview every event shape their route would receive. Modules
// missing from this map fall back to a single generic sample.
const SAMPLES_BY_MODULE: Record<string, SampleOption[]> = {
  "ecs.probe": [
    { value: "service_down",       label: "Service went down" },
    { value: "service_degraded",   label: "Service degraded" },
    { value: "service_up",         label: "Service recovered" },
    { value: "probe_agent_stale",  label: "Probe agent stale" },
  ],
  "ec2.host": [
    { value: "perf_alert",   label: "Performance alert" },
    { value: "fim_modified", label: "File integrity change" },
    { value: "ssh_failure",  label: "SSH failed login" },
  ],
  "vpn.openvpn": [
    { value: "vpn_failure", label: "VPN failed login" },
  ],
  "aws.cloudtrail": [
    { value: "iam_key_created", label: "IAM access key created" },
  ],
  "aws.rds": [
    { value: "rds_auth_failure", label: "RDS proxy auth failure" },
  ],
};

function samplesFor(moduleKey: string): SampleOption[] {
  return SAMPLES_BY_MODULE[moduleKey] ?? [
    { value: "vpn_failure", label: "Generic sample event" },
  ];
}

import { saveAlertRouteAction } from "./wizard-actions";

const SEVERITIES: Array<{
  key: SeverityKey;
  label: string;
  short: string;
}> = [
  { key: "critical",      label: "Critical",      short: "critical" },
  { key: "high",          label: "High",          short: "high" },
  { key: "medium",        label: "Medium",        short: "medium" },
  { key: "low",           label: "Low",           short: "low" },
  { key: "informational", label: "Informational", short: "info" },
];

const WIZARD_STEPS = [
  { n: 1, label: "Source" },
  { n: 2, label: "Trigger" },
  { n: 3, label: "Channel" },
  { n: 4, label: "Message" },
  { n: 5, label: "Review" },
];

type Channel = { id: string; name: string; type: string; enabled: boolean };
type Step = 1 | 2 | 3 | 4 | 5;

export function AlertWizard({
  catalog,
  channels,
  existing,
}: {
  catalog: ModuleCatalogEntry[];
  channels: Channel[];
  existing?: Route | null;
}) {
  const isEdit = !!existing;

  const [step, setStep] = useState<Step>(existing ? 5 : 1);
  const [module, setModule] = useState<string>(existing?.module ?? "");
  const [severities, setSeverities] = useState<Set<SeverityKey>>(
    new Set(existing?.severities ?? []),
  );
  const [channel, setChannel] = useState<string>(existing?.channel ?? "");
  const [useCustomTemplate, setUseCustomTemplate] = useState<boolean>(
    !!existing?.message_template,
  );
  const [templateValue, setTemplateValue] = useState<string>(
    existing?.message_template ?? "",
  );

  const selectedModule = useMemo(
    () => catalog.find((m) => m.key === module) ?? null,
    [catalog, module],
  );
  const selectedChannel = useMemo(
    () => channels.find((c) => c.name === channel) ?? null,
    [channels, channel],
  );

  const complete: Record<number, boolean> = {
    1: !!module,
    2: severities.size > 0,
    3: !!channel,
    4: true,
  };
  const canGoTo = (n: Step): boolean => {
    if (n === 1) return true;
    if (n === 2) return complete[1];
    if (n === 3) return complete[1] && complete[2];
    if (n === 4) return complete[1] && complete[2] && complete[3];
    if (n === 5) return complete[1] && complete[2] && complete[3];
    return false;
  };
  const canAdvance = complete[step];
  const isFinal = step === 5;

  return (
    <form action={saveAlertRouteAction}>
      {existing && <input type="hidden" name="id" value={existing.id} />}
      <input type="hidden" name="module" value={module} />
      <input type="hidden" name="channel" value={channel} />
      <input
        type="hidden"
        name="enabled"
        value={existing?.enabled === false ? "off" : "on"}
      />
      {Array.from(severities).map((s) => (
        <input key={s} type="hidden" name="severity" value={s} />
      ))}
      {!useCustomTemplate && (
        <input type="hidden" name="message_template" value="" />
      )}

      <Wizard
        backHref="/notifications"
        backLabel="back to notifications"
        title={isEdit ? "Edit alert route" : "Create alert route"}
        subtitle={
          isEdit
            ? "Change the trigger, channel, or message for this alert."
            : "Four steps: pick source, severity, channel, and an optional custom message."
        }
        steps={WIZARD_STEPS}
        current={step}
        completed={complete}
        onJump={(n) => canGoTo(n as Step) && setStep(n as Step)}
        onBack={() => setStep((s) => (s > 1 ? ((s - 1) as Step) : s))}
        onNext={() => setStep((s) => (s < 5 ? ((s + 1) as Step) : s))}
        canAdvance={canAdvance}
        isFinal={isFinal}
        finalNode={
          <Button type="submit" size="sm" variant="primary">
            <Check size={12} /> {isEdit ? "Save changes" : "Create alert"}
          </Button>
        }
      >
        <div hidden={step !== 1}>
          <SourceStep
            catalog={catalog}
            selected={module}
            onSelect={setModule}
          />
        </div>
        <div hidden={step !== 2}>
          <TriggerStep
            selected={severities}
            onToggle={(k) => {
              const next = new Set(severities);
              next.has(k) ? next.delete(k) : next.add(k);
              setSeverities(next);
            }}
          />
        </div>
        <div hidden={step !== 3}>
          <ChannelStep
            channels={channels}
            selected={channel}
            onSelect={setChannel}
          />
        </div>
        <div hidden={step !== 4}>
          <MessageStep
            channelName={channel}
            channelType={selectedChannel?.type ?? "slack"}
            enabled={useCustomTemplate}
            onToggle={setUseCustomTemplate}
            defaultValue={existing?.message_template ?? ""}
            onValueChange={setTemplateValue}
            sampleOptions={samplesFor(module)}
          />
        </div>
        <div hidden={step !== 5}>
          <ReviewStep
            moduleLabel={selectedModule?.label ?? module}
            severities={Array.from(severities)}
            channelName={channel}
            channelType={selectedChannel?.type ?? "slack"}
            customTemplate={useCustomTemplate}
            templateValue={templateValue}
            sampleOptions={samplesFor(module)}
          />
        </div>
      </Wizard>
    </form>
  );
}

// =========================================================================
// Step 1 — Source
// =========================================================================

function SourceStep({
  catalog,
  selected,
  onSelect,
}: {
  catalog: ModuleCatalogEntry[];
  selected: string;
  onSelect: (k: string) => void;
}) {
  return (
    <div>
      <WizardStepHeader
        title="Which source triggers this alert?"
        subtitle="Pick a module. The alert will fire for events coming from that source."
      />
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {catalog.map((m) => (
          <SelectableCard
            key={m.key}
            type="radio"
            name="source-radio"
            value={m.key}
            checked={m.key === selected}
            onChange={() => onSelect(m.key)}
            title={
              <span className="flex items-center gap-2">
                <span>{m.label}</span>
                <code className="font-mono text-[10px] text-fg-subtle">
                  {m.key}
                </code>
              </span>
            }
            description={m.blurb}
          />
        ))}
      </div>
      <div className="mt-5 border-t border-line-soft pt-3 text-xs text-fg-subtle">
        Need a rule with a custom condition (action contains, category-in, etc)?{" "}
        <Link
          href="/notifications/rules/new"
          className="text-signal hover:underline"
        >
          Use the advanced rule editor →
        </Link>
      </div>
    </div>
  );
}

// =========================================================================
// Step 2 — Trigger (severity selection)
// =========================================================================

function TriggerStep({
  selected,
  onToggle,
}: {
  selected: Set<SeverityKey>;
  onToggle: (k: SeverityKey) => void;
}) {
  return (
    <div>
      <WizardStepHeader
        title="Which severities should trigger it?"
        subtitle="Usually one. Creating a separate route per severity lets you customize the channel and message for each. Multi-select routes them to the same channel with the same message."
      />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        {SEVERITIES.map((s) => (
          <SelectableCard
            key={s.key}
            type="checkbox"
            name="severity-toggle"
            value={s.key}
            checked={selected.has(s.key)}
            onChange={() => onToggle(s.key)}
            title={s.label}
          />
        ))}
      </div>
    </div>
  );
}

// =========================================================================
// Step 3 — Channel
// =========================================================================

function ChannelStep({
  channels,
  selected,
  onSelect,
}: {
  channels: Channel[];
  selected: string;
  onSelect: (name: string) => void;
}) {
  return (
    <div>
      <WizardStepHeader
        title="Which channel should receive it?"
        subtitle="Pick a delivery channel — Slack, email, webhook, etc."
      />
      {channels.length === 0 ? (
        <div className="border border-sev-medium/30 bg-sev-medium/5 px-4 py-3 text-xs text-fg-muted">
          No channels yet.{" "}
          <Link
            href="/notifications/channels/new"
            className="text-signal hover:underline"
          >
            Add a channel first →
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {channels.map((c) => (
            <SelectableCard
              key={c.name}
              type="radio"
              name="channel-select"
              value={c.name}
              checked={c.name === selected}
              onChange={() => onSelect(c.name)}
              disabled={!c.enabled}
              title={
                <span className="flex items-center gap-2">
                  <span>{c.name}</span>
                  <code className="border border-line-soft px-1 py-px font-mono text-[9px] uppercase tracking-wider text-fg-subtle">
                    {c.type}
                  </code>
                </span>
              }
              description={
                !c.enabled ? "This channel is currently disabled" : undefined
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

// =========================================================================
// Step 4 — Message (optional)
// =========================================================================

function MessageStep({
  channelName,
  channelType,
  enabled,
  onToggle,
  defaultValue,
  onValueChange,
  sampleOptions,
}: {
  channelName: string;
  channelType: string;
  enabled: boolean;
  onToggle: (v: boolean) => void;
  defaultValue: string;
  onValueChange: (v: string) => void;
  sampleOptions: SampleOption[];
}) {
  return (
    <div>
      <WizardStepHeader
        title="Customize the message (optional)"
        subtitle="By default the channel's own template is used. Toggle on to write a per-rule template with variables, a live preview against sample events (or a real recent event), and a Send-test button."
      />

      <label
        className={
          enabled
            ? "flex cursor-pointer items-center gap-3 border border-signal bg-signal/5 px-4 py-3 text-sm text-fg transition-colors"
            : "flex cursor-pointer items-center gap-3 border border-line-soft bg-canvas px-4 py-3 text-sm text-fg-muted transition-colors hover:bg-surface-2"
        }
      >
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onToggle(e.currentTarget.checked)}
          className="sr-only"
        />
        <span
          aria-hidden
          className={
            enabled
              ? "h-2 w-2 shrink-0 rounded-full border border-signal bg-signal transition-colors"
              : "h-2 w-2 shrink-0 rounded-full border border-fg-subtle bg-transparent transition-colors"
          }
        />
        <span>Use a custom message for this route</span>
      </label>

      {enabled && (
        <div className="mt-5 space-y-4">
          <TemplateEditor
            name="message_template"
            channelType={channelType}
            defaultValue={defaultValue}
            onValueChange={onValueChange}
          />
          {channelName && (
            <div className="border-t border-line-soft pt-4">
              <p className="mb-2 text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
                Test-send this message
              </p>
              <p className="mb-2.5 text-[11px] text-fg-subtle">
                Delivers the rendered template to <code className="font-mono text-fg-muted">{channelName}</code> so you can see the real message land before saving.
              </p>
              <TestSendButton
                channelNames={[channelName]}
                template={defaultValue}
                channelType={channelType}
                contextKind="event"
                sampleOptions={sampleOptions}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// =========================================================================
// Step 5 — Review
// =========================================================================

function ReviewStep({
  moduleLabel,
  severities,
  channelName,
  channelType,
  customTemplate,
  templateValue,
  sampleOptions,
}: {
  moduleLabel: string;
  severities: SeverityKey[];
  channelName: string;
  channelType: string;
  customTemplate: boolean;
  templateValue: string;
  sampleOptions: SampleOption[];
}) {
  return (
    <div>
      <WizardStepHeader
        title="Review your alert"
        subtitle="Make sure everything looks right, then save."
      />

      <ReviewGrid>
        <ReviewLabel>Source</ReviewLabel>
        <ReviewValue className="text-fg">{moduleLabel || "—"}</ReviewValue>

        <ReviewLabel>Trigger</ReviewLabel>
        <ReviewValue className="flex flex-wrap gap-1.5">
          {severities.length === 0 ? (
            <span className="text-fg-muted">—</span>
          ) : (
            severities.map((s) => (
              <SeverityChip key={s} severity={s} />
            ))
          )}
        </ReviewValue>

        <ReviewLabel>Channel</ReviewLabel>
        <ReviewValue className="font-mono text-xs text-fg-muted">
          {channelName ? `→ ${channelName}` : "—"}
        </ReviewValue>

        <ReviewLabel>Message</ReviewLabel>
        <ReviewValue className="text-xs text-fg-muted">
          {customTemplate ? (
            <span className="text-fg">Custom template for this route</span>
          ) : (
            <span className="text-fg-muted">
              Uses channel&apos;s default template
            </span>
          )}
        </ReviewValue>
      </ReviewGrid>

      {channelName && (
        <div className="mt-6 border-t border-line-soft pt-5">
          <p className="mb-1 text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            One-shot test
          </p>
          <p className="mb-2.5 text-[11px] text-fg-subtle">
            Fires the picked sample event through{" "}
            <code className="font-mono text-fg-muted">{channelName}</code> right now
            {customTemplate ? " using your custom template." : " using the channel's default template — no template setup needed."}
            {sampleOptions.length > 1 && " Pick which event shape to preview:"}
          </p>
          <TestSendButton
            channelNames={[channelName]}
            template={customTemplate ? templateValue : ""}
            channelType={channelType}
            contextKind="event"
            sampleOptions={sampleOptions}
          />
        </div>
      )}
    </div>
  );
}
