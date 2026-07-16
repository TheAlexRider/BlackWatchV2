import { notFound } from "next/navigation";

import { fetchNotificationChannel } from "@/lib/api";
import type { ChannelType } from "@/lib/types";
import { CHANNEL_TYPES } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { BackLink } from "@/components/ui/BackLink";
import { ChannelForm } from "@/components/domain/notifications/ChannelForm";

export default async function EditChannelPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const channel = await fetchNotificationChannel(id);
  if (!channel) notFound();
  const knownType = (CHANNEL_TYPES as string[]).includes(channel.type)
    ? (channel.type as ChannelType)
    : null;

  return (
    <>
      <BackLink href="/notifications" label="back to notifications" />

      <PageHeader title={`Edit · ${channel.name}`} subtitle={channel.id} />

      <DataPanel className="overflow-hidden">
        {knownType ? (
          <ChannelForm type={knownType} existing={channel} />
        ) : (
          <div className="p-4 text-xs text-fg-muted">
            Unknown channel type: <code className="text-fg">{channel.type}</code>
            <pre className="mt-2 overflow-auto bg-surface-2 p-3 text-[11px]">
              {JSON.stringify(channel.config, null, 2)}
            </pre>
          </div>
        )}
      </DataPanel>
    </>
  );
}
