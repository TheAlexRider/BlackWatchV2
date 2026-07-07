"use client";

import { useMemo, useState } from "react";
import clsx from "clsx";
import type { Rule } from "@/lib/types";
import { Table } from "@/components/ui/Table";
import { Button } from "@/components/ui/Button";
import { SeverityBadge } from "@/components/domain/SeverityBadge";
import { toggleRuleAction, setSeverityAction } from "./actions";

const SEVERITY_OPTIONS = [
  { value: "critical", label: "critical" },
  { value: "high", label: "high" },
  { value: "medium", label: "medium" },
  { value: "low", label: "low" },
  { value: "informational", label: "informational" },
];

/**
 * Client-side filter over the rules list plus inline severity + enable
 * controls. Filter matches across id / title / matched action strings /
 * tags, so an operator hunting for `host.auth.ssh.password.success` (an
 * event action) or `host` (a tag) finds the rule instantly.
 */
export function RulesTable({ rules }: { rules: Rule[] }) {
  const [q, setQ] = useState("");

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return rules;
    return rules.filter((r) => {
      const hay = [
        r.id,
        r.title,
        r.description ?? "",
        (r.matched_actions ?? []).join(" "),
        (r.tags ?? []).join(" "),
        r.severity ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(needle);
    });
  }, [q, rules]);

  return (
    <div>
      <div className="flex items-center gap-2 border-b border-line-soft bg-surface-1 px-3 py-2">
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter by id, title, event action, tag…"
          className="min-w-0 flex-1 rounded border border-line-soft bg-surface-1 px-3 py-1.5 text-xs text-fg placeholder:text-fg-disabled focus:border-sig-teal focus:outline-none"
        />
        <span className="text-[11px] text-fg-subtle">
          <span className="font-mono text-fg-muted">{filtered.length}</span>
          {q && (
            <>
              {" "}/ <span className="font-mono">{rules.length}</span>
            </>
          )}
        </span>
      </div>
      <Table>
        <thead>
          <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            <th className="w-56 px-4 py-2 text-left font-normal">ID</th>
            <th className="w-72 px-4 py-2 text-left font-normal">Title</th>
            <th className="px-4 py-2 text-left font-normal">Event action(s)</th>
            <th className="w-44 px-4 py-2 text-left font-normal">Severity</th>
            <th className="w-24 px-4 py-2 text-left font-normal">State</th>
            <th className="w-40 px-4 py-2 text-left font-normal">Tags</th>
            <th className="w-28 px-4 py-2 text-right font-normal" />
          </tr>
        </thead>
        <tbody>
          {filtered.map((r) => (
            <tr
              key={r.id}
              className="border-b border-line-soft last:border-0 hover:bg-surface-2"
            >
              <td className="truncate px-4 py-2 font-mono text-xs text-fg">
                {r.id}
              </td>
              <td className="truncate px-4 py-2 text-sm text-fg-muted">
                {r.title}
              </td>
              <td className="px-4 py-2 font-mono text-[11px] text-fg-muted">
                {r.matched_actions && r.matched_actions.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {r.matched_actions.map((a) => (
                      <code
                        key={a}
                        className="rounded bg-surface-2 px-1.5 py-0.5 text-fg"
                      >
                        {a}
                      </code>
                    ))}
                  </div>
                ) : (
                  <span className="text-fg-disabled">
                    (matches on non-action fields)
                  </span>
                )}
              </td>
              <td className="px-4 py-2">
                <SeverityPicker
                  ruleId={r.id}
                  current={typeof r.severity === "string" ? r.severity : null}
                />
              </td>
              <td className="px-4 py-2">
                <EnabledPill enabled={r.enabled} />
              </td>
              <td className="truncate px-4 py-2 font-mono text-[11px] text-fg-subtle">
                {r.tags && r.tags.length > 0 ? r.tags.join(", ") : "—"}
              </td>
              <td className="px-4 py-2 text-right">
                <form action={toggleRuleAction} className="inline">
                  <input type="hidden" name="rule_id" value={r.id} />
                  <input
                    type="hidden"
                    name="enabled"
                    value={r.enabled ? "off" : "on"}
                  />
                  <Button
                    type="submit"
                    size="sm"
                    variant={r.enabled ? "ghost" : "secondary"}
                  >
                    {r.enabled ? "Disable" : "Enable"}
                  </Button>
                </form>
              </td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={7} className="px-4 py-8 text-center text-sm text-fg-muted">
                No rules match &ldquo;{q}&rdquo;.
              </td>
            </tr>
          )}
        </tbody>
      </Table>
    </div>
  );
}

/**
 * Inline severity <select> that submits via a server action on change,
 * so the operator doesn't have to hit a Save button per row. The current
 * severity is what the engine holds after any override is applied — we
 * don't try to display "overridden" vs "YAML default" because the engine
 * doesn't currently expose the original — but picking any value writes
 * an override; picking the (default) option clears it.
 */
function SeverityPicker({
  ruleId,
  current,
}: {
  ruleId: string;
  current: string | null;
}) {
  return (
    <form action={setSeverityAction} className="inline-flex items-center gap-1">
      <input type="hidden" name="rule_id" value={ruleId} />
      <span className="pointer-events-none">
        {current ? <SeverityBadge severity={current} /> : null}
      </span>
      <select
        name="severity"
        defaultValue={current ?? "default"}
        onChange={(e) => e.currentTarget.form?.requestSubmit()}
        className={clsx(
          "cursor-pointer rounded border border-line-soft bg-surface-1 px-1.5 py-1 text-[11px] text-fg",
          "focus:border-sig-teal focus:outline-none",
        )}
        aria-label={`Set severity for ${ruleId}`}
      >
        <option value="default">— clear override —</option>
        {SEVERITY_OPTIONS.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>
    </form>
  );
}

function EnabledPill({ enabled }: { enabled: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        aria-hidden
        className={clsx(
          "h-1.5 w-1.5 rounded-full",
          enabled ? "bg-sev-resolved" : "bg-fg-subtle",
        )}
      />
      <span className={enabled ? "text-fg-muted" : "text-fg-subtle"}>
        {enabled ? "enabled" : "disabled"}
      </span>
    </span>
  );
}
