import Link from "next/link";
import clsx from "clsx";
import { ArrowLeft, Cpu, HardDrive, MemoryStick } from "lucide-react";

import { fetchPerfQuick } from "@/lib/api";
import type {
  PerfQuickCard,
  PerfQuickExistingRule,
  PerfQuickResponse,
} from "@/lib/types";

import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { PendingButton } from "@/components/ui/PendingButton";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Input } from "@/components/ui/Input";
import { FlashToast } from "@/components/ui/FlashToast";

import { savePerfQuickAction } from "./actions";

type SearchParams = { msg?: string };

export default async function PerfQuickPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { msg } = await searchParams;
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

      {msg && <FlashToast message={msg} />}

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

// =========================================================================
// One card per metric
// =========================================================================

const METRIC_ICONS: Record<string, React.ComponentType<{ size?: number }>> = {
  memory_pct: MemoryStick,
  cpu_load_norm: Cpu,
  disk_pct_max: HardDrive,
};

function MetricCard({
  card,
  channels,
  instances,
  disabled,
}: {
  card: PerfQuickCard;
  channels: PerfQuickResponse["channels"];
  instances: PerfQuickResponse["instances"];
  disabled: boolean;
}) {
  const Icon = METRIC_ICONS[card.metric] ?? Cpu;

  // For simplicity: only surface the FIRST existing rule per metric as the
  // card's defaults. If someone has multiple (different scopes) we still
  // let them see and edit each via the full page.
  const existing: PerfQuickExistingRule | undefined = card.existing[0];
  const isLive = !!existing && existing.enabled;
  const currentThreshold = existing?.threshold ?? card.default_threshold;
  const currentWindowMin = existing
    ? Math.max(1, Math.round(existing.window_seconds / 60))
    : card.default_window_minutes;
  const currentScope: "all" | "instance" = existing?.instance_id ? "instance" : "all";
  const currentInstance = existing?.instance_id ?? "";
  const currentChannel = existing?.channels?.[0] ?? "";
  const currentSeverity = existing?.severity ?? card.default_severity;

  return (
    <DataPanel className="p-0">
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
            <div className="font-mono text-[10px] text-fg-subtle">{card.metric}</div>
          </div>
        </div>
        {existing ? (
          <StatePill enabled={existing.enabled} />
        ) : (
          <span className="text-xs text-fg-subtle">not set up</span>
        )}
      </div>

      <div className="px-4 pt-3 text-xs text-fg-muted">{card.blurb}</div>

      <form action={savePerfQuickAction} className="space-y-3 px-4 pb-4 pt-3">
        <input type="hidden" name="metric" value={card.metric} />

        {/* Threshold + window inline */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              Alert when &gt;=
            </label>
            <div className="flex items-center gap-1.5">
              <Input
                name="threshold"
                type="number"
                min={0}
                max={100}
                defaultValue={currentThreshold}
                className="w-20"
                mono
              />
              <span className="text-xs text-fg-muted">%</span>
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
              For at least
            </label>
            <div className="flex items-center gap-1.5">
              <Input
                name="window_minutes"
                type="number"
                min={1}
                max={120}
                defaultValue={currentWindowMin}
                className="w-20"
                mono
              />
              <span className="text-xs text-fg-muted">minutes</span>
            </div>
          </div>
        </div>

        {/* Scope */}
        <div className="space-y-1.5">
          <label className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            On
          </label>
          <div className="flex flex-col gap-1.5">
            <label className="flex items-center gap-2 text-xs">
              <input
                type="radio"
                name="scope"
                value="all"
                defaultChecked={currentScope === "all"}
                className="accent-signal"
              />
              <span className="text-fg-muted">all hosts</span>
            </label>
            <label className="flex items-center gap-2 text-xs">
              <input
                type="radio"
                name="scope"
                value="instance"
                defaultChecked={currentScope === "instance"}
                className="accent-signal"
              />
              <span className="text-fg-muted">just this host</span>
              <NativeSelect
                name="instance_id"
                defaultValue={currentInstance}
                className="h-7 text-xs"
              >
                <option value="">— pick host —</option>
                {instances.map((i) => (
                  <option key={i.instance_id} value={i.instance_id}>
                    {i.hostname ?? i.instance_id}
                  </option>
                ))}
              </NativeSelect>
            </label>
          </div>
        </div>

        {/* Channel */}
        <div className="space-y-1.5">
          <label className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            Send alerts to
          </label>
          <NativeSelect
            name="channel"
            defaultValue={currentChannel}
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

        {/* Severity */}
        <div className="space-y-1.5">
          <label className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            Severity
          </label>
          <NativeSelect
            name="severity"
            defaultValue={currentSeverity}
            className="w-32"
          >
            <option value="informational">informational</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="critical">critical</option>
          </NativeSelect>
        </div>

        <input type="hidden" name="enabled" value={existing?.enabled === false ? "off" : "on"} />

        <div className="flex justify-end gap-2 pt-1">
          <PendingButton
            size="sm"
            variant="primary"
            disabled={disabled}
            pendingLabel="Saving…"
          >
            Save
          </PendingButton>
        </div>
      </form>
    </DataPanel>
  );
}

function StatePill({ enabled }: { enabled: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        aria-hidden
        className={clsx(
          "h-1.5 w-1.5 rounded-full",
          enabled ? "bg-sev-resolved" : "bg-fg-subtle",
        )}
      />
      <span className="text-fg-muted">{enabled ? "on" : "off"}</span>
    </span>
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
