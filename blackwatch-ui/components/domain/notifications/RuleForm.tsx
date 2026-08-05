import Link from "next/link";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { FormRow } from "@/components/ui/FormRow";
import { Checkbox } from "@/components/ui/Checkbox";
import type { NotificationChannel, NotificationRule } from "@/lib/types";
import { saveRuleAction } from "@/app/notifications/actions";

// Common BlackWatch categories + modules. Used as chip pickers in the wizard.
// Hardcoded because they're stable; operators with custom values use the
// "advanced JSON" disclosure at the bottom.
const COMMON_CATEGORIES = [
  "iam",
  "posture",
  "host",
  "vpn",
  "finding",
  "network",
  "ecs",
  "s3",
  "service",
];

const COMMON_MODULES = [
  "aws.cloudtrail",
  "ec2.host",
  "vpn.openvpn",
  "aws.s3",
  "aws.posture",
  "aws.ecs",
];

// The wizard captures a Condition tree in simplified form. When editing an
// existing rule, we try to reverse-engineer the simple form from the saved
// match — for rules built via the wizard this works. For rules with bespoke
// matches, we fall back to the advanced JSON view automatically.
type Initial = {
  name: string;
  severity_at_least: "any" | "critical" | "high" | "medium" | "low";
  categories: string[];
  modules: string[];
  action_contains: string;
  advanced_yaml: string;
  uses_advanced: boolean;
};

// Preset / preset-link prefill — values come from URL query params on
// /notifications/rules/new and override the empty defaults. Existing-rule
// editing takes precedence over prefill.
export type RulePrefill = {
  name?: string;
  severity_at_least?: string;
  categories?: string[];
  modules?: string[];
  action_contains?: string;
};

const VALID_SEVS = ["any", "critical", "high", "medium", "low"] as const;

function inferInitial(rule?: NotificationRule, prefill?: RulePrefill): Initial {
  const empty: Initial = {
    name: prefill?.name ?? "",
    severity_at_least:
      prefill?.severity_at_least &&
      (VALID_SEVS as readonly string[]).includes(prefill.severity_at_least)
        ? (prefill.severity_at_least as Initial["severity_at_least"])
        : "any",
    categories: prefill?.categories ?? [],
    modules: prefill?.modules ?? [],
    action_contains: prefill?.action_contains ?? "",
    advanced_yaml: "",
    uses_advanced: false,
  };
  if (!rule) return empty;
  const m = rule.match as Record<string, unknown>;
  if (!m) return empty;

  // Reads BOTH condition shapes:
  //   - shortcut: {field: X, in: [...]}          // legacy form some rules use
  //   - explicit: {field: X, op: "in", value: [...]}   // canonical form
  // (Same for icontains / value shape.) New rules always save in the explicit
  // form; legacy rules still round-trip correctly until the user re-saves.
  function readPart(p: unknown): boolean {
    if (typeof p !== "object" || p === null) return false;
    const part = p as Record<string, unknown>;
    const inList: string[] | null =
      Array.isArray(part.in)
        ? (part.in as string[])
        : part.op === "in" && Array.isArray(part.value)
        ? (part.value as string[])
        : null;
    const iContainsValue: string | null =
      typeof part.icontains === "string"
        ? (part.icontains as string)
        : part.op === "icontains" && typeof part.value === "string"
        ? (part.value as string)
        : null;

    if (part.field === "severity" && inList) {
      const sevs = inList.slice().sort();
      const map: Record<string, Initial["severity_at_least"]> = {
        critical: "critical",
        "critical,high": "high",
        "critical,high,medium": "medium",
        "critical,high,low,medium": "low",
      };
      const key = sevs.join(",");
      empty.severity_at_least = map[key] ?? "any";
      return true;
    }
    if (part.field === "category" && inList) {
      empty.categories = inList.slice();
      return true;
    }
    if (part.field === "source.module" && inList) {
      empty.modules = inList.slice();
      return true;
    }
    if (part.field === "action" && iContainsValue !== null) {
      empty.action_contains = iContainsValue;
      return true;
    }
    return false;
  }

  let parsed = false;
  if (Array.isArray(m.all)) {
    parsed = (m.all as unknown[]).every(readPart);
  } else if (Object.keys(m).length > 0) {
    parsed = readPart(m);
  } else {
    parsed = true; // empty match-all
  }

  if (!parsed) {
    empty.uses_advanced = true;
    try {
      empty.advanced_yaml = JSON.stringify(m, null, 2);
    } catch {
      empty.advanced_yaml = "";
    }
  }
  return empty;
}

