"use client";

import { useState } from "react";
import { Eye, Loader2 } from "lucide-react";
import { previewNotificationProfile } from "@/lib/api";
import type { NotificationChannel, NotificationProfile } from "@/lib/types";
import { Button } from "@/components/ui/Button";

const CONTENT_FIELDS = [
  "title",
  "what_happened",
  "facts",
  "decision",
  "next_steps",
  "why_it_matters",
  "evidence",
  "monitoring_method",
  "impact",
  "recovery",
  "runbook_url",
] as const;

export function ProfilePreview({
  profile,
  channels,
}: {
  profile: NotificationProfile;
  channels: NotificationChannel[];
}) {
  const [rendered, setRendered] = useState(profile.message_template);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const channel = channels.find((item) => profile.channels.includes(item.name)) ?? channels[0];

  async function refresh() {
    setBusy(true);
    setError(null);
    try {
      const form = document.querySelector<HTMLFormElement>("form[data-notification-profile]");
      const formData = form ? new FormData(form) : null;
      const content = Object.fromEntries(
        CONTENT_FIELDS.map((field) => [field, String(formData?.get(field) ?? profile.content[field])]),
      );
      const result = await previewNotificationProfile(
        { ...profile, content },
        channel?.type ?? "slack",
      );
      setRendered(result.rendered);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Preview failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border border-line-soft bg-surface-1">
      <div className="flex items-center justify-between border-b border-line-soft px-4 py-3">
        <div>
          <p className="text-sm text-fg">Live example</p>
          <p className="mt-0.5 text-xs text-fg-subtle">
            Preview the current editor values{channel ? " · " + channel.type : ""}.
          </p>
        </div>
        <Button type="button" size="sm" onClick={refresh} disabled={busy}>
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Eye size={13} />}
          Refresh preview
        </Button>
      </div>
      <pre className="min-h-36 whitespace-pre-wrap px-4 py-4 font-mono text-xs leading-5 text-fg-muted">
        {rendered}
      </pre>
      {error && <p className="border-t border-sev-critical/30 bg-sev-critical/10 px-4 py-2 text-xs text-sev-critical">{error}</p>}
    </div>
  );
}
