import Link from "next/link";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { FormRow } from "@/components/ui/FormRow";
import type {
  Connector,
  ConnectorType,
  CloudTrailSqsConfig,
  EcsHealthConfig,
  S3DriftConfig,
  PostureDriftConfig,
  CertProbeConfig,
  CertProbeTarget,
} from "@/lib/types";
import {
  saveCloudTrailSqsAction,
  saveEcsHealthAction,
  saveS3DriftAction,
  savePostureDriftAction,
  saveCertProbeAction,
} from "@/app/connectors/actions";

// Public API: render the right form for a given connector type. If `existing`
// is provided, the form is treated as edit (id hidden field) and the inputs
// are pre-populated.
export function ConnectorForm({
  type,
  existing,
}: {
  type: ConnectorType;
  existing?: Connector;
}) {
  switch (type) {
    case "aws_cloudtrail_sqs":
      return <CloudTrailSqsForm existing={existing} />;
    case "aws_ecs_health":
      return <EcsHealthForm existing={existing} />;
    case "aws_s3_drift":
      return <S3DriftForm existing={existing} />;
    case "aws_posture_drift":
      return <PostureDriftForm existing={existing} />;
    case "cert_probe":
      return <CertProbeForm existing={existing} />;
  }
}

// --- shared form scaffolding ---------------------------------------------

function FormActions({
  isEdit,
  cancelHref = "/connectors",
}: {
  isEdit: boolean;
  cancelHref?: string;
}) {
  return (
    <div className="flex items-center gap-3 border-t border-line-soft bg-surface-1 px-4 py-3">
      <Button type="submit" variant="primary" size="sm">
        {isEdit ? "Save changes" : "Add connector"}
      </Button>
      <Link
        href={cancelHref}
        className="text-xs text-fg-muted transition-colors hover:text-fg"
      >
        cancel
      </Link>
    </div>
  );
}

function FormNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="border-t border-line-soft bg-surface-1 px-4 py-3 text-xs text-fg-muted">
      {children}
    </p>
  );
}

// =========================================================================
// 1. CloudTrail / SQS connector (CloudTrail + EC2 agents + VPN agents)
// =========================================================================

function CloudTrailSqsForm({ existing }: { existing?: Connector }) {
  const a = (existing?.config as CloudTrailSqsConfig) ?? {};
  return (
    <form action={saveCloudTrailSqsAction}>
      <input type="hidden" name="connector_id" value={existing?.id ?? ""} />
      <FormRow label="Name">
        <Input
          name="name"
          required
          defaultValue={existing?.name ?? ""}
          placeholder="aws iam events / ec2 agents"
        />
      </FormRow>
      <FormRow label="Target module">
        <NativeSelect
          name="target_module"
          defaultValue={a.target_module ?? "aws.cloudtrail"}
        >
          <option value="aws.cloudtrail">aws.cloudtrail (IAM / CloudTrail)</option>
          <option value="ec2.host">ec2.host (EC2 agents)</option>
          <option value="vpn.openvpn">vpn.openvpn (OpenVPN agent)</option>
        </NativeSelect>
      </FormRow>
      <FormRow label="SQS queue URL">
        <Input
          name="queue_url"
          required
          defaultValue={a.queue_url ?? ""}
          placeholder="https://sqs.us-west-1.amazonaws.com/123/blackwatch-..."
          mono
        />
      </FormRow>
      <FormRow label="AWS region">
        <Input
          name="aws_region"
          defaultValue={a.aws_region ?? "us-west-1"}
          className="w-48"
        />
      </FormRow>
      <FormRow label="AWS profile" hint="in mounted ~/.aws">
        <Input
          name="aws_profile"
          defaultValue={a.aws_profile ?? "blackwatch"}
          className="w-48"
        />
      </FormRow>
      <FormRow label="Poll interval" hint="seconds">
        <Input
          name="interval_seconds"
          type="number"
          defaultValue={String(a.interval_seconds ?? 60)}
          className="w-32"
          mono
        />
      </FormRow>
      <FormActions isEdit={!!existing} />
      <FormNote>
        Mount your AWS credentials read-only (
        <code className="text-fg">~/.aws</code>) into the container and put the
        profile name above. Creds are never stored by BlackWatch. The queue is
        filled by the EventBridge → Lambda forwarder (see{" "}
        <code className="text-fg">deploy/iam/</code>). After saving, click{" "}
        <strong className="text-fg">Test</strong>.
      </FormNote>
    </form>
  );
}

