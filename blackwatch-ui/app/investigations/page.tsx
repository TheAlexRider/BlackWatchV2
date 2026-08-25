import { fetchInvestigations } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { InvestigationList } from "./InvestigationList";
import { InvestigationStartForm } from "./InvestigationStartForm";

type SearchParams = { ip?: string };

export default async function InvestigationsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const [params, { investigations }] = await Promise.all([
    searchParams,
    fetchInvestigations(),
  ]);
  return (
    <>
      <PageHeader
        title="Investigations"
        subtitle="Track observables, preserve evidence, and connect related BlackWatch events."
        actions={<InvestigationStartForm initialIp={params.ip} />}
      />
      {investigations.length === 0 ? (
        <DataPanel>
          <EmptyState>
            <p>No investigations yet.</p>
            <p className="mt-2 text-fg-subtle">
              Right-click an IP anywhere in BlackWatch and choose <strong className="text-fg">Add to investigation</strong>.
            </p>
          </EmptyState>
        </DataPanel>
      ) : (
        <InvestigationList investigations={investigations} />
      )}
    </>
  );
}
