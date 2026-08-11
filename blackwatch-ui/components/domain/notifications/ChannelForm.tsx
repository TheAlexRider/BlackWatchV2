import Link from "next/link";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { FormRow } from "@/components/ui/FormRow";
import { Checkbox } from "@/components/ui/Checkbox";
import type { ChannelType, NotificationChannel } from "@/lib/types";
import { saveChannelAction } from "@/app/notifications/actions";
import { TemplateEditor } from "./TemplateEditor";

// Per-channel-type form. Replaces the old YAML textarea with structured
// fields specific to each provider. Secrets are referenced by env-var name
// only — they never go in the database.
export function ChannelForm({
  type,
  existing,
}: {
  type: ChannelType;
  existing?: NotificationChannel;
}) {
  const cfg = (existing?.config as Record<string, unknown>) ?? {};
  const isEdit = !!existing;

  return (
    <form action={saveChannelAction}>
      <input type="hidden" name="id" value={existing?.id ?? ""} />
      <input type="hidden" name="type" value={type} />

      {/* core fields */}
      <FormRow label="Name">
        <Input
          name="name"
          required
          defaultValue={existing?.name ?? ""}
          placeholder={namePlaceholder(type)}
        />
      </FormRow>

      <FormRow label="Enabled">
        <Checkbox
          name="enabled"
          defaultChecked={isEdit ? existing?.enabled : true}
          label="send when matched"
        />
      </FormRow>

      {/* per-type fields */}
      {(type === "slack" || type === "teams" || type === "discord") && (
        <FormRow label="Webhook URL">
          <div className="space-y-2">
            <Input
              name="url"
              required
              mono
              defaultValue={String(cfg.url ?? "")}
              placeholder={webhookPlaceholder(type)}
            />
            <HelpHint {...webhookHelp(type)} />
          </div>
        </FormRow>
      )}

      {type === "webhook" && (
        <>
          <FormRow label="URL">
            <div className="space-y-2">
              <Input
                name="url"
                required
                mono
                defaultValue={String(cfg.url ?? "")}
                placeholder="http://host.docker.internal:9000/hook"
              />
              <HelpHint
                text="POST with a JSON body containing the event. Use this for local debugging, custom relays, or n8n/Pipedream automations."
              />
            </div>
          </FormRow>
        </>
      )}

      {type === "email" && (
        <>
          <div className="border-b border-line-soft bg-surface-1 px-4 py-3">
            <HelpHint
              text="Amazon SES API is the default and uses the app's AWS IAM role. No SMTP password or .env secret is required. An SMTP fallback is available for manually maintained non-SES configs."
              learnHref="/docs/notifications-setup"
              learnLabel="Setup guide"
            />
          </div>
          <FormRow label="AWS region" hint="Region where your SES identity is verified">
            <Input
              name="aws_region"
              required
              mono
              defaultValue={String(cfg.aws_region ?? "us-west-1")}
              placeholder="us-west-1"
            />
          </FormRow>
          <FormRow label="Configuration set" hint="Optional SES configuration set">
            <Input
              name="configuration_set"
              mono
              defaultValue={String(cfg.configuration_set ?? "")}
              placeholder="blackwatch-events"
            />
          </FormRow>
          <FormRow label="From">
            <Input
              name="from_addr"
              required
              mono
              defaultValue={String(cfg.from_addr ?? "")}
              placeholder="alerts@mail.example.com"
            />
          </FormRow>
          <FormRow label="To" hint="comma-separated">
            <Input
              name="to_addrs"
              required
              mono
              defaultValue={
                Array.isArray(cfg.to_addrs) ? (cfg.to_addrs as string[]).join(", ") : ""
              }
              placeholder="you@example.com, team@example.com"
            />
          </FormRow>
        </>
      )}

      {type === "pagerduty" && (
        <FormRow label="Routing key env" hint="env name only — never the value">
          <div className="space-y-2">
            <Input
              name="routing_key_env"
              required
              mono
              className="w-72"
              defaultValue={String(cfg.routing_key_env ?? "")}
              placeholder="PD_ROUTING_KEY"
            />
            <HelpHint
              text="In PagerDuty: Services → your service → Integrations → add an Events API v2 integration. The integration key is the routing key."
              learnHref="https://support.pagerduty.com/main/docs/services-and-integrations"
              learnLabel="PagerDuty docs"
            />
          </div>
        </FormRow>
      )}

      {/* Message — pulled OUT of "advanced" because it's the thing users
          most want to customize. The TemplateEditor handles preset picker,
          variable insertion, and live preview. */}
      <FormRow label="Message">
        <TemplateEditor
          name="message_template"
          channelType={type}
          defaultValue={existing?.message_template ?? ""}
        />
      </FormRow>

      {/* Sending behaviour — friendly labels instead of "dedup window s" etc.
          Every knob is one plain-English sentence and a number input. */}
      <details className="border-t border-line-soft px-4 py-3">
        <summary className="cursor-pointer text-xs uppercase tracking-[0.08em] text-fg-subtle hover:text-fg">
          More options · how often to send & retry
        </summary>
        <div className="mt-4 space-y-3">
          <SettingRow
            label="Don't send the same alert again for"
            hint="If the same kind of event (same action + user + target) fires again within this many seconds, we stay quiet. 300 s = 5 min."
            name="dedup_window_seconds"
            unit="seconds"
            defaultValue={existing?.dedup_window_seconds ?? 300}
          />
          <SettingRow
            label="Maximum alerts per minute"
            hint="Cap on outgoing messages. 0 means no cap."
            name="rate_limit_per_min"
            unit="per minute"
            defaultValue={existing?.rate_limit_per_min ?? 0}
          />
          <SettingRow
            label="Group similar alerts together for"
            hint="Wait this long after the first alert, then send one digest with all alerts that piled up. 0 means send each alert immediately."
            name="digest_window_seconds"
            unit="seconds"
            defaultValue={existing?.digest_window_seconds ?? 0}
          />
          <SettingRow
            label="If sending fails, try again"
            hint="How many times to retry a failed delivery before giving up."
            name="retries"
            unit="times"
            defaultValue={existing?.retries ?? 3}
          />
          <SettingRow
            label="Wait between retries"
            hint="Pause this long between retry attempts."
            name="retry_backoff_seconds"
            unit="seconds"
            defaultValue={existing?.retry_backoff_seconds ?? 5}
          />
        </div>
      </details>

      <div className="flex items-center gap-3 border-t border-line-soft bg-surface-1 px-4 py-3">
        <Button type="submit" variant="primary" size="sm">
          {isEdit ? "Save changes" : "Add channel"}
        </Button>
        <Link
          href="/notifications"
          className="text-xs text-fg-muted hover:text-fg"
        >
          cancel
        </Link>
      </div>
    </form>
  );
}

