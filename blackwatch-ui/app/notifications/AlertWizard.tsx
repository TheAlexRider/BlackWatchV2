"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Check } from "lucide-react";

import type {
  ModuleCatalogEntry,
  Route,
  SeverityKey,
} from "@/lib/types";
import type { PreviewSampleKind } from "@/lib/api";

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
  const [templateValue, setTemplateValue] = useState<string>(
    existing?.message_template ?? "",
  );

  // Sample event the operator is previewing — shared across the Message
  // and Review steps so the same choice drives both the live preview and
  // the Send-test button. Seeded from the first module-appropriate sample.
  const moduleSamples = useMemo(() => samplesFor(module), [module]);
  const [sample, setSample] = useState<PreviewSampleKind>(moduleSamples[0].value);
  // If the operator changes the source module and the current sample no
  // longer applies, re-seed to the first sample for the new module.
  useMemo(() => {
    if (!moduleSamples.some((o) => o.value === sample)) {
      setSample(moduleSamples[0].value);
    }
  }, [moduleSamples, sample]);

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
      {/* Empty template = server falls back to the channel's default. That's
          the "no setup needed" path: ECS/perf events carry their own
          extra.message which the channel default renders verbatim. */}
      <input type="hidden" name="message_template" value={templateValue} />

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
            defaultValue={existing?.message_template ?? ""}
            templateValue={templateValue}
            onValueChange={setTemplateValue}
            sampleOptions={moduleSamples}
            sample={sample}
            onSampleChange={setSample}
          />
        </div>
        <div hidden={step !== 5}>
          <ReviewStep
            moduleLabel={selectedModule?.label ?? module}
            severities={Array.from(severities)}
            channelName={channel}
            channelType={selectedChannel?.type ?? "slack"}
            templateValue={templateValue}
            sample={sample}
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
  defaultValue,
  templateValue,
  onValueChange,
  sampleOptions,
  sample,
  onSampleChange,
}: {
  channelName: string;
  channelType: string;
  defaultValue: string;
  templateValue: string;
  onValueChange: (v: string) => void;
  sampleOptions: SampleOption[];
  sample: PreviewSampleKind;
  onSampleChange: (kind: PreviewSampleKind) => void;
}) {
  return (
    <div>
      <WizardStepHeader
        title="Message"
        subtitle="Pick a preset or write your own. The preview updates live against the sample event you pick below. Leave everything empty to use the channel's built-in formatting — recommended for ECS/perf events that already ship pre-formatted bodies."
      />

      <TemplateEditor
        name="message_template"
        channelType={channelType}
        defaultValue={defaultValue}
        onValueChange={onValueChange}
        sampleOptions={sampleOptions}
        sample={sample}
        onSampleChange={onSampleChange}
      />

      {channelName && (
        <div className="mt-6 border-t border-line-soft pt-5">
          <p className="mb-2 text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            Test-send this message
          </p>
          <p className="mb-2.5 text-[11px] text-fg-subtle">
            Delivers the currently-previewed sample to{" "}
            <code className="font-mono text-fg-muted">{channelName}</code> using
            the template above (or the channel default if empty). Change the
            sample from the preview dropdown to test each event type.
          </p>
          <TestSendButton
            channelNames={[channelName]}
            template={templateValue}
            channelType={channelType}
            contextKind="event"
            sampleEvent={sample}
          />
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
  templateValue,
  sample,
}: {
  moduleLabel: string;
  severities: SeverityKey[];
  channelName: string;
  channelType: string;
  templateValue: string;
  sample: PreviewSampleKind;
}) {
  const customTemplate = templateValue.trim().length > 0;
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
            Fires the sample event picked in the Message step through{" "}
            <code className="font-mono text-fg-muted">{channelName}</code> right now
            {customTemplate ? " using your custom template." : " using the channel's default template — no template setup needed."}
          </p>
          <TestSendButton
            channelNames={[channelName]}
            template={templateValue}
            channelType={channelType}
            contextKind="event"
            sampleEvent={sample}
          />
        </div>
      )}
    </div>
  );
}