export function RuleForm({
  existing,
  channels,
  prefill,
}: {
  existing?: NotificationRule;
  channels: NotificationChannel[];
  prefill?: RulePrefill;
}) {
  const init = inferInitial(existing, prefill);
  const isEdit = !!existing;

  return (
    <form action={saveRuleAction}>
      <input type="hidden" name="id" value={existing?.id ?? ""} />

      <FormRow label="Name">
        <Input
          name="name"
          required
          defaultValue={existing?.name ?? init.name}
          placeholder="critical to slack"
        />
      </FormRow>

      <FormRow label="Enabled">
        <Checkbox
          name="enabled"
          defaultChecked={isEdit ? existing?.enabled : true}
          label="send when matched"
        />
      </FormRow>

      {/* The conversational simple section */}
      {!init.uses_advanced && (
        <>
          <FormRow label="Severity" hint="at least">
            <NativeSelect
              name="severity_at_least"
              defaultValue={init.severity_at_least}
              className="w-48"
            >
              <option value="any">any severity</option>
              <option value="critical">critical only</option>
              <option value="high">high or above</option>
              <option value="medium">medium or above</option>
              <option value="low">low or above</option>
            </NativeSelect>
          </FormRow>

          <FormRow label="Categories" hint="any of">
            <ChipPicker
              name="category"
              options={COMMON_CATEGORIES}
              selected={init.categories}
            />
          </FormRow>

          <FormRow label="Modules" hint="any of">
            <ChipPicker
              name="module"
              options={COMMON_MODULES}
              selected={init.modules}
            />
          </FormRow>

          <FormRow label="Action contains" hint="case-insensitive substring">
            <Input
              name="action_contains"
              mono
              defaultValue={init.action_contains}
              placeholder="e.g. iam.policy"
              className="w-72"
            />
          </FormRow>
        </>
      )}

      {/* Channels */}
      <FormRow label="Send to">
        {channels.length === 0 ? (
          <p className="text-xs text-fg-muted">
            No channels defined yet. Add one before saving this rule.
          </p>
        ) : (
          <ChannelChipPicker
            channels={channels}
            selected={existing?.channels ?? []}
          />
        )}
      </FormRow>

      <FormRow label="Throttle" hint="seconds · 0 = use channel default">
        <Input
          name="throttle_seconds"
          type="number"
          mono
          className="w-24"
          defaultValue={String(existing?.throttle_seconds ?? 0)}
        />
      </FormRow>

      <FormRow label="Message" hint="Jinja · overrides channel default when set">
        <textarea
          name="message_template"
          rows={8}
          defaultValue={existing?.message_template ?? ""}
          placeholder={"*Something happened on {{ event.extra.display_name | default(event.target.id) }}*\nSeverity: {{ event.severity }}\nCheck: ..."}
          className="w-full border border-line bg-surface-1 px-2.5 py-2 font-mono text-xs text-fg placeholder:text-fg-disabled focus-visible:border-signal focus-visible:outline-none"
        />
      </FormRow>

      {/* Advanced JSON override */}
      <details
        className="border-t border-line-soft px-4 py-3"
        open={init.uses_advanced}
      >
        <summary className="cursor-pointer text-xs uppercase tracking-[0.08em] text-fg-subtle hover:text-fg">
          advanced · custom JSON criteria (overrides the simple form above)
        </summary>
        <div className="mt-3 space-y-2">
          <textarea
            name="advanced_yaml"
            rows={6}
            defaultValue={init.advanced_yaml}
            placeholder={`{\n  "all": [\n    {"field": "severity", "in": ["critical"]},\n    {"field": "actor.principal", "regex": "ops-.*"}\n  ]\n}`}
            className="w-full border border-line bg-surface-1 px-2.5 py-2 font-mono text-xs text-fg placeholder:text-fg-disabled focus-visible:border-signal focus-visible:outline-none"
          />
          <p className="text-[11px] text-fg-subtle">
            Same shape as detection rules · operators: equals, not_equals, in,
            contains, icontains, regex, cidr, exists, startswith, endswith ·
            nest with all / any / not
          </p>
        </div>
      </details>

      <div className="flex items-center gap-3 border-t border-line-soft bg-surface-1 px-4 py-3">
        <Button type="submit" variant="primary" size="sm">
          {isEdit ? "Save changes" : "Add rule"}
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

// =========================================================================
// chip pickers
// =========================================================================

function ChipPicker({
  name,
  options,
  selected,
}: {
  name: string;
  options: string[];
  selected: string[];
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((opt) => (
        <Chip key={opt} name={name} value={opt} defaultChecked={selected.includes(opt)}>
          {opt}
        </Chip>
      ))}
    </div>
  );
}

function ChannelChipPicker({
  channels,
  selected,
}: {
  channels: NotificationChannel[];
  selected: string[];
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {channels.map((c) => (
        <Chip
          key={c.id}
          name="channel"
          value={c.name}
          defaultChecked={selected.includes(c.name)}
          subtle={!c.enabled}
        >
          <span className="font-mono text-[10px] text-fg-subtle">{c.type}</span>
          <span className="ml-1.5">{c.name}</span>
        </Chip>
      ))}
    </div>
  );
}

function Chip({
  name,
  value,
  defaultChecked,
  subtle,
  children,
}: {
  name: string;
  value: string;
  defaultChecked: boolean;
  subtle?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label
      className={`inline-flex cursor-pointer items-center gap-1.5 border border-line bg-surface-1 px-2 py-1 text-xs text-fg-muted transition-colors hover:bg-surface-2 has-[:checked]:border-signal has-[:checked]:bg-signal/10 has-[:checked]:text-fg ${
        subtle ? "opacity-60" : ""
      }`}
    >
      <input
        type="checkbox"
        name={name}
        value={value}
        defaultChecked={defaultChecked}
        className="sr-only"
      />
      {children}
    </label>
  );
}

