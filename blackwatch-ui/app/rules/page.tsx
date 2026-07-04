import { fetchRules } from "@/lib/api";
import type { Rule } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { SeverityBadge } from "@/components/domain/SeverityBadge";
import { toggleRuleAction, muteAction, unmuteAction } from "./actions";

type SearchParams = { msg?: string };

export default async function RulesPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { msg } = await searchParams;
  const { count, rules, muted } = await fetchRules();

  return (
    <>
      <PageHeader
        title="Rules"
        subtitle={`${count} loaded · toggle below, or edit YAML in rules/ and restart`}
      />

      {msg && <MessageBar message={msg} />}

      <section className="space-y-2">
        <SectionLabel>rules</SectionLabel>
        <DataPanel className="overflow-hidden">
          <RulesTable rules={rules} />
        </DataPanel>
      </section>

      <section className="mt-6 space-y-2">
        <SectionLabel>muted event types · dropped at ingest</SectionLabel>
        <DataPanel className="p-4">
          <p className="text-xs text-fg-muted">
            Muted actions are discarded before storage — use this for
            high-volume, low-value events (e.g.{" "}
            <code className="text-fg">auth.assume_role</code>). Note: this stops
            them cluttering BlackWatch but does <strong>not</strong> reduce AWS
            cost — to cut cost, also drop the event from the EventBridge pattern
            in <code className="text-fg">deploy/iam/</code>.
          </p>

          {muted.length > 0 ? (
            <MutedTable muted={muted} />
          ) : (
            <p className="mt-4 text-sm text-fg-muted">Nothing muted.</p>
          )}

          <form
            action={muteAction}
            className="mt-4 flex items-center gap-2 border-t border-line-soft pt-4"
          >
            <Input
              name="action"
              placeholder="e.g. auth.assume_role"
              required
              className="w-72"
            />
            <Button type="submit" variant="primary" size="sm">
              Mute
            </Button>
          </form>
        </DataPanel>
      </section>
    </>
  );
}

// --- table renderers ------------------------------------------------------

function RulesTable({ rules }: { rules: Rule[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
          <th className="w-56 px-4 py-2 text-left font-normal">ID</th>
          <th className="px-4 py-2 text-left font-normal">Title</th>
          <th className="w-56 px-4 py-2 text-left font-normal">Action</th>
          <th className="w-28 px-4 py-2 text-left font-normal">Severity</th>
          <th className="w-24 px-4 py-2 text-left font-normal">State</th>
          <th className="w-40 px-4 py-2 text-left font-normal">Tags</th>
          <th className="w-28 px-4 py-2 text-right font-normal" />
        </tr>
      </thead>
      <tbody>
        {rules.map((r) => (
          <tr
            key={r.id}
            className="border-b border-line-soft last:border-0 hover:bg-surface-2"
          >
            <td className="truncate px-4 py-2 font-mono text-xs text-fg">{r.id}</td>
            <td className="truncate px-4 py-2 text-sm text-fg-muted">{r.title}</td>
            <td className="truncate px-4 py-2 font-mono text-xs text-fg-muted">
              {r.action}
            </td>
            <td className="px-4 py-2">
              {r.severity ? (
                <SeverityBadge severity={r.severity} />
              ) : (
                <span className="text-fg-disabled">—</span>
              )}
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
      </tbody>
    </Table>
  );
}

function MutedTable({ muted }: { muted: string[] }) {
  return (
    <div className="mt-4 border border-line-soft">
      <Table>
        <thead>
          <tr className="border-b border-line-soft text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
            <th className="px-4 py-2 text-left font-normal">Action</th>
            <th className="w-32 px-4 py-2 text-right font-normal" />
          </tr>
        </thead>
        <tbody>
          {muted.map((m) => (
            <tr key={m} className="border-b border-line-soft last:border-0">
              <td className="px-4 py-2 font-mono text-xs text-fg">{m}</td>
              <td className="px-4 py-2 text-right">
                <form action={unmuteAction} className="inline">
                  <input type="hidden" name="action" value={m} />
                  <Button type="submit" size="sm" variant="ghost">
                    Unmute
                  </Button>
                </form>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

// --- presentational pieces ------------------------------------------------

function EnabledPill({ enabled }: { enabled: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        aria-hidden
        className={`h-1.5 w-1.5 rounded-full ${
          enabled ? "bg-sev-resolved" : "bg-fg-subtle"
        }`}
      />
      <span className={enabled ? "text-fg-muted" : "text-fg-subtle"}>
        {enabled ? "enabled" : "disabled"}
      </span>
    </span>
  );
}

function MessageBar({ message }: { message: string }) {
  return (
    <div className="mb-4 border-l-2 border-signal bg-surface-1 px-3 py-2 text-xs text-fg-muted">
      <span className="text-signal">·</span> {message}
    </div>
  );
}
