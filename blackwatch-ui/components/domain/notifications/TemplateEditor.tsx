"use client";

import { useEffect, useState, useTransition } from "react";
import {
  fetchRecentEventsForPreview,
  fetchTemplatePresets,
  previewTemplate,
  type PreviewSampleKind,
  type RecentEventSample,
  type TemplatePreset,
} from "@/lib/api";

const SAMPLE_EVENTS: Array<{ value: PreviewSampleKind; label: string }> = [
  { value: "vpn_failure", label: "VPN failed login" },
  { value: "perf_alert", label: "Performance alert" },
  { value: "fim_modified", label: "FIM file modified" },
  { value: "ssh_failure", label: "SSH failed login" },
  { value: "iam_key_created", label: "IAM access key created" },
  { value: "rds_auth_failure", label: "RDS proxy auth failure" },
];

type SampleSource = "canned" | "recent";

function formatRecentEventLabel(ev: RecentEventSample): string {
  // Compact one-liner: HH:mm · action · principal → target
  const ts = ev.event_time ? new Date(ev.event_time) : null;
  const t = ts
    ? ts.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "??:??";
  const parts = [t, ev.action || "(no action)"];
  if (ev.principal) parts.push(`by ${ev.principal}`);
  if (ev.target_name) parts.push(`→ ${ev.target_name}`);
  const label = parts.join(" · ");
  return label.length > 80 ? `${label.slice(0, 79)}…` : label;
}

// The fields the operator can stick into a template, with one-line descriptions.
// Insert-on-click puts `{{ event.X }}` at the textarea's cursor so the user
// doesn't have to remember the dotted-path syntax. Same names the Jinja
// templates use server-side.
const VARIABLES: { name: string; path: string; example: string }[] = [
  { name: "Action", path: "event.action", example: "vpn.auth.failure" },
  { name: "Severity", path: "event.severity", example: "high" },
  { name: "Who (principal)", path: "event.actor.principal", example: "apoorvasharma" },
  { name: "Source IP", path: "event.actor.source_ip", example: "27.58.20.140" },
  { name: "When", path: "event.event_time", example: "2026-06-10T06:25:24Z" },
  { name: "Target", path: "event.target.id", example: "openvpn-prod-1" },
  { name: "Module", path: "event.source.module", example: "vpn.openvpn" },
  { name: "Outcome", path: "event.outcome", example: "failure" },
  { name: "Matched rules", path: "event.rule_matches|join(', ')", example: "Failed logins" },
];

