import { fetchRules } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { Table } from "@/components/ui/Table";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { muteAction, unmuteAction } from "./actions";
import { RulesTable } from "./RulesTable";

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
        subtitle={`${count} loaded · toggle + set severity below, or edit YAML in rules/ and restart`}
      />

      {msg && <MessageBar message={msg} />}

      <section className="space-y-2">
        <SectionLabel>rules</SectionLabel>
        <DataPanel className="overflow-x-auto">
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

function MessageBar({ message }: { message: string }) {
  return (
    <div className="mb-4 border-l-2 border-signal bg-surface-1 px-3 py-2 text-xs text-fg-muted">
      <span className="text-signal">·</span> {message}
    </div>
  );
}
