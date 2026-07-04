import Link from "next/link";

import { fetchNotificationCards } from "@/lib/api";

import { PageHeader } from "@/components/layout/PageHeader";
import { SectionLabel } from "@/components/layout/SectionLabel";

import { ModuleCard } from "./ModuleCard";

// Server component: fetches once, hands data down to the client ModuleCard.
// All action feedback lives inside each card, so no ?msg=… flash toast here.

export default async function RoutingPage() {
  const data = await fetchNotificationCards();
  const noChannels = data.channels.length === 0;
  const configured = data.cards.filter((c) => c.channel).length;

  return (
    <>
      <PageHeader
        title="Notifications by module"
        subtitle={
          noChannels
            ? "no channels yet — add one first"
            : `${configured} of ${data.cards.length} modules routed`
        }
      />

      {noChannels && <NoChannelsHint />}

      <IntroBanner />

      <section className="mt-6 space-y-2">
        <SectionLabel>modules</SectionLabel>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {data.cards.map((card) => (
            <ModuleCard
              key={card.module}
              card={card}
              channels={data.channels}
              disabled={noChannels}
            />
          ))}
        </div>
      </section>

      <AdvancedFooter />
    </>
  );
}

function NoChannelsHint() {
  return (
    <div className="mb-4 border border-sev-medium/30 bg-sev-medium/5 px-4 py-3 text-sm text-fg-muted">
      You need at least one notification channel before modules can route
      anywhere.{" "}
      <Link href="/notifications/channels/new" className="text-signal hover:underline">
        Add a channel →
      </Link>
    </div>
  );
}

function IntroBanner() {
  return (
    <div className="mt-4 border border-line-soft bg-surface-1 px-4 py-3 text-xs text-fg-muted">
      <span className="text-signal">▸</span> Pick a channel and severity for each
      module. That&apos;s the whole setup — no rule editor, no conditions. Anything
      more custom (specific actions, tag filters) still lives in{" "}
      <Link href="/notifications" className="text-signal hover:underline">
        advanced rules
      </Link>
      .
    </div>
  );
}

function AdvancedFooter() {
  return (
    <p className="mt-8 text-xs text-fg-subtle">
      Modules use one auto-managed rule each under the hood. Editing them
      directly in{" "}
      <Link href="/notifications" className="text-signal hover:underline">
        advanced rules
      </Link>{" "}
      is discouraged — the cards will overwrite your changes on save.
    </p>
  );
}