// =========================================================================
// 2. ECS health
// =========================================================================

function EcsHealthForm({ existing }: { existing?: Connector }) {
  const c = (existing?.config as EcsHealthConfig) ?? {};
  return (
    <form action={saveEcsHealthAction}>
      <input type="hidden" name="connector_id" value={existing?.id ?? ""} />
      <FormRow label="Name">
        <Input
          name="name"
          required
          defaultValue={existing?.name ?? ""}
          placeholder="ecs dev cluster"
        />
      </FormRow>
      <FormRow label="VPC label">
        <Input
          name="vpc"
          required
          defaultValue={c.vpc ?? ""}
          placeholder="dev / prod"
          className="w-48"
        />
      </FormRow>
      <FormRow label="AWS region">
        <Input
          name="aws_region"
          defaultValue={c.aws_region ?? "us-west-1"}
          className="w-48"
        />
      </FormRow>
      <FormRow label="AWS profile">
        <Input
          name="aws_profile"
          defaultValue={c.aws_profile ?? "blackwatch"}
          className="w-48"
        />
      </FormRow>
      <FormRow label="Poll interval" hint="seconds">
        <Input
          name="interval_seconds"
          type="number"
          defaultValue={String(c.interval_seconds ?? 60)}
          className="w-32"
          mono
        />
      </FormRow>
      <FormRow label="runningCount smoothing" hint="minutes">
        <Input
          name="running_smoothing_minutes"
          type="number"
          defaultValue={String(c.running_smoothing_minutes ?? 5)}
          className="w-32"
          mono
        />
      </FormRow>
      <FormActions isEdit={!!existing} />
      <FormNote>
        Iterates probe_targets in this VPC with tier{" "}
        <code className="text-fg">ecs_health</code> or{" "}
        <code className="text-fg">ecs_running</code> and reads AWS&apos;s view of
        each service&apos;s health. No in-VPC presence needed — control plane
        only.
      </FormNote>
    </form>
  );
}

// =========================================================================
// 3. S3 drift
// =========================================================================

function S3DriftForm({ existing }: { existing?: Connector }) {
  const c = (existing?.config as S3DriftConfig) ?? {};
  return (
    <form action={saveS3DriftAction}>
      <input type="hidden" name="connector_id" value={existing?.id ?? ""} />
      <FormRow label="Name">
        <Input
          name="name"
          required
          defaultValue={existing?.name ?? ""}
          placeholder="s3 inventory"
        />
      </FormRow>
      <FormRow label="AWS profile">
        <Input
          name="aws_profile"
          defaultValue={c.aws_profile ?? "blackwatch"}
          className="w-48"
        />
      </FormRow>
      <FormRow label="Scan interval" hint="seconds">
        <Input
          name="interval_seconds"
          type="number"
          defaultValue={String(c.interval_seconds ?? 3600)}
          className="w-32"
          mono
        />
      </FormRow>
      <FormActions isEdit={!!existing} />
      <FormNote>
        Lists every S3 bucket in the account (via{" "}
        <code className="text-fg">ListBuckets</code> — global) and reads its
        posture (ACL, policy, BPA, encryption, versioning, logging). Default
        interval is 1h — these settings don&apos;t change minute-by-minute.
        For the very first scan, you can also run{" "}
        <code className="text-fg">scripts/s3_bucket_inventory.py</code>{" "}
        directly from your local machine.
      </FormNote>
    </form>
  );
}

// =========================================================================
// 4. AWS posture drift (biggest one — 13 checkboxes + 2 thresholds)
// =========================================================================

