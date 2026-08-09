import Link from "next/link";
import clsx from "clsx";

import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { Table, TableEmpty } from "@/components/ui/Table";
import { UebaAnomalyRow } from "@/components/domain/UebaAnomalyRow";
import { BaselineTable } from "@/components/domain/BaselineTable";
import { fetchUebaAnomalies, fetchUebaBaselines } from "@/lib/api";

type SearchParams = {
  tab?: string;
  principal_type?: string;
  principal_id?: string;
  dimension?: string;
};

export default async function UebaPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const tab = params.tab === "baselines" ? "baselines" : "anomalies";

  const [anomalies, baselines] = await Promise.all([
    tab === "anomalies"
      ? fetchUebaAnomalies({ limit: 200 }).catch(() => ({
          count: 0,
          anomalies: [],
        }))
      : Promise.resolve({ count: 0, anomalies: [] }),
    tab === "baselines"
      ? fetchUebaBaselines({
          principal_type: params.principal_type,
          principal_id: params.principal_id,
          dimension: params.dimension,
          limit: 500,
        }).catch(() => ({ count: 0, baselines: [] }))
      : Promise.resolve({ count: 0, baselines: [] }),
  ]);

  return (
    <>
      <PageHeader
        title="UEBA"
        subtitle="Per-principal baselines and first-seen anomalies."
      />

      <div className="mb-4 flex gap-1 border-b border-line-soft text-sm">
        <TabLink
          href="/ueba?tab=anomalies"
          active={tab === "anomalies"}
          label="Recent anomalies"
        />
        <TabLink
          href="/ueba?tab=baselines"
          active={tab === "baselines"}
          label="Baseline explorer"
        />
      </div>

      {tab === "anomalies" ? (
        <DataPanel className="overflow-hidden">
          {anomalies.anomalies.length === 0 ? (
            <div className="px-6 py-10 text-center text-sm text-fg-muted">
              No first-seen anomalies yet. Principals need to be past the
              warm-up window (default 7 days) for anomalies to fire.
            </div>
          ) : (
            <Table tableId="ueba-anomalies">
              <thead>
                <tr>
                  <th style={{ width: 170 }}>Time</th>
                  <th style={{ width: 260 }}>Action</th>
                  <th style={{ width: 220 }}>Principal</th>
                  <th style={{ width: 150 }}>Dimension</th>
                  <th style={{ width: 220 }}>New value</th>
                  <th style={{ width: 100 }}>Trigger</th>
                </tr>
              </thead>
              <tbody>
                {anomalies.anomalies.map((e) => (
                  <UebaAnomalyRow key={e.event_id} event={e} />
                ))}
              </tbody>
            </Table>
          )}
        </DataPanel>
      ) : (
        <>
          <form
            method="get"
            className="mb-4 flex flex-wrap items-end gap-3 text-sm"
          >
            <input type="hidden" name="tab" value="baselines" />
            <label className="flex flex-col gap-1">
              <SectionLabel>principal type</SectionLabel>
              <input
                type="text"
                name="principal_type"
                defaultValue={params.principal_type ?? ""}
                placeholder="user, role, service"
                className="w-40 rounded border border-line-soft bg-canvas px-2 py-1"
              />
            </label>
            <label className="flex flex-col gap-1">
              <SectionLabel>principal id</SectionLabel>
              <input
                type="text"
                name="principal_id"
                defaultValue={params.principal_id ?? ""}
                placeholder="alice"
                className="w-56 rounded border border-line-soft bg-canvas px-2 py-1"
              />
            </label>
            <label className="flex flex-col gap-1">
              <SectionLabel>dimension</SectionLabel>
              <input
                type="text"
                name="dimension"
                defaultValue={params.dimension ?? ""}
                placeholder="source_ip"
                className="w-44 rounded border border-line-soft bg-canvas px-2 py-1"
              />
            </label>
            <button
              type="submit"
              className="h-8 rounded border border-line-soft px-3 text-fg hover:bg-canvas-raised"
            >
              Filter
            </button>
          </form>
          <DataPanel className="overflow-hidden">
            <BaselineTable rows={baselines.baselines} />
          </DataPanel>
        </>
      )}
    </>
  );
}

function TabLink({
  href,
  label,
  active,
}: {
  href: string;
  label: string;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      className={clsx(
        "-mb-px border-b-2 px-3 py-2 transition-colors",
        active
          ? "border-signal text-fg"
          : "border-transparent text-fg-subtle hover:text-fg",
      )}
    >
      {label}
    </Link>
  );
}