// A friendly setting row: full-sentence label, plain-English description
// underneath, and the number input on the right with its unit alongside.
// This is the "make it less technical" rewrite of the old NumberWithLabel —
// users now read "Don't send the same alert again for [300] seconds" instead
// of "DEDUP WINDOW S [300]".
function SettingRow({
  label,
  hint,
  name,
  unit,
  defaultValue,
}: {
  label: string;
  hint: string;
  name: string;
  unit: string;
  defaultValue: number;
}) {
  return (
    <div className="grid grid-cols-[1fr_auto] items-start gap-4 border-b border-line-soft pb-3 last:border-0 last:pb-0">
      <div>
        <p className="text-sm text-fg">{label}</p>
        <p className="mt-0.5 text-[11px] leading-relaxed text-fg-subtle">
          {hint}
        </p>
      </div>
      <div className="flex items-center gap-2 pt-0.5">
        <Input
          name={name}
          type="number"
          mono
          defaultValue={String(defaultValue)}
          className="w-20 text-right"
        />
        <span className="text-xs text-fg-muted">{unit}</span>
      </div>
    </div>
  );
}

function namePlaceholder(type: ChannelType): string {
  switch (type) {
    case "slack":
      return "slack-security";
    case "webhook":
      return "local-webhook";
    case "email":
      return "ops-email";
    case "pagerduty":
      return "ops-pagerduty";
    case "teams":
      return "teams-security";
    case "discord":
      return "discord-alerts";
  }
}

function webhookPlaceholder(type: "slack" | "teams" | "discord"): string {
  switch (type) {
    case "slack":
      return "https://hooks.slack.com/services/REPLACE/ME";
    case "teams":
      return "https://outlook.office.com/webhook/REPLACE";
    case "discord":
      return "https://discord.com/api/webhooks/REPLACE";
  }
}

// Plain-English where-to-find-it for each webhook-style provider. Avoids the
// most common confusion ("which URL? the workspace URL? the channel URL?").
function webhookHelp(type: "slack" | "teams" | "discord"): {
  text: string;
  learnHref: string;
  learnLabel: string;
} {
  switch (type) {
    case "slack":
      return {
        text:
          "In Slack: Apps → Incoming Webhooks → Add to Slack → pick a channel. Copy the URL it gives you here. It starts with https://hooks.slack.com/services/.",
        learnHref: "https://api.slack.com/messaging/webhooks",
        learnLabel: "Slack docs",
      };
    case "teams":
      return {
        text:
          "In a Teams channel: ⋯ → Connectors → Incoming Webhook → Configure → name it → Create. Copy the URL it shows. (Teams webhooks are being deprecated — Workflows is the replacement; the URL still works.)",
        learnHref:
          "https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook",
        learnLabel: "Teams docs",
      };
    case "discord":
      return {
        text:
          "In a Discord channel: ⚙ Edit Channel → Integrations → Webhooks → New Webhook → name & avatar → Copy Webhook URL.",
        learnHref:
          "https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks",
        learnLabel: "Discord docs",
      };
  }
}

// Small inline help block — friendlier than a tooltip and unmissable for new
// users. The optional learn-more link should point at our own docs or the
// upstream provider's; whichever explains it faster.
function HelpHint({
  text,
  learnHref,
  learnLabel,
}: {
  text: string;
  learnHref?: string;
  learnLabel?: string;
}) {
  return (
    <p className="text-[11px] leading-relaxed text-fg-subtle">
      {text}
      {learnHref && (
        <>
          {" "}
          <a
            href={learnHref}
            target={learnHref.startsWith("http") ? "_blank" : undefined}
            rel={learnHref.startsWith("http") ? "noreferrer" : undefined}
            className="text-signal hover:underline"
          >
            {learnLabel ?? "Learn more"} →
          </a>
        </>
      )}
    </p>
  );
}