function PostureDriftForm({ existing }: { existing?: Connector }) {
  const p = (existing?.config as PostureDriftConfig) ?? {};
  const isNew = !existing;
  // Phase 2a + Phase 2b defaults: all checks on for new connectors
  const checked = (val: boolean | undefined) => isNew || val === true;

  return (
    <form action={savePostureDriftAction}>
      <input type="hidden" name="connector_id" value={existing?.id ?? ""} />
      <FormRow label="Name">
        <Input
          name="name"
          required
          defaultValue={existing?.name ?? ""}
          placeholder="aws posture"
        />
      </FormRow>
      <FormRow label="AWS profile">
        <Input
          name="aws_profile"
          defaultValue={p.aws_profile ?? "blackwatch"}
          className="w-48"
        />
      </FormRow>
      <FormRow label="Regions" hint="comma-separated; blank = all enabled">
        <Input
          name="regions"
          defaultValue={(p.regions ?? []).join(",")}
          placeholder="us-west-1,us-east-1"
          mono
        />
      </FormRow>
      <FormRow label="Scan interval" hint="seconds">
        <Input
          name="interval_seconds"
          type="number"
          defaultValue={String(p.interval_seconds ?? 3600)}
          className="w-32"
          mono
        />
      </FormRow>
      <FormRow label="Phase 2a" hint="infrastructure posture">
        <CheckboxList>
          <Check name="check_sg_public_ingress" defaultChecked={checked(p.check_sg_public_ingress)}>
            Security groups: public ingress
          </Check>
          <Check name="check_ebs_encryption" defaultChecked={checked(p.check_ebs_encryption)}>
            EBS volumes: encryption
          </Check>
          <Check name="check_ebs_snapshot_public" defaultChecked={checked(p.check_ebs_snapshot_public)}>
            EBS snapshots: shared publicly
          </Check>
          <Check name="check_ec2_imdsv2" defaultChecked={checked(p.check_ec2_imdsv2)}>
            EC2 instances: IMDSv2 required
          </Check>
          <Check name="check_ami_public" defaultChecked={checked(p.check_ami_public)}>
            AMIs (yours): public
          </Check>
        </CheckboxList>
      </FormRow>
      <FormRow label="Phase 2b" hint="IAM hygiene (account-global)">
        <CheckboxList>
          <Check name="check_iam_user_no_mfa" defaultChecked={checked(p.check_iam_user_no_mfa)}>
            IAM users with console password but no MFA
          </Check>
          <Check name="check_iam_key_age" defaultChecked={checked(p.check_iam_key_age)}>
            Access keys older than rotation threshold
          </Check>
          <Check name="check_iam_key_unused" defaultChecked={checked(p.check_iam_key_unused)}>
            Access keys not used recently / never used
          </Check>
          <Check name="check_iam_role_wildcard_trust" defaultChecked={checked(p.check_iam_role_wildcard_trust)}>
            Roles assumable by Principal=* (no Condition)
          </Check>
        </CheckboxList>
      </FormRow>
      <FormRow label="IAM thresholds" hint="days">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2 text-xs">
          <label className="flex items-center gap-2">
            <span className="text-fg-muted">Key rotation threshold:</span>
            <Input
              name="iam_key_max_age_days"
              type="number"
              defaultValue={String(p.iam_key_max_age_days ?? 90)}
              className="w-24"
              mono
            />
          </label>
          <label className="flex items-center gap-2">
            <span className="text-fg-muted">Key unused threshold:</span>
            <Input
              name="iam_key_unused_threshold_days"
              type="number"
              defaultValue={String(p.iam_key_unused_threshold_days ?? 90)}
              className="w-24"
              mono
            />
          </label>
        </div>
      </FormRow>
      <FormRow label="Phase 2b" hint="KMS & audit">
        <CheckboxList>
          <Check name="check_kms_rotation" defaultChecked={checked(p.check_kms_rotation)}>
            KMS keys: rotation enabled (CMKs only)
          </Check>
          <Check name="check_kms_policy_wildcard" defaultChecked={checked(p.check_kms_policy_wildcard)}>
            KMS keys: wildcard principal in key policy
          </Check>
          <Check name="check_cloudtrail_validation" defaultChecked={checked(p.check_cloudtrail_validation)}>
            CloudTrail: multi-region enabled + log validation on
          </Check>
        </CheckboxList>
      </FormRow>
      <FormRow label="Phase 2c" hint="RDS posture + inventory">
        <CheckboxList>
          <Check name="check_rds" defaultChecked={checked(p.check_rds)}>
            RDS: per-instance posture (public, encryption, backups, deletion protection, IAM auth) + emit inventory events for /rds
          </Check>
        </CheckboxList>
      </FormRow>
      <FormActions isEdit={!!existing} />
      <FormNote>
        Scans current state of AWS resources for posture problems. Findings
        appear at{" "}
        <Link href="/aws-posture" className="text-signal hover:underline">
          /aws-posture
        </Link>
        . CloudTrail rules in <code className="text-fg">aws_posture.yaml</code>{" "}
        already fire on change events; this connector catches the &quot;already
        bad before BW existed&quot; case.
      </FormNote>
    </form>
  );
}

