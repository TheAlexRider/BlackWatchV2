"use client";

import Link from "next/link";
import clsx from "clsx";
import { useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Check, ChevronRight } from "lucide-react";

import type {
  ModuleCatalogEntry,
  Route,
  SeverityKey,
} from "@/lib/types";

import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { SeverityChip, severityChipClass } from "@/components/ui/SeverityChip";
import { ReviewGrid, ReviewLabel, ReviewValue } from "@/components/ui/ReviewGrid";
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

  // React state governs stepper + review + hidden-input mirrors; the actual
  // form fields (radios, checkboxes, template textarea) live in the DOM.
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

  const chipsBySev = (keys: Iterable<SeverityKey>) =>
    Array.from(keys)
      .map((k) => SEVERITIES.find((s) => s.key === k)?.short ?? k)
      .join(" + ");

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6">
        <Link
          href="/notifications"
          className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft size={12} /> back to notifications
        </Link>
      </div>

      <div className="mb-6">
        <h1 className="text-xl text-fg">
          {isEdit ? "Edit alert route" : "Create alert route"}
        </h1>
        <p className="mt-1 text-xs text-fg-muted">
          {isEdit
            ? "Change the trigger, channel, or message for this alert."
            : "Four steps: pick source, pick severity, pick channel, customize message (optional)."}
        </p>
      </div>

      <Stepper step={step} onJump={(n) => canGoTo(n) && setStep(n)} completed={complete} />

      <form action={saveAlertRouteAction} className="mt-6">
        {/* Hidden mirrors of React state so FormData sees them on submit. */}
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
        {/* When the "use custom message" toggle is OFF, we clear the field
            so save persists null (channel default). When ON, the value
            comes from the TemplateEditor's textarea below. */}
        {!useCustomTemplate && (
          <input type="hidden" name="message_template" value="" />
        )}

        <div className="border border-line-soft bg-surface-1 p-6">
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

        <div className="mt-4 flex items-center justify-between">
          <Button
            type="button"
            size="sm"
            variant="secondary"
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

      {step < 5 && (module || severities.size > 0 || channel) && (
        <div className="mt-4 border border-line-soft bg-canvas px-3 py-2 text-[11px] text-fg-muted">
          <span className="text-fg-subtle">so far:</span>{" "}
          {module ? (
            <span className="text-fg">{selectedModule?.label ?? module}</span>
          ) : (
            <span className="text-fg-subtle">no source</span>
          )}
          <span className="mx-2 text-fg-subtle">·</span>
          {severities.size > 0 ? (
            <span className="text-fg">{chipsBySev(severities)}</span>
          ) : (
            <span className="text-fg-subtle">no severity</span>
          )}
          <span className="mx-2 text-fg-subtle">·</span>
          {channel ? (
            <span className="font-mono text-fg">→ {channel}</span>
          ) : (
            <span className="text-fg-subtle">no channel</span>
          )}
        </div>
      )}
    </div>
  );
}

