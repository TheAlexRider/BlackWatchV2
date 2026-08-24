import Link from "next/link";
import clsx from "clsx";
import { ArrowLeft, Cloud, Server, Database, ShieldCheck, ShieldAlert } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { ConnectorForm } from "@/components/domain/connectors/ConnectorForm";
import type { ConnectorType } from "@/lib/types";

type SearchParams = { type?: string };

const CONNECTOR_OPTIONS: Array<{
  type: ConnectorType;
  title: string;
  blurb: string;
  icon: typeof Cloud;
}> = [
  {
    type: "aws_cloudtrail_sqs",
    title: "SQS connector",
    blurb: "CloudTrail / EC2 agents / OpenVPN agent — events posted to an SQS queue",
    icon: Cloud,
  },
  {
    type: "aws_ecs_health",
    title: "ECS health",
    blurb: "Reads AWS-side healthStatus per VPC. No in-VPC presence required.",
    icon: Server,
  },
  {
    type: "aws_s3_drift",
    title: "S3 drift",
    blurb: "Periodic posture scan of every bucket — ACL, BPA, encryption, versioning, logging",
    icon: Database,
  },
  {
    type: "aws_s3_access_logs",
    title: "S3 access-log reader",
    blurb: "Reads a central S3 server-access-log bucket and emits object access events",
    icon: Database,
  },
  {
    type: "aws_posture_drift",
    title: "AWS posture drift",
    blurb: "Current-state checks across SG, EBS, EC2, IAM, KMS, CloudTrail. Phase 2a + 2b.",
    icon: ShieldCheck,
  },
  {
    type: "cert_probe",
    title: "TLS cert expiry",
    blurb: "Periodic probe of HTTPS endpoints to catch certs before they expire.",
    icon: ShieldAlert,
  },
];

export default async function NewConnectorPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { type } = await searchParams;
  const chosen = (type as ConnectorType) ?? null;

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
        title={chosen ? labelFor(chosen) : "Add connector"}
        subtitle={chosen ? "Configure, save, test, then enable." : "Pick a connector type."}
      />

      {!chosen ? (
        <TypePicker />
      ) : (
        <DataPanel className="overflow-hidden">
          <ConnectorForm type={chosen} />
        </DataPanel>
      )}
    </>
  );
}

function TypePicker() {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {CONNECTOR_OPTIONS.map((opt) => (
        <Link
          key={opt.type}
          href={`/connectors/new?type=${opt.type}`}
          className={clsx(
            "group flex flex-col gap-2 border border-line-soft bg-surface-1 px-4 py-4",
            "transition-colors hover:border-line hover:bg-surface-2",
          )}
        >
          <div className="flex items-center gap-2">
            <opt.icon
              size={14}
              strokeWidth={1.5}
              className="text-fg-subtle group-hover:text-signal"
            />
            <span className="text-sm text-fg">{opt.title}</span>
            <code className="ml-auto font-mono text-[10px] text-fg-subtle">
              {opt.type}
            </code>
          </div>
          <p className="text-xs text-fg-muted">{opt.blurb}</p>
        </Link>
      ))}
    </div>
  );
}

function labelFor(type: ConnectorType): string {
  switch (type) {
    case "aws_cloudtrail_sqs":
      return "Add SQS connector";
    case "aws_ecs_health":
      return "Add ECS health connector";
    case "aws_s3_drift":
      return "Add S3 drift connector";
    case "aws_s3_access_logs":
      return "Add S3 access-log reader";
    case "aws_posture_drift":
      return "Add AWS posture drift connector";
    case "cert_probe":
      return "Add TLS cert expiry probe";
  }
}
