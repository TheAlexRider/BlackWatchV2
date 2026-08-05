import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { fetchEvent } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { TimestampCell } from "@/components/domain/TimestampCell";
import { SeverityBadge } from "@/components/domain/SeverityBadge";

export default async function EventDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const event = await fetchEvent(id);
  if (!event) notFound();

  // Strip the raw payload out for the envelope view so it can be inspected
  // independently — they are often large and noisy.
  const { raw, ...envelopeForDisplay } = (event ?? {}) as Record<string, unknown>;
  const envelopeJson = JSON.stringify(envelopeForDisplay, null, 2);
  const rawJson = raw === undefined ? null : JSON.stringify(raw, null, 2);

  return (
    <>
      <div className="mb-4">
        <Link
          href="/events"
          className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft size={12} /> back to events
        </Link>
      </div>

      <PageHeader title={event.action} subtitle={event.event_id} />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <DataPanel className="p-4">
          <SectionLabel>severity</SectionLabel>
          <div className="mt-2">
            <SeverityBadge severity={(event.severity as string) ?? null} />
          </div>
        </DataPanel>
        <DataPanel className="p-4">
          <SectionLabel>time</SectionLabel>
          <div className="mt-2">
            <TimestampCell value={event.event_time} />
          </div>
        </DataPanel>
        <DataPanel className="p-4">
          <SectionLabel>module</SectionLabel>
          <div className="mt-2 font-mono text-xs text-fg">
            {event.source?.module ?? "—"}
          </div>
        </DataPanel>
      </div>

      <div className="mt-6 space-y-2">
        <SectionLabel>envelope</SectionLabel>
        <DataPanel className="overflow-auto p-4">
          <pre className="max-w-full overflow-auto break-words whitespace-pre-wrap text-xs leading-relaxed text-fg-muted">
            {envelopeJson}
          </pre>
        </DataPanel>
      </div>

      {rawJson && (
        <div className="mt-6 space-y-2">
          <SectionLabel>raw</SectionLabel>
          <DataPanel className="overflow-auto p-4">
            <pre className="max-w-full overflow-auto break-words whitespace-pre-wrap text-xs leading-relaxed text-fg-muted">
              {rawJson}
            </pre>
          </DataPanel>
        </div>
      )}
    </>
  );
}