// =========================================================================
// Stepper
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
    <ol className="flex flex-wrap items-center gap-1 text-[11px]">
      {STEPS.map((s, i) => {
        const active = step === s.n;
        const done = completed[s.n];
        return (
          <li key={s.n} className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => onJump(s.n as 1 | 2 | 3 | 4 | 5)}
              className={clsx(
                "inline-flex items-center gap-1.5 border px-2 py-1 transition-colors",
                active
                  ? "border-signal bg-signal/10 text-fg"
                  : done
                  ? "border-line bg-canvas text-fg-muted hover:bg-surface-2"
                  : "border-line-soft bg-canvas text-fg-subtle",
              )}
              aria-current={active ? "step" : undefined}
            >
              <span
                className={clsx(
                  "flex h-4 w-4 items-center justify-center border font-mono text-[10px]",
                  active
                    ? "border-signal bg-signal text-canvas"
                    : done
                    ? "border-line bg-canvas text-fg-muted"
                    : "border-line-soft text-fg-subtle",
                )}
              >
                {done && !active ? <Check size={9} /> : s.n}
              </span>
              <span>{s.label}</span>
            </button>
            {i < STEPS.length - 1 && (
              <ChevronRight size={11} className="text-fg-subtle" />
            )}
          </li>
        );
      })}
    </ol>
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
    <div className="space-y-4">
      <div>
        <h2 className="text-sm text-fg">Which source triggers this alert?</h2>
        <p className="mt-0.5 text-xs text-fg-muted">
          Pick a module. The alert will fire for events coming from that source.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {catalog.map((m) => {
          const isSelected = m.key === selected;
          return (
            <label
              key={m.key}
              className={clsx(
                "flex cursor-pointer flex-col gap-1 border px-3 py-2.5 transition-colors",
                isSelected
                  ? "border-signal bg-signal/5"
                  : "border-line-soft bg-canvas hover:bg-surface-2",
              )}
            >
              <div className="flex items-center gap-2">
                <input
                  type="radio"
                  name="source-radio"
                  value={m.key}
                  checked={isSelected}
                  onChange={() => onSelect(m.key)}
                  className="accent-signal"
                />
                <span className="text-sm text-fg">{m.label}</span>
                <span className="ml-auto font-mono text-[10px] text-fg-subtle">
                  {m.key}
                </span>
              </div>
              <p className="pl-5 text-[11px] text-fg-subtle">{m.blurb}</p>
            </label>
          );
        })}
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
// Step 2 — Trigger
// =========================================================================

function TriggerStep({
  selected,
  onToggle,
}: {
  selected: Set<SeverityKey>;
  onToggle: (k: SeverityKey) => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm text-fg">Which severities should trigger it?</h2>
        <p className="mt-0.5 text-xs text-fg-muted">
          Usually one. Creating a separate route per severity lets you customize
          the channel and message for each. Multi-select routes them to the same
          channel with the same message.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {SEVERITIES.map((s) => {
          const isOn = selected.has(s.key);
          return (
            <label
              key={s.key}
              className={clsx(
                "flex cursor-pointer items-center gap-2 border px-3 py-2 text-sm transition-colors",
                isOn
                  ? clsx(severityChipClass(s.key), "border")
                  : "border-line-soft bg-canvas text-fg-muted hover:bg-surface-2",
              )}
            >
              <input
                type="checkbox"
                checked={isOn}
                onChange={() => onToggle(s.key)}
                className="accent-signal"
              />
              <span>{s.label}</span>
            </label>
          );
        })}
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
    <div className="space-y-4">
      <div>
        <h2 className="text-sm text-fg">Which channel should receive it?</h2>
        <p className="mt-0.5 text-xs text-fg-muted">
          Pick a delivery channel — Slack, email, webhook, etc.
        </p>
      </div>

      {channels.length === 0 ? (
        <div className="border border-sev-medium/30 bg-sev-medium/5 px-3 py-3 text-xs text-fg-muted">
          No channels yet.{" "}
          <Link
            href="/notifications/channels/new"
            className="text-signal hover:underline"
          >
            Add a channel first →
          </Link>
        </div>
      ) : (
        <NativeSelect
          name="channel-select"
          value={selected}
          onChange={(e) => onSelect(e.currentTarget.value)}
          className="w-full max-w-md"
        >
          <option value="">— pick a channel —</option>
          {channels.map((c) => (
            <option key={c.name} value={c.name} disabled={!c.enabled}>
              {c.name} · {c.type}
              {!c.enabled ? " (disabled)" : ""}
            </option>
          ))}
        </NativeSelect>
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
    <div className="space-y-4">
      <div>
        <h2 className="text-sm text-fg">Customize the message (optional)</h2>
        <p className="mt-0.5 text-xs text-fg-muted">
          By default the channel's own template is used. Toggle on to write a
          per-rule template with variables and a live preview against sample
          events (or a real recent event).
        </p>
      </div>

      <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-fg-muted">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onToggle(e.currentTarget.checked)}
          className="accent-signal"
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
    <div className="space-y-4">
      <div>
        <h2 className="text-sm text-fg">Review your alert</h2>
        <p className="mt-0.5 text-xs text-fg-muted">
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
            <span className="text-fg-muted">Uses channel&apos;s default template</span>
          )}
        </ReviewValue>
      </ReviewGrid>
    </div>
  );
}
