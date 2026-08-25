import { AlertTriangle, Check, ChevronDown, Save, Send } from "lucide-react";
import { notFound } from "next/navigation";

import { fetchNotificationChannels, fetchNotificationProfiles } from "@/lib/api";
import type { NotificationProfile, NotificationProfileContent } from "@/lib/types";
import { BackLink } from "@/components/ui/BackLink";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { DataPanel } from "@/components/layout/DataPanel";
import { FlashToast } from "@/components/ui/FlashToast";
import { Input } from "@/components/ui/Input";
import { ProfilePreview } from "@/components/domain/notifications/ProfilePreview";
import { saveNotificationProfileAction, testNotificationProfileAction } from "../../profile-actions";

type SearchParams = { msg?: string };

const SEVERITIES = ["informational", "low", "medium", "high", "critical"] as const;
const CONTENT_FIELDS: Array<{
  key: keyof NotificationProfileContent;
  label: string;
  hint: string;
  multiline?: boolean;
}> = [
  { key: "title", label: "Message title", hint: "A short sentence people can scan quickly." },
  { key: "what_happened", label: "What happened", hint: "Explain the signal in plain language.", multiline: true },
  { key: "why_it_matters", label: "Why it matters", hint: "Give the receiver enough context to decide what to do.", multiline: true },
  { key: "evidence", label: "Evidence", hint: "Point to the observed value, actor, target, or event.", multiline: true },
  { key: "monitoring_method", label: "How we monitor it", hint: "Name the check, collector, or signal that produced it.", multiline: true },
  { key: "impact", label: "Possible impact", hint: "Describe the customer or technical consequence.", multiline: true },
  { key: "next_steps", label: "Recommended next steps", hint: "Give a short, ordered response for the on-call person.", multiline: true },
  { key: "recovery", label: "Recovery", hint: "Explain how recovery will be recognized.", multiline: true },
  { key: "runbook_url", label: "Runbook link", hint: "Optional URL to the team’s response guide." },
];