export function TemplateEditor({
  name,
  channelType,
  defaultValue,
}: {
  name: string;
  channelType: string;
  defaultValue: string;
}) {
  const [value, setValue] = useState(defaultValue);
  const [presets, setPresets] = useState<TemplatePreset[]>([]);
  const [preview, setPreview] = useState<string>("");
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [sampleSource, setSampleSource] = useState<SampleSource>("canned");
  const [sample, setSample] = useState<PreviewSampleKind>("vpn_failure");
  const [recentEvents, setRecentEvents] = useState<RecentEventSample[]>([]);
  const [recentEventId, setRecentEventId] = useState<string>("");
  const [recentLoading, setRecentLoading] = useState(false);
  const [, startTransition] = useTransition();

  // Load recent real events the first time the user flips to "recent".
  useEffect(() => {
    if (sampleSource !== "recent" || recentEvents.length > 0) return;
    let cancelled = false;
    setRecentLoading(true);
    fetchRecentEventsForPreview(30)
      .then((rows) => {
        if (cancelled) return;
        setRecentEvents(rows);
        if (rows.length > 0 && !recentEventId) setRecentEventId(rows[0].event_id);
      })
      .catch(() => {
        // Non-fatal — user can flip back to canned.
      })
      .finally(() => {
        if (!cancelled) setRecentLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sampleSource, recentEvents.length, recentEventId]);

  // Load presets for this channel type once on mount.
  useEffect(() => {
    let cancelled = false;
    fetchTemplatePresets(channelType)
      .then((p) => {
        if (!cancelled) setPresets(p);
      })
      .catch(() => {
        // Non-fatal — picker just won't render. The textarea still works.
      });
    return () => {
      cancelled = true;
    };
  }, [channelType]);

  // Debounce-ish: re-render preview when value / sample selection changes.
  useEffect(() => {
    const handle = setTimeout(() => {
      startTransition(() => {
        const opts =
          sampleSource === "recent" && recentEventId
            ? { channelType, eventId: recentEventId }
            : { channelType, sampleEvent: sample };
        previewTemplate(value, opts)
          .then((res) => {
            setPreview(res.rendered);
            setPreviewError(res.error);
          })
          .catch((exc) => {
            setPreview("");
            setPreviewError(String(exc));
          });
      });
    }, 300);
    return () => clearTimeout(handle);
  }, [value, sample, sampleSource, recentEventId, channelType]);

  function insertVariable(path: string) {
    // Insert at the textarea's cursor position (or append if no focus).
    const ta = document.getElementById(
      `${name}-textarea`,
    ) as HTMLTextAreaElement | null;
    if (!ta) {
      setValue((v) => `${v}{{ ${path} }}`);
      return;
    }
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const insert = `{{ ${path} }}`;
    const next = value.slice(0, start) + insert + value.slice(end);
    setValue(next);
    // Move cursor to after the inserted token on next tick.
    requestAnimationFrame(() => {
      ta.focus();
      const pos = start + insert.length;
      ta.setSelectionRange(pos, pos);
    });
  }

  return (
    <div className="space-y-3">
      {/* Presets */}
      {presets.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[11px] uppercase tracking-[0.06em] text-fg-subtle">
            Start from a template
          </p>
          <div className="flex flex-wrap gap-1.5">
            {presets.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setValue(p.template)}
                title={p.blurb}
                className="border border-line bg-surface-1 px-2 py-1 text-xs text-fg-muted transition-colors hover:border-signal hover:bg-signal/10 hover:text-fg"
              >
                {p.name}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setValue("")}
              className="border border-dashed border-line-soft px-2 py-1 text-xs text-fg-subtle transition-colors hover:border-line hover:text-fg"
            >
              Blank
            </button>
          </div>
        </div>
      )}

      {/* Textarea */}
      <div>
        <textarea
          id={`${name}-textarea`}
          name={name}
          rows={5}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Pick a template above, or write your own"
          className="w-full border border-line bg-surface-1 px-2.5 py-2 font-mono text-xs text-fg placeholder:text-fg-disabled focus-visible:border-signal focus-visible:outline-none"
        />
      </div>

      {/* Insert-variable chips */}
      <div className="space-y-1.5">
        <p className="text-[11px] uppercase tracking-[0.06em] text-fg-subtle">
          Insert a variable
        </p>
        <div className="flex flex-wrap gap-1.5">
          {VARIABLES.map((v) => (
            <button
              key={v.path}
              type="button"
              onClick={() => insertVariable(v.path)}
              title={`Example value: ${v.example}`}
              className="inline-flex items-center gap-1.5 border border-line-soft bg-surface-1 px-2 py-1 text-xs text-fg-muted transition-colors hover:border-line hover:text-fg"
            >
              <span>{v.name}</span>
              <code className="font-mono text-[10px] text-fg-subtle">
                {`{{ ${v.path} }}`}
              </code>
            </button>
          ))}
        </div>
      </div>

      {/* Live preview */}
      <div className="border border-line-soft bg-surface-0">
        <div className="space-y-1.5 border-b border-line-soft px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] uppercase tracking-[0.06em] text-fg-subtle">
              Preview
            </span>
            {/* Source toggle: canned sample vs a real recent event.
                Think: CloudWatch's "test pattern against sample records". */}
            <div className="flex overflow-hidden border border-line-soft">
              <button
                type="button"
                onClick={() => setSampleSource("canned")}
                className={
                  sampleSource === "canned"
                    ? "bg-signal/10 px-2 py-0.5 text-[10px] text-fg"
                    : "bg-surface-1 px-2 py-0.5 text-[10px] text-fg-subtle hover:text-fg"
                }
              >
                canned sample
              </button>
              <button
                type="button"
                onClick={() => setSampleSource("recent")}
                className={
                  sampleSource === "recent"
                    ? "bg-signal/10 px-2 py-0.5 text-[10px] text-fg"
                    : "bg-surface-1 px-2 py-0.5 text-[10px] text-fg-subtle hover:text-fg"
                }
              >
                real recent event
              </button>
            </div>
          </div>
          {sampleSource === "canned" ? (
            <label className="flex items-center gap-1.5 text-[10px] text-fg-disabled">
              <span>event type:</span>
              <select
                value={sample}
                onChange={(e) => setSample(e.target.value as PreviewSampleKind)}
                className="border border-line-soft bg-surface-1 px-1.5 py-0.5 text-[10px] text-fg-muted focus-visible:border-signal focus-visible:outline-none"
              >
                {SAMPLE_EVENTS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label className="flex items-center gap-1.5 text-[10px] text-fg-disabled">
              <span>event:</span>
              {recentLoading ? (
                <span className="text-fg-subtle">loading…</span>
              ) : recentEvents.length === 0 ? (
                <span className="text-fg-subtle">no events yet</span>
              ) : (
                <select
                  value={recentEventId}
                  onChange={(e) => setRecentEventId(e.target.value)}
                  className="max-w-[60%] border border-line-soft bg-surface-1 px-1.5 py-0.5 text-[10px] text-fg-muted focus-visible:border-signal focus-visible:outline-none"
                >
                  {recentEvents.map((ev) => (
                    <option key={ev.event_id} value={ev.event_id}>
                      {formatRecentEventLabel(ev)}
                    </option>
                  ))}
                </select>
              )}
            </label>
          )}
        </div>
        <div className="px-3 py-2.5">
          {previewError ? (
            <p className="font-mono text-xs text-sev-critical">{previewError}</p>
          ) : preview.trim() ? (
            <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-fg">
              {preview}
            </pre>
          ) : (
            <p className="text-xs text-fg-disabled">
              Pick a template to see what your message will look like.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
