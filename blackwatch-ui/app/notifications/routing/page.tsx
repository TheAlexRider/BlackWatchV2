import Link from "next/link";
import clsx from "clsx";
import {
  Activity,
  Archive,
  BellOff,
  Database,
  Eye,
  KeyRound,
  Network,
  Pencil,
  Server,
  Shield,
} from "lucide-react";

import { fetchNotificationCards } from "@/lib/api";
import type {
  CardThresholdKey,
  NotificationCard,
  NotificationCardsResponse,
} from "@/lib/types";

import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { PendingButton } from "@/components/ui/PendingButton";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { FlashToast } from "@/components/ui/FlashToast";
import {
  saveCardAction,
  toggleCardAction,
  testCardAction,
  silenceCardAction,
} from "./actions";

type SearchParams = { msg?: string };

export default async function RoutingPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { msg } = await searchParams;
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

      {msg && <FlashToast message={msg} />}

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

// =========================================================================
// One card per module
// =========================================================================

const ICONS: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  database: Database,
  shield: Shield,
  archive: Archive,
  eye: Eye,
  network: Network,
  server: Server,
  activity: Activity,
  "key-round": KeyRound,
};

function ModuleCard({
  card,
  channels,
  disabled,
}: {
  card: NotificationCard;
  channels: NotificationCardsResponse["channels"];
  disabled: boolean;
}) {
  const Icon = ICONS[card.icon] ?? Shield;
  const now = Date.now();
  const silencedUntil = card.silence_until ? new Date(card.silence_until).getTime() : 0;
  const isSilenced = silencedUntil > now;
  const isRouted = !!card.channel;
  const isLive = isRouted && card.enabled && !isSilenced;

  return (
    <DataPanel className="p-0">
      {/* Header row */}
      <div className="flex items-center justify-between border-b border-line-soft px-4 py-3">
        <div className="flex items-center gap-3">
          <span
            aria-hidden
            className={clsx(
              "flex h-8 w-8 items-center justify-center border",
              isLive
                ? "border-signal/30 bg-signal/5 text-signal"
                : "border-line-soft bg-surface-2 text-fg-muted",
            )}
          >
            <Icon size={14} />
          </span>
          <div>
            <div className="text-sm text-fg">{card.label}</div>
            <div className="font-mono text-[10px] text-fg-subtle">{card.module}</div>
          </div>
        </div>
        <StateBadge live={isLive} silenced={isSilenced} routed={isRouted} enabled={card.enabled} />
      </div>

      {/* Blurb */}
      <div className="px-4 pt-3 text-xs text-fg-muted">{card.blurb}</div>

      {/* Setup form */}
      <form action={saveCardAction} className="space-y-3 px-4 pb-4 pt-3">
        <input type="hidden" name="module" value={card.module} />
        {/* Always send enabled=on when Save is clicked — the toggle for
            on/off lives in a separate row below the form so the user's Save
            doesn't accidentally flip enablement back on. */}
        <input type="hidden" name="enabled" value={card.enabled ? "on" : "off"} />

        <div className="space-y-1.5">
          <label className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            Send alerts to
          </label>
          <NativeSelect
            name="channel"
            defaultValue={card.channel ?? ""}
            disabled={disabled}
            className="w-full"
          >
            <option value="">— none (turn off) —</option>
            {channels.map((ch) => (
              <option key={ch.name} value={ch.name} disabled={!ch.enabled}>
                {ch.name} · {ch.type}
                {!ch.enabled ? " (disabled)" : ""}
              </option>
            ))}
          </NativeSelect>
        </div>

        <div className="space-y-1.5">
          <label className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            Alert me on
          </label>
          <ThresholdRadios name="threshold" current={card.threshold} />
        </div>

        <div className="flex items-center justify-between gap-2 pt-1">
          <PendingButton
            size="sm"
            variant="primary"
            disabled={disabled}
            pendingLabel="Saving…"
          >
            Save
          </PendingButton>
          <CardControls card={card} isRouted={isRouted} isSilenced={isSilenced} />
        </div>
      </form>

      {isRouted && (
        <CustomizeMessageLink
          channelName={card.channel!}
          channels={channels}
        />
      )}
    </DataPanel>
  );
}

function CustomizeMessageLink({
  channelName,
  channels,
}: {
  channelName: string;
  channels: NotificationCardsResponse["channels"];
}) {
  const channel = channels.find((c) => c.name === channelName);
  if (!channel) return null;
  return (
    <div className="border-t border-line-soft bg-surface-1 px-4 py-2">
      <Link
        href={`/notifications/channels/${encodeURIComponent(channel.id)}`}
        className="inline-flex items-center gap-1.5 text-[11px] text-fg-subtle hover:text-signal"
      >
        <Pencil size={10} />
        <span>Customize message format for {channelName}</span>
      </Link>
    </div>
  );
}

