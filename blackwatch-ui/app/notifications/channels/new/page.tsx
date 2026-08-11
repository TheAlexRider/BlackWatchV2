import Link from "next/link";
import {
  Slack,
  Mail,
  Webhook,
  Siren,
  MessageSquare,
  Hash,
} from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { BackLink } from "@/components/ui/BackLink";
import { PickerCard } from "@/components/ui/PickerCard";
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
    blurb: "Amazon SES API via the AWS IAM role — no SMTP password.",
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
      <BackLink href="/notifications" label="back to notifications" />

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
        <PickerCard
          key={opt.type}
          href={`/notifications/channels/new?type=${opt.type}`}
          icon={<opt.icon size={14} strokeWidth={1.5} />}
          title={opt.title}
          blurb={opt.blurb}
          badge={opt.type}
        />
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
