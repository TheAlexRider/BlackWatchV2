import { notFound } from "next/navigation";

import { fetchConnector } from "@/lib/api";
import type { ConnectorType } from "@/lib/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { ConnectorForm } from "@/components/domain/connectors/ConnectorForm";

const KNOWN: ConnectorType[] = [
  "aws_cloudtrail_sqs",
  "aws_ecs_health",
  "aws_s3_drift",
  "aws_s3_access_logs",
  "aws_posture_drift",
  "cert_probe",
];

export default async function EditConnectorPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const connector = await fetchConnector(id);
  if (!connector) notFound();

  // Only render a form for known types; unknown types just show the raw config.
  const knownType = KNOWN.includes(connector.type as ConnectorType)
    ? (connector.type as ConnectorType)
    : null;

  return (
    <>
      <PageHeader
        title={`Edit · ${connector.name}`}
        subtitle={connector.id}
        breadcrumbs={[{ label: "Connectors", href: "/connectors" }, { label: connector.name }]}
      />

      <DataPanel className="overflow-hidden">
        {knownType ? (
          <ConnectorForm type={knownType} existing={connector} />
        ) : (
          <div className="p-4 text-xs text-fg-muted">
            Unknown connector type:{" "}
            <code className="text-fg">{connector.type}</code>. No edit form
            available. Raw config:
            <pre className="mt-2 overflow-auto bg-surface-2 p-3 text-[11px] text-fg-muted">
              {JSON.stringify(connector.config, null, 2)}
            </pre>
          </div>
        )}
      </DataPanel>
    </>
  );
}
