import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { fetchPerfQuick } from "@/lib/api";

import { PageHeader } from "@/components/layout/PageHeader";
import { SectionLabel } from "@/components/layout/SectionLabel";

import { MetricCard } from "./MetricCard";

// Server component: fetch once, render cards. All action feedback lives
// inside each card via useActionState — no ?msg=… banner here.
export default async function PerfQuickPage() {
  const data = await fetchPerfQuick();
  const noChannels = data.channels.length === 0;
  const configured = data.cards.filter((c) => c.existing.length > 0).length;

  return (
    <>
      <div className="mb-4">
        <Link
          href="/notifications"
          className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft size={12} /> back to notifications
        </Link>
      </div>

      <PageHeader
        title="Performance alerts · quick setup"
        subtitle={
          noChannels
            ? "no channels yet — add one first"
            : `${configured} of ${data.cards.length} metrics wired up`
        }
      />

      {noChannels && <NoChannelsHint />}

      <IntroBanner />

      <section className="mt-6 space-y-2">
        <SectionLabel>metrics</SectionLabel>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {data.cards.map((card) => (
            <MetricCard
              key={card.metric}
              card={card}
              channels={data.channels}
              instances={data.instances}
              disabled={noChannels}
            />
          ))}
        </div>
      </section>

      <p className="mt-8 text-xs text-fg-subtle">
        Need something more specific — one instance, a tag scope, or an unusual
        window?{" "}
        <Link href="/notifications/perf-alerts/new" className="text-signal hover:underline">
          Use the full form
        </Link>
        .
      </p>
    </>
  );
}

function NoChannelsHint() {
  return (
    <div className="mb-4 border border-sev-medium/30 bg-sev-medium/5 px-4 py-3 text-sm text-fg-muted">
      You need at least one notification channel before performance alerts can
      route anywhere.{" "}
      <Link href="/notifications/channels/new" className="text-signal hover:underline">
        Add a channel →
      </Link>
    </div>
  );
}

function IntroBanner() {
  return (
    <div className="mt-4 border border-line-soft bg-surface-1 px-4 py-3 text-xs text-fg-muted">
      <span className="text-signal">▸</span> Pick a threshold and a channel for
      each metric. Alerts fire when the metric stays above the threshold for the
      chosen window across the chosen hosts.
    </div>
  );
}
