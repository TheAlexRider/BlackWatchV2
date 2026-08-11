import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";

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
      <div className="mb-4">
        <Link
          href="/connectors"
          className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft size={12} /> back to connectors
        </Link>
      </div>

      <PageHeader
        title={`Edit · ${connector.name}`}
        subtitle={connector.id}
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
