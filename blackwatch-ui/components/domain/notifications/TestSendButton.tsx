"use client";

import { useState } from "react";
import { Send, Check, X } from "lucide-react";

import { Button } from "@/components/ui/Button";
import {
  testSendTemplate,
  type PreviewSampleKind,
  type TemplateContextKind,
} from "@/lib/api";

// Deliver the current template + a sample event through the selected
// channel(s) so the operator sees the exact message land in Slack/Discord/etc.
// This is what "test alert" means in the wizards — NOT a generic
// informational probe.
//
// Renders as an inline button with a status pill that clears itself after a
// short cooldown so the operator can send another one.
export function TestSendButton({
  channelNames,
  template,
  channelType,
  contextKind = "event",
  sampleEvent,
  disabled = false,
}: {
  /** Every channel the alert would fire on. All are hit in parallel. */
  channelNames: string[];
  /** The exact Jinja source in the textarea. Empty means "use the channel's
   *  default preset" — matches preview behavior. */
  template: string;
  channelType?: string;
  contextKind?: TemplateContextKind;
  sampleEvent?: PreviewSampleKind;
  disabled?: boolean;
}) {
  const [sending, setSending] = useState(false);
  const [results, setResults] = useState<
    Array<{ channel: string; ok: boolean; detail?: string }>
  >([]);

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
            sampleEvent,
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
