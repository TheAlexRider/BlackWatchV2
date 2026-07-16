"use client";

import Link from "next/link";
import clsx from "clsx";
import { useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";

import type {
  ModuleCatalogEntry,
  Route,
  SeverityKey,
} from "@/lib/types";

import { Button } from "@/components/ui/Button";
import { SelectableCard } from "@/components/ui/SelectableCard";
import { SeverityChip } from "@/components/ui/SeverityChip";
import { ReviewGrid, ReviewLabel, ReviewValue } from "@/components/ui/ReviewGrid";
import { BackLink } from "@/components/ui/BackLink";
import { DataPanel } from "@/components/layout/DataPanel";
import { TemplateEditor } from "@/components/domain/notifications/TemplateEditor";

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

  return (
    <div className="mx-auto max-w-3xl">
      <BackLink href="/notifications" label="back to notifications" />

      <div className="mb-8">
        <h1 className="text-xl text-fg">
          {isEdit ? "Edit alert route" : "Create alert route"}
        </h1>
        <p className="mt-1 text-xs text-fg-muted">
          {isEdit
            ? "Change the trigger, channel, or message for this alert."
            : "Four steps: pick source, severity, channel, and an optional custom message."}
        </p>
      </div>

      <Stepper step={step} onJump={(n) => canGoTo(n) && setStep(n)} completed={complete} />

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

        <DataPanel scrollX={false}>
          <div className="p-8">
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
                channelType={selectedChannel?.type ?? "slack"}
                enabled={useCustomTemplate}
                onToggle={setUseCustomTemplate}
                defaultValue={existing?.message_template ?? ""}
              />
            </div>
            <div hidden={step !== 5}>
              <ReviewStep
                moduleLabel={selectedModule?.label ?? module}
                severities={Array.from(severities)}
                channelName={channel}
                customTemplate={useCustomTemplate}
              />
            </div>
          </div>
        </DataPanel>

        <div className="mt-4 flex items-center justify-between">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={step === 1}
            onClick={() => setStep((s) => (s > 1 ? ((s - 1) as Step) : s))}
          >
            <ArrowLeft size={12} /> Back
          </Button>

          {step < 5 ? (
            <Button
              type="button"
              size="sm"
              variant="primary"
              disabled={!canAdvance}
              onClick={() => setStep((s) => (s < 5 ? ((s + 1) as Step) : s))}
            >
              Next <ArrowRight size={12} />
            </Button>
          ) : (
            <Button type="submit" size="sm" variant="primary">
              <Check size={12} /> {isEdit ? "Save changes" : "Create alert"}
            </Button>
          )}
        </div>
      </form>
    </div>
  );
}

// =========================================================================
// Stepper — circles connected by lines, labels below
// =========================================================================

const STEPS = [
  { n: 1, label: "Source" },
  { n: 2, label: "Trigger" },
  { n: 3, label: "Channel" },
  { n: 4, label: "Message" },
  { n: 5, label: "Review" },
] as const;

function Stepper({
  step,
  onJump,
  completed,
}: {
  step: number;
  onJump: (n: 1 | 2 | 3 | 4 | 5) => void;
  completed: Record<number, boolean>;
}) {
  return (
    <nav aria-label="Progress" className="mb-8">
      <ol className="flex items-start">
        {STEPS.map((s, i) => {
          const active = step === s.n;
          const done = completed[s.n] && !active;
          const isLast = i === STEPS.length - 1;

          return (
            <li
              key={s.n}
              className={clsx("flex items-start", !isLast && "flex-1")}
            >
              <button
                type="button"
                onClick={() => onJump(s.n as 1 | 2 | 3 | 4 | 5)}
                className="group flex flex-col items-center gap-1.5"
                aria-current={active ? "step" : undefined}
              >
                <span
                  className={clsx(
                    "flex h-7 w-7 items-center justify-center rounded-full border-2 font-mono text-[11px] transition-colors",
                    active
                      ? "border-signal bg-signal text-canvas"
                      : done
                        ? "border-signal/50 bg-signal/10 text-signal"
                        : "border-line-soft text-fg-subtle group-hover:border-line",
                  )}
                >
                  {done ? <Check size={11} strokeWidth={2.5} /> : s.n}
                </span>
                <span
                  className={clsx(
                    "text-[10px] uppercase tracking-[0.08em]",
                    active
                      ? "text-fg"
                      : done
                        ? "text-fg-muted"
                        : "text-fg-subtle",
                  )}
                >
                  {s.label}
                </span>
              </button>
              {!isLast && (
                <div
                  className={clsx(
                    "mx-1.5 mt-3.5 h-px flex-1 transition-colors",
                    done ? "bg-signal/30" : "bg-line-soft",
                  )}
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
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
    <div className="space-y-5">
      <div>
        <h2 className="text-sm text-fg">Which source triggers this alert?</h2>
        <p className="mt-1 text-xs text-fg-muted">
          Pick a module. The alert will fire for events coming from that source.
        </p>
      </div>

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

      <div className="border-t border-line-soft pt-3 text-xs text-fg-subtle">
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
    <div className="space-y-5">
      <div>
        <h2 className="text-sm text-fg">Which severities should trigger it?</h2>
        <p className="mt-1 text-xs text-fg-muted">
          Usually one. Creating a separate route per severity lets you customize
          the channel and message for each. Multi-select routes them to the same
          channel with the same message.
        </p>
      </div>

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
    <div className="space-y-5">
      <div>
        <h2 className="text-sm text-fg">Which channel should receive it?</h2>
        <p className="mt-1 text-xs text-fg-muted">
          Pick a delivery channel — Slack, email, webhook, etc.
        </p>
      </div>

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
  channelType,
  enabled,
  onToggle,
  defaultValue,
}: {
  channelType: string;
  enabled: boolean;
  onToggle: (v: boolean) => void;
  defaultValue: string;
}) {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-sm text-fg">Customize the message (optional)</h2>
        <p className="mt-1 text-xs text-fg-muted">
          By default the channel&apos;s own template is used. Toggle on to write a
          per-rule template with variables and a live preview against sample
          events (or a real recent event).
        </p>
      </div>

      <label
        className={clsx(
          "flex cursor-pointer items-center gap-3 border px-4 py-3 text-sm transition-colors",
          enabled
            ? "border-signal bg-signal/5 text-fg"
            : "border-line-soft bg-canvas text-fg-muted hover:bg-surface-2",
        )}
      >
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onToggle(e.currentTarget.checked)}
          className="sr-only"
        />
        <span
          aria-hidden
          className={clsx(
            "h-2 w-2 shrink-0 rounded-full border transition-colors",
            enabled
              ? "border-signal bg-signal"
              : "border-fg-subtle bg-transparent",
          )}
        />
        <span>Use a custom message for this route</span>
      </label>

      {enabled && (
        <TemplateEditor
          name="message_template"
          channelType={channelType}
          defaultValue={defaultValue}
        />
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
  customTemplate,
}: {
  moduleLabel: string;
  severities: SeverityKey[];
  channelName: string;
  customTemplate: boolean;
}) {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-sm text-fg">Review your alert</h2>
        <p className="mt-1 text-xs text-fg-muted">
          Make sure everything looks right, then save.
        </p>
      </div>

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
    </div>
  );
}
