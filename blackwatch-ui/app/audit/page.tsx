import { apiFetch } from "@/lib/server-fetch";
import { AuditRow, type AuditEntry } from "@/components/domain/AuditRow";
import { Table } from "@/components/ui/Table";

interface SearchParams {
  actor?: string;
  path?: string;
  since?: string;
  limit?: string;
}

async function loadAudit(sp: SearchParams): Promise<AuditEntry[]> {
  const qs = new URLSearchParams();
  if (sp.actor) qs.set("actor", sp.actor);
  if (sp.path) qs.set("path", sp.path);
  if (sp.since) qs.set("since", sp.since);
  qs.set("limit", sp.limit ?? "200");
  const res = await apiFetch(`/api/audit?${qs.toString()}`);
  if (res.status === 403) return [];
  if (!res.ok) throw new Error(`audit fetch failed: ${res.status}`);
  const j = (await res.json()) as { rows: AuditEntry[] };
  return j.rows ?? [];
}

export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const rows = await loadAudit(sp);

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-medium">Audit log</h1>
        <p className="text-sm text-fg-subtle">
          Append-only record of every mutation this BlackWatch instance received.
        </p>
      </header>

      <form className="flex flex-wrap gap-2 text-sm" action="/audit" method="get">
        <input
          type="text"
          name="actor"
          placeholder="actor"
          defaultValue={sp.actor ?? ""}
          className="rounded border border-line-soft bg-canvas px-2 py-1"
        />
        <input
          type="text"
          name="path"
          placeholder="path contains"
          defaultValue={sp.path ?? ""}
          className="rounded border border-line-soft bg-canvas px-2 py-1"
        />
        <input
          type="datetime-local"
          name="since"
          defaultValue={sp.since ?? ""}
          className="rounded border border-line-soft bg-canvas px-2 py-1"
        />
        <input
          type="number"
          name="limit"
          placeholder="limit"
          defaultValue={sp.limit ?? "200"}
          className="w-24 rounded border border-line-soft bg-canvas px-2 py-1"
        />
        <button
          type="submit"
          className="rounded border border-line-soft px-3 py-1 hover:border-signal"
        >
          Filter
        </button>
      </form>

      <div className="overflow-hidden rounded border border-line-soft">
        <Table tableId="audit-log" ariaLabel="Audit log">
          <thead className="bg-canvas-elev text-left text-xs text-fg-subtle">
            <tr>
              <th>Time</th>
              <th>Actor</th>
              <th>Role</th>
              <th>IP</th>
              <th>Method</th>
              <th>Path</th>
              <th>Status</th>
              <th>Body</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-fg-subtle">
                  No audit rows (or not authorized).
                </td>
              </tr>
            ) : (
              rows.map((r) => <AuditRow key={r.id} row={r} />)
            )}
          </tbody>
        </Table>
      </div>
    </div>
  );
}
