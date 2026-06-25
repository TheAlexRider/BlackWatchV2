"use client";

import { useEffect, useState, useTransition } from "react";
import {
  fetchTemplatePresets,
  previewTemplate,
  type TemplatePreset,
} from "@/lib/api";

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
  const [, startTransition] = useTransition();

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

  // Debounce-ish: re-render preview when value changes, but not on every keystroke.
  // 300ms feels live without spamming the backend.
  useEffect(() => {
    const handle = setTimeout(() => {
      startTransition(() => {
        previewTemplate(value)
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
  }, [value]);

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
        <div className="flex items-baseline justify-between border-b border-line-soft px-3 py-1.5">
          <span className="text-[11px] uppercase tracking-[0.06em] text-fg-subtle">
            Preview
          </span>
          <span className="text-[10px] text-fg-disabled">
            using a sample failed VPN login
          </span>
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
