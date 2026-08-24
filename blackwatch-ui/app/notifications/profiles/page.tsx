import Link from "next/link";
import { ArrowLeft, ChevronRight } from "lucide-react";

import { fetchNotificationProfiles } from "@/lib/api";
import type { NotificationProfile, NotificationProfileModule } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { StatusPill } from "@/components/ui/StatusPill";

export default async function NotificationProfilesPage() {
  const data = await fetchNotificationProfiles();
  const byModule = new Map(data.profiles.map((profile) => [profile.id, profile]));
  const configured = data.profiles.filter((profile) => profile.source === "saved").length;
  const enabled = data.profiles.filter((profile) => profile.enabled).length;

  return (
    <>
      <div className="mb-4">
        <Link href="/notifications" className="inline-flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg">
          <ArrowLeft size={12} /> back to notifications
        </Link>
      </div>

      <PageHeader
        title="Notification Studio"
        subtitle={`${configured} customized · ${enabled} enabled · choose a module, then edit an alert in plain language`}
      />

      <div className="mb-6 max-w-3xl border border-signal/20 bg-signal/5 px-4 py-3 text-sm leading-6 text-fg-muted">
        Configure what a person should understand when an alert arrives. Each
        alert type has its own wording, urgency, delivery, monitoring context,
        impact, and next steps. Advanced templates are optional.
      </div>

      <div className="space-y-6">
        {data.catalog.map((module) => (
          <ModuleProfilePanel
            key={module.key}
            module={module}
            profiles={module.events.map((event) => byModule.get(`profile:${module.key}:${event.key}`)).filter(Boolean) as NotificationProfile[]}
          />
        ))}
      </div>
    </>
  );
}

function ModuleProfilePanel({
  module,
  profiles,
}: {
  module: NotificationProfileModule;
  profiles: NotificationProfile[];
}) {
  const profileByKind = new Map(profiles.map((profile) => [profile.event_kind, profile]));
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium text-fg">{module.label}</h2>
          <p className="mt-0.5 text-xs text-fg-subtle">{module.description}</p>
        </div>
        <code className="font-mono text-[10px] text-fg-subtle">{module.key}</code>
      </div>
      <DataPanel className="overflow-hidden">
        <div className="divide-y divide-line-soft">
          {module.events.map((event) => {
            const profile = profileByKind.get(event.key);
            return (
              <Link
                key={event.key}
                href={`/notifications/profiles/${encodeURIComponent(profile?.id ?? `profile:${module.key}:${event.key}`)}`}
                className="flex items-center justify-between gap-4 px-4 py-3 transition-colors hover:bg-surface-2"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm text-fg">{event.label}</span>
                    <StatusPill
                      severity={profile?.enabled ? "resolved" : profile?.source === "saved" ? "high" : "neutral"}
                      label={profile?.enabled ? "enabled" : profile?.source === "saved" ? "saved · off" : "not configured"}
                    />
                  </div>
                  <p className="mt-1 truncate font-mono text-[11px] text-fg-subtle">{event.key}</p>
                </div>
                <ChevronRight size={14} className="shrink-0 text-fg-subtle" />
              </Link>
            );
          })}
        </div>
      </DataPanel>
    </section>
  );
}
