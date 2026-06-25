import Link from "next/link";
import clsx from "clsx";
import {
  ArrowLeft,
  Slack,
  Mail,
  Webhook,
  Siren,
  MessageSquare,
  Hash,
} from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { ChannelForm } from "@/components/domain/notifications/ChannelForm";
import { CHANNEL_TYPES, type ChannelType } from "@/lib/types";

type SearchParams = { type?: string };

const TYPE_CARDS: Array<{
  type: ChannelType;
  title: string;
  blurb: string;
  icon: typeof Slack;
}> = [
  {
    type: "slack",
    title: "Slack",
    blurb: "Incoming webhook URL — one field, you're done.",
    icon: Slack,
  },
  {
    type: "webhook",
    title: "Webhook",
    blurb: "Plain HTTP POST. For local testing or custom relays.",
    icon: Webhook,
  },
  {
    type: "email",
    title: "Email",
    blurb: "SMTP — host/port/from/to. Password via env var.",
    icon: Mail,
  },
  {
    type: "pagerduty",
    title: "PagerDuty",
    blurb: "Events API v2. Routing key via env var.",
    icon: Siren,
  },
  {
    type: "teams",
    title: "Teams",
    blurb: "Incoming webhook URL.",
    icon: MessageSquare,
  },
  {
    type: "discord",
    title: "Discord",
    blurb: "Webhook URL.",
    icon: Hash,
  },
];

export default async function NewChannelPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { type } = await searchParams;
  const chosen = (CHANNEL_TYPES as string[]).includes(type ?? "")
    ? (type as ChannelType)
    : null;

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
        title={chosen ? `Add ${labelFor(chosen)} channel` : "Add channel"}
        subtitle={chosen ? "Fill in the URL / key. Save. Test." : "Pick a channel type."}
      />

      {chosen ? (
        <DataPanel className="overflow-hidden">
          <ChannelForm type={chosen} />
        </DataPanel>
      ) : (
        <TypePicker />
      )}
    </>
  );
}

function TypePicker() {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
      {TYPE_CARDS.map((opt) => (
        <Link
          key={opt.type}
          href={`/notifications/channels/new?type=${opt.type}`}
          className={clsx(
            "group flex flex-col gap-2 border border-line-soft bg-surface-1 px-4 py-4",
            "transition-colors hover:border-line hover:bg-surface-2",
          )}
        >
          <div className="flex items-center gap-2">
            <opt.icon
              size={14}
              strokeWidth={1.5}
              className="text-fg-subtle group-hover:text-signal"
            />
            <span className="text-sm text-fg">{opt.title}</span>
            <code className="ml-auto font-mono text-[10px] text-fg-subtle">
              {opt.type}
            </code>
          </div>
          <p className="text-xs text-fg-muted">{opt.blurb}</p>
        </Link>
      ))}
    </div>
  );
}

function labelFor(t: ChannelType): string {
  switch (t) {
    case "slack":
      return "Slack";
    case "webhook":
      return "webhook";
    case "email":
      return "email";
    case "pagerduty":
      return "PagerDuty";
    case "teams":
      return "Teams";
    case "discord":
      return "Discord";
  }
}