// =========================================================================
// Threshold radios
// =========================================================================

const THRESHOLD_OPTIONS: Array<{ key: CardThresholdKey; label: string; hint: string }> = [
  { key: "critical", label: "Only critical", hint: "emergencies only" },
  { key: "high", label: "Critical + high", hint: "recommended" },
  { key: "medium", label: "≥ medium", hint: "medium and above" },
  { key: "low", label: "Everything except info", hint: "noisiest" },
];

function ThresholdRadios({ name, current }: { name: string; current: CardThresholdKey }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {THRESHOLD_OPTIONS.map((opt) => {
        const selected = opt.key === current;
        return (
          <label
            key={opt.key}
            className={clsx(
              "flex cursor-pointer flex-col gap-0.5 border px-2.5 py-2 text-xs transition-colors",
              selected
                ? "border-signal/50 bg-signal/5 text-fg"
                : "border-line-soft bg-surface-1 text-fg-muted hover:bg-surface-2",
            )}
          >
            <span className="flex items-center gap-1.5">
              <input
                type="radio"
                name={name}
                value={opt.key}
                defaultChecked={selected}
                className="accent-signal"
              />
              <span>{opt.label}</span>
            </span>
            <span className="pl-5 text-[10px] text-fg-subtle">{opt.hint}</span>
          </label>
        );
      })}
    </div>
  );
}

// =========================================================================
// Header state badge
// =========================================================================

function StateBadge({
  live,
  silenced,
  routed,
  enabled,
}: {
  live: boolean;
  silenced: boolean;
  routed: boolean;
  enabled: boolean;
}) {
  if (silenced)
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <BellOff size={11} className="text-sev-medium" aria-hidden />
        <span className="text-fg-muted">silenced</span>
      </span>
    );
  if (!routed)
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span className="h-1.5 w-1.5 rounded-full bg-fg-subtle" aria-hidden />
        <span className="text-fg-subtle">not set up</span>
      </span>
    );
  if (!enabled)
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span className="h-1.5 w-1.5 rounded-full bg-fg-subtle" aria-hidden />
        <span className="text-fg-subtle">disabled</span>
      </span>
    );
  if (live)
    return (
      <span className="inline-flex items-center gap-1.5 text-xs">
        <span className="h-1.5 w-1.5 rounded-full bg-sev-resolved" aria-hidden />
        <span className="text-fg-muted">on</span>
      </span>
    );
  return null;
}

// =========================================================================
// Per-card control row (test / silence / on-off)
// =========================================================================

function CardControls({
  card,
  isRouted,
  isSilenced,
}: {
  card: NotificationCard;
  isRouted: boolean;
  isSilenced: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-1.5">
      <form action={testCardAction} className="inline">
        <input type="hidden" name="module" value={card.module} />
        <PendingButton
          size="sm"
          variant="secondary"
          disabled={!isRouted}
          pendingLabel="Sending…"
        >
          Test
        </PendingButton>
      </form>

      {isRouted && (
        <form action={silenceCardAction} className="inline-flex items-center gap-1">
          <input type="hidden" name="module" value={card.module} />
          <NativeSelect name="hours" defaultValue={isSilenced ? "0" : "1"} className="h-7 text-xs">
            <option value="1">1h</option>
            <option value="4">4h</option>
            <option value="24">24h</option>
            <option value="0">clear</option>
          </NativeSelect>
          <PendingButton size="sm" variant="secondary" pendingLabel="…">
            {isSilenced ? "Un-silence" : "Silence"}
          </PendingButton>
        </form>
      )}

      {isRouted && (
        <form action={toggleCardAction} className="inline">
          <input type="hidden" name="module" value={card.module} />
          <input type="hidden" name="channel" value={card.channel ?? ""} />
          <input type="hidden" name="threshold" value={card.threshold} />
          <input type="hidden" name="target" value={card.enabled ? "off" : "on"} />
          <PendingButton size="sm" variant="secondary" pendingLabel="…">
            {card.enabled ? "Turn off" : "Turn on"}
          </PendingButton>
        </form>
      )}
    </div>
  );
}

// =========================================================================
// Bits
// =========================================================================

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
      more custom (specific actions, tag filters, etc.) still lives in{" "}
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