// =========================================================================
// 5. TLS cert expiry probe — list of host:port endpoints
// =========================================================================

function targetsToText(targets: CertProbeTarget[] | undefined): string {
  if (!targets || targets.length === 0) return "";
  return targets
    .map((t) => {
      const base = `${t.name},${t.host},${t.port}`;
      return t.sni ? `${base},${t.sni}` : base;
    })
    .join("\n");
}

function CertProbeForm({ existing }: { existing?: Connector }) {
  const cfg = (existing?.config as CertProbeConfig) ?? {};
  const initialTargets = targetsToText(cfg.targets);
  return (
    <form action={saveCertProbeAction}>
      <input type="hidden" name="connector_id" value={existing?.id ?? ""} />
      <FormRow label="Name">
        <Input
          name="name"
          required
          defaultValue={existing?.name ?? ""}
          placeholder="tls cert watcher"
        />
      </FormRow>
      <FormRow label="Targets" hint="one per line · name,host,port[,sni]">
        <textarea
          name="targets_raw"
          rows={6}
          defaultValue={
            initialTargets ||
            "# one target per line\n# lightsail-nginx,blackwatch.example.com,443\n# api-alb,api.example.com,443"
          }
          className="w-full border border-line bg-surface-1 px-2.5 py-2 font-mono text-xs text-fg placeholder:text-fg-disabled focus-visible:border-signal focus-visible:outline-none"
        />
      </FormRow>
      <FormRow label="Scan interval" hint="seconds · default 1h">
        <Input
          name="interval_seconds"
          type="number"
          mono
          defaultValue={String(cfg.interval_seconds ?? 3600)}
          className="w-32"
        />
      </FormRow>
      <FormRow label="Connect timeout" hint="seconds per endpoint">
        <Input
          name="timeout_seconds"
          type="number"
          mono
          defaultValue={String(cfg.timeout_seconds ?? 5)}
          className="w-24"
        />
      </FormRow>
      <FormActions isEdit={!!existing} />
      <FormNote>
        Opens a TLS handshake to each endpoint, reads the leaf cert, computes
        days until expiry. Emits an event only when{" "}
        <code className="text-fg">days &lt; 30</code> — healthy certs produce
        no noise. <strong>Limitation:</strong> OpenVPN&apos;s UDP handshake
        isn&apos;t a plain TLS endpoint. The OpenVPN server cert needs the SSH
        probe variant — planned follow-up. For now, use any HTTPS endpoint on
        the same host or your Lightsail nginx cert.
      </FormNote>
    </form>
  );
}

// --- styled native checkbox shared by the posture form -------------------

function CheckboxList({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-col gap-1.5">{children}</div>;
}

function Check({
  name,
  defaultChecked,
  children,
}: {
  name: string;
  defaultChecked: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-fg-muted hover:text-fg">
      <input
        type="checkbox"
        name={name}
        defaultChecked={defaultChecked}
        className="h-3.5 w-3.5 cursor-pointer appearance-none border border-line bg-surface-1 checked:border-signal checked:bg-signal/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal"
      />
      <span>{children}</span>
    </label>
  );
}
