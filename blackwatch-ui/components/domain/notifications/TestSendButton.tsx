"use client";

import { useEffect, useState } from "react";
import { Send, Check, X } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import {
  testSendTemplate,
  type PerfPreviewContext,
  type PreviewSampleKind,
  type TemplateContextKind,
} from "@/lib/api";

export type SampleOption = { value: PreviewSampleKind; label: string };

// Deliver the current template + a sample event through the selected
// channel(s) so the operator sees the exact message land in Slack/Discord/etc.
// This is what "test alert" means in the wizards — NOT a generic
// informational probe.
//
// If `sampleOptions` has more than one entry, the button gets a dropdown so
// the operator picks WHICH sample event to fire — e.g. an ECS route can
// test service.down vs service.up vs probe.agent.stale from the same button.
export function TestSendButton({
  channelNames,
  template,
  channelType,
  contextKind = "event",
  sampleEvent,
  sampleOptions,
  perfContext,
  disabled = false,
}: {
  /** Every channel the alert would fire on. All are hit in parallel. */
  channelNames: string[];
  /** The exact Jinja source in the textarea. Empty means "use the channel's
   *  default preset" — matches preview behavior. */
  template: string;
  channelType?: string;
  contextKind?: TemplateContextKind;
  /** Default sample kind. Ignored when `sampleOptions` is passed (the picker's
   *  selection wins). */
  sampleEvent?: PreviewSampleKind;
  /** Optional sample dropdown. First entry is the default. Pass this from
   *  the wizard based on the selected module so the operator can preview
   *  every event shape the route would receive. */
  sampleOptions?: SampleOption[];
  /** Wizard's live form state (metric/threshold/window/…). Only used for
   *  perf tests — merged onto the server's baseline perf sample so the
   *  test message reflects the rule being built, not a stale CPU sample. */
  perfContext?: PerfPreviewContext;
  disabled?: boolean;
}) {
  const [sending, setSending] = useState(false);
  const [results, setResults] = useState<
    Array<{ channel: string; ok: boolean; detail?: string }>
  >([]);

  // Selected sample kind — seeded from options[0] or the fallback prop.
  const [selectedSample, setSelectedSample] = useState<PreviewSampleKind | undefined>(
    sampleOptions?.[0]?.value ?? sampleEvent,
  );
  // Re-seed if the parent swaps options (e.g. user changes the wizard module).
  useEffect(() => {
    const first = sampleOptions?.[0]?.value;
    if (first && !sampleOptions?.some((o) => o.value === selectedSample)) {
      setSelectedSample(first);
    }
  }, [sampleOptions, selectedSample]);

  const noChannels = channelNames.length === 0;
  const isDisabled = disabled || sending || noChannels;

  async function handleSend() {
    setSending(true);
    setResults([]);
    try {
      const settled = await Promise.all(
        channelNames.map((name) =>
          testSendTemplate({
            channelName: name,
            template,
            channelType,
            contextKind,
            sampleEvent: selectedSample ?? sampleEvent,
            perfContext,
          }).then((r) => ({
            channel: name,
            ok: r.status === "sent",
            detail: r.detail,
          })),
        ),
      );
      setResults(settled);
    } finally {
      setSending(false);
      // Auto-clear the pill after 6s so the button feels reusable.
      window.setTimeout(() => setResults([]), 6000);
    }
  }

  const allOk = results.length > 0 && results.every((r) => r.ok);
  const anyFail = results.some((r) => !r.ok);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {sampleOptions && sampleOptions.length > 1 && (
        <NativeSelect
          value={selectedSample ?? sampleOptions[0].value}
          onChange={(e) => setSelectedSample(e.target.value as PreviewSampleKind)}
          className="w-52"
          aria-label="Which sample event to fire"
          disabled={sending}
        >
          {sampleOptions.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </NativeSelect>
      )}

      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={handleSend}
        disabled={isDisabled}
        aria-label="Send a test alert to the selected channels"
      >
        <Send size={12} />
        {sending
          ? "Sending…"
          : channelNames.length > 1
            ? `Send test to ${channelNames.length} channels`
            : "Send test"}
      </Button>

      {noChannels && (
        <span className="text-[11px] text-fg-subtle">
          Pick a channel first.
        </span>
      )}

      {results.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {results.map((r) => (
            <span
              key={r.channel}
              className={
                r.ok
                  ? "inline-flex items-center gap-1 border border-signal/40 bg-signal/10 px-1.5 py-0.5 font-mono text-[10px] text-signal"
                  : "inline-flex items-center gap-1 border border-sev-critical/40 bg-sev-critical/10 px-1.5 py-0.5 font-mono text-[10px] text-sev-critical"
              }
              title={r.detail}
            >
              {r.ok ? <Check size={10} /> : <X size={10} />}
              {r.channel}
            </span>
          ))}
        </div>
      )}

      {!sending && results.length > 0 && anyFail && (
        <span className="text-[10px] text-fg-subtle">
          Hover a failed pill for the error detail.
        </span>
      )}
    </div>
  );
}