export default async function NotificationProfilePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const [{ id }, { msg }, data, channelsData] = await Promise.all([
    params,
    searchParams,
    fetchNotificationProfiles(),
    fetchNotificationChannels(),
  ]);
  const profile = data.profiles.find((item) => item.id === decodeURIComponent(id));
  if (!profile) notFound();
  const eventSpec = data.catalog
    .find((module) => module.key === profile.module)
    ?.events.find((event) => event.key === profile.event_kind);
  const availableFields = eventSpec?.available_fields ?? ["{target_name}", "{severity}", "{evidence}", "{monitoring_method}", "{impact}"];

  return (
    <>
      <BackLink href="/notifications/profiles" label="back to Notification Studio" />
      {msg && <FlashToast message={msg} />}
      <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-signal">
            {profile.module} · {profile.event_kind}
          </p>
          <h1 className="mt-2 text-xl text-fg">{profile.label}</h1>
          <p className="mt-1 max-w-2xl text-sm text-fg-muted">{profile.description}</p>
        </div>
        <StatusNote profile={profile} />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(20rem,0.72fr)]">
        <form action={saveNotificationProfileAction} data-notification-profile className="space-y-6">
          <input type="hidden" name="id" value={profile.id} />
          <input type="hidden" name="module" value={profile.module} />
          <input type="hidden" name="event_kind" value={profile.event_kind} />

          <DataPanel className="p-5" scrollX={false}>
            <SectionTitle title="When this alert should be sent" subtitle="Turn this alert on, choose urgency, and decide where it should arrive." />
            <div className="mt-5 flex items-center justify-between border border-line-soft bg-surface-2 px-3 py-3">
              <div>
                <p className="text-sm text-fg">Enable this alert</p>
                <p className="mt-0.5 text-xs text-fg-subtle">BlackWatch will route matching events through the shared delivery worker.</p>
              </div>
              <Checkbox name="enabled" defaultChecked={profile.enabled} aria-label="Enable this alert" />
            </div>

            <div className="mt-5 grid gap-5 md:grid-cols-2">
              <ChoiceGroup title="Urgency" hint="Only selected severities will use this profile.">
                <div className="flex flex-wrap gap-1.5">
                  {SEVERITIES.map((severity) => (
                    <label key={severity} className="inline-flex cursor-pointer items-center gap-2 border border-line bg-surface-1 px-2.5 py-2 text-xs text-fg-muted transition-colors hover:bg-surface-2 has-[:checked]:border-signal has-[:checked]:bg-signal/10 has-[:checked]:text-fg">
                      <Checkbox name="severity" value={severity} defaultChecked={profile.severities.includes(severity)} />
                      {severity}
                    </label>
                  ))}
                </div>
              </ChoiceGroup>
              <ChoiceGroup title="Send to" hint="Pick one or more configured channels.">
                {channelsData.channels.length ? (
                  <div className="flex flex-wrap gap-1.5">
                    {channelsData.channels.map((channel) => (
                      <label key={channel.name} className="inline-flex cursor-pointer items-center gap-2 border border-line bg-surface-1 px-2.5 py-2 text-xs text-fg-muted transition-colors hover:bg-surface-2 has-[:checked]:border-signal has-[:checked]:bg-signal/10 has-[:checked]:text-fg">
                        <Checkbox name="channel" value={channel.name} defaultChecked={profile.channels.includes(channel.name)} />
                        <span>{channel.name}</span>
                        <span className="font-mono text-[10px] text-fg-subtle">{channel.type}</span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <p className="border border-sev-medium/30 bg-sev-medium/10 px-3 py-2 text-xs text-sev-medium">Add a notification channel before enabling this alert.</p>
                )}
              </ChoiceGroup>
            </div>

            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <label className="text-xs text-fg-muted">
                Throttle repeated alerts (seconds)
                <Input name="throttle_seconds" type="number" min={0} step={60} defaultValue={profile.throttle_seconds} className="mt-1" />
              </label>
              <label className="text-xs text-fg-muted">
                Digest window (seconds, 0 = off)
                <Input name="digest_window_seconds" type="number" min={0} step={60} defaultValue={profile.digest_window_seconds} className="mt-1" />
              </label>
            </div>
          </DataPanel>

          <DataPanel className="p-5" scrollX={false}>
            <SectionTitle title="What people should understand" subtitle="These fields become the notification. Use the supplied placeholders when you want live event details." />
            <div className="mt-5 space-y-4">
              {CONTENT_FIELDS.map((field) => (
                <label key={field.key} className="block text-xs text-fg-muted">
                  <span>{field.label}</span>
                  <span className="ml-2 text-fg-subtle">{field.hint}</span>
                  {field.multiline ? (
                    <textarea name={field.key} defaultValue={profile.content[field.key]} rows={3} className="mt-1 block w-full resize-y border border-line bg-surface-1 px-2.5 py-2 text-sm leading-5 text-fg placeholder:text-fg-disabled focus-visible:border-signal focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal" />
                  ) : (
                    <Input name={field.key} defaultValue={profile.content[field.key]} className="mt-1" />
                  )}
                </label>
              ))}
            </div>
            <p className="mt-4 border-l-2 border-signal/40 pl-3 font-mono text-[11px] leading-5 text-fg-subtle">
              Available placeholders: {availableFields.join(" · ")}
            </p>
          </DataPanel>

          <DataPanel className="p-5" scrollX={false}>
            <details>
              <summary className="flex cursor-pointer list-none items-center gap-2 text-sm text-fg [&::-webkit-details-marker]:hidden">
                <ChevronDown size={14} className="text-fg-subtle" /> Advanced template (optional)
              </summary>
              <p className="mt-3 text-xs leading-5 text-fg-subtle">Leave this blank to use the guided fields. Advanced templates use the existing Jinja event context and are intended for experienced operators.</p>
              <textarea name="advanced_template" defaultValue={profile.advanced_template ?? ""} rows={8} className="mt-3 block w-full resize-y border border-line bg-surface-1 px-2.5 py-2 font-mono text-xs leading-5 text-fg placeholder:text-fg-disabled focus-visible:border-signal focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal" placeholder="{{ event.action }} on {{ event.target.name }}" />
            </details>
          </DataPanel>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-fg-subtle">Saving updates the alert profile and its compiled delivery rule.</p>
            <Button type="submit" variant="primary"><Save size={13} /> Save profile</Button>
          </div>
        </form>

        <aside className="space-y-6 xl:sticky xl:top-5 xl:self-start">
          <ProfilePreview profile={profile} channels={channelsData.channels} />
          <DataPanel className="p-5" scrollX={false}>
            <SectionTitle title="Send a test" subtitle="Uses the saved version and sends a sample through every selected channel." />
            <form action={testNotificationProfileAction} className="mt-4">
              <input type="hidden" name="id" value={profile.id} />
              <Button type="submit" size="sm" disabled={!profile.channels.length}><Send size={13} /> Send test notification</Button>
              {!profile.channels.length && <p className="mt-3 text-xs text-fg-subtle">Save at least one channel first.</p>}
            </form>
          </DataPanel>
        </aside>
      </div>
    </>
  );
}

function SectionTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return <div><h2 className="text-sm text-fg">{title}</h2><p className="mt-1 text-xs leading-5 text-fg-subtle">{subtitle}</p></div>;
}

function ChoiceGroup({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return <div><p className="text-xs text-fg-muted">{title}</p><p className="mt-1 text-[11px] text-fg-subtle">{hint}</p><div className="mt-2">{children}</div></div>;
}

function StatusNote({ profile }: { profile: NotificationProfile }) {
  return (
    <div className="flex items-center gap-2 border border-line-soft bg-surface-1 px-3 py-2 text-xs text-fg-muted">
      {profile.enabled ? <Check size={13} className="text-sev-resolved" /> : <AlertTriangle size={13} className="text-sev-medium" />}
      {profile.enabled ? "enabled" : profile.source === "default" ? "not configured" : "saved but off"}
    </div>
  );
}
