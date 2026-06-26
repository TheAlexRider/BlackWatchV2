// Shape of an event envelope returned by the BlackWatch API.
// Mirrors blackwatch/events.py + storage.query_events output.

export type Severity =
  | "critical"
  | "high"
  | "medium"
  | "low"
  | "informational"
  | "unscored";

export const SEVERITY_VALUES: Severity[] = [
  "critical",
  "high",
  "medium",
  "low",
  "informational",
];

export interface EventEnvelope {
  event_id: string;
  event_time: string; // ISO 8601
  schema_version?: number;
  category?: string;
  severity?: Severity | string | null;
  action: string;
  outcome?: string;
  account?: string;
  region?: string;
  source?: {
    module?: string;
    transport?: string;
    raw?: unknown;
  };
  actor?: {
    principal?: string;
    [k: string]: unknown;
  };
  target?: {
    id?: string;
    name?: string;
    type?: string;
    [k: string]: unknown;
  };
  rule_matches?: string[];
  // Pass-through for anything else the backend includes
  [k: string]: unknown;
}

export interface EventsResponse {
  count: number;
  events: EventEnvelope[];
}

// --- Posture findings ------------------------------------------------------

// --- IAM (centerpiece module — logins, IAM changes, SGs, KMS, AssumeRole) -

export interface IamCounts {
  logins_ok: number;
  logins_failed: number;
  host_vpn_auth_failed: number;
  iam_changes: number;
  sg_changes: number;
  kms_changes: number;
  storage_exposure: number;
  host_changes: number;
  assume_roles: number;
  ct_tamper: number;
  posture_findings_new: number;
}

export interface IamViewResponse {
  counts: IamCounts;
  logins: EventEnvelope[];
  host_vpn_auth: EventEnvelope[];
  iam_changes: EventEnvelope[];
  sg_changes: EventEnvelope[];
  storage_exposure: EventEnvelope[];
  kms_changes: EventEnvelope[];
  host_changes: EventEnvelope[];
  assume_roles: EventEnvelope[];
  posture_findings_new: EventEnvelope[];
  ct_tamper: EventEnvelope[];
}

// --- VPN -----------------------------------------------------------------

export interface VpnClient {
  common_name?: string | null;
  username?: string | null;
  real_ip?: string | null;
  virtual_address?: string | null;
  connected_since?: string | null;
  bytes_received?: number | null;
  bytes_sent?: number | null;
}

export type VpnCertKind =
  | "ca"
  | "server"
  | "client"
  | "revoked"
  | "crl"
  | string;

export type VpnCertSource = "pki" | "live" | string;

export interface VpnCertificate {
  kind: VpnCertKind;
  name: string;
  /** Which root the cert was found in: 'pki' = easy-rsa source of truth,
   * 'live' = the file OpenVPN actually reads. Mismatches between the two
   * for the same cert kind = renew-but-not-copied. */
  source?: VpnCertSource | null;
  path?: string | null;
  subject?: string | null;
  issuer?: string | null;
  not_after?: string | null;
  last_update?: string | null; // CRL only
  days_remaining?: number | null;
  revoked?: boolean;
  error?: string | null;
}

export interface VpnServer {
  server: string;
  active: boolean;
  updated_at: string | null;
  age_seconds: number | null;
  stale: boolean;
  client_count: number;
  clients: VpnClient[];
  certs: VpnCertificate[];
}

export interface VpnResponse {
  servers: VpnServer[];
  auth: EventEnvelope[];
}

// --- RDS -------------------------------------------------------------------

export interface RdsCounts {
  events_24h: number;
  instances_seen: number;
  public_flagged: number;
  no_backups_flagged: number;
  unencrypted_flagged: number;
  snapshot_public_flagged: number;
  no_deletion_protection_flagged: number;
}

export interface RdsInstance {
  instance_id: string;
  events_30d: number;
  last_event_time: string | null;
  last_action: string | null;
  last_actor: string | null;
  // Names of the rds_* flags the adapter has set on any event for this
  // instance in the last 30 days. Stay set until BlackWatch sees the fix.
  flags: string[];
}

export interface RdsViewResponse {
  counts: RdsCounts;
  instances: RdsInstance[];
  recent_events: EventEnvelope[];
  have_connector: boolean;
}

// --- Notifications ---------------------------------------------------------

export type ChannelType =
  | "slack"
  | "webhook"
  | "email"
  | "pagerduty"
  | "teams"
  | "discord";

export const CHANNEL_TYPES: ChannelType[] = [
  "slack",
  "webhook",
  "email",
  "pagerduty",
  "teams",
  "discord",
];

export interface NotificationChannel {
  id: string;
  name: string;
  type: ChannelType | string;
  enabled: boolean;
  config: Record<string, unknown>;
  message_template: string | null;
  retries: number;
  retry_backoff_seconds: number;
  rate_limit_per_min: number;
  dedup_window_seconds: number;
  digest_window_seconds: number;
  last_status: string | null;
  last_error: string | null;
  last_sent_at: string | null;
}

export interface NotificationChannelsResponse {
  count: number;
  channels: NotificationChannel[];
}

export interface NotificationRule {
  id: string;
  name: string;
  enabled: boolean;
  match: Record<string, unknown>;
  channels: string[];
  throttle_seconds: number;
  priority: number;
  silence_until: string | null;
  silenced: boolean;
}

export interface NotificationRulesResponse {
  count: number;
  rules: NotificationRule[];
}

export interface NotificationLogEntry {
  id: string | number;
  ts: string;
  rule_name: string | null;
  channel_name: string | null;
  event_id: string | null;
  event_action: string | null;
  event_severity: string | null;
  status: string;
  retries_used: number;
  body_preview: string | null;
  error_message: string | null;
}

export interface NotificationLogResponse {
  count: number;
  entries: NotificationLogEntry[];
}

export interface NotificationAck {
  fingerprint: string;
  ack_until: string;
  reason: string | null;
  created_at: string;
}

export interface NotificationAcksResponse {
  count: number;
  acks: NotificationAck[];
}

export interface LivePingResponse {
  ts: string;
  events_last_60s: number;
  eps: number;
}

// Simple criteria the rule wizard captures. Server actions translate this
// to the Condition tree the backend expects.
export interface SimpleRuleCriteria {
  severity_at_least?: "critical" | "high" | "medium" | "low" | "any";
  categories?: string[];
  modules?: string[];
  action_contains?: string;
}

// --- Overview --------------------------------------------------------------

export interface OverviewResponse {
  now: string;
  severity_counts: Record<string, number>;
  notable: EventEnvelope[];
  recent: EventEnvelope[];
  volume_24h: number;
  hosts: {
    total: number;
    reporting: number;
    stale: number;
  };
  posture: {
    total_open: number;
    by_severity: {
      critical: number;
      high: number;
      medium: number;
      low: number;
      informational: number;
    };
  };
}

export interface PostureFinding {
  finding_id: string;
  resource_id: string;
  resource_type: string;
  finding_type: string;
  severity: Severity | string;
  region: string | null;
  account: string | null;
  evidence: Record<string, unknown>;
  first_seen: string;
  last_seen: string;
  resolved_at: string | null;
}

export interface PostureFindingsResponse {
  count: number;
  findings: PostureFinding[];
  have_connector: boolean;
}

// --- Hosts -----------------------------------------------------------------

export interface HostSummary {
  instance_id: string;
  hostname: string | null;
  account: string | null;
  region: string | null;
  active: boolean;
  age_seconds: number | null;
  stale: boolean;
  updated_at: string | null;
  tags: Record<string, string> | null;
  port_count: number;
  user_count: number;
  key_count: number;
}

export interface HostsListResponse {
  count: number;
  servers: HostSummary[];
  auth: EventEnvelope[];
  changes: EventEnvelope[];
}

export interface HostDetailResponse {
  instance_id: string;
  host: HostRecord | null;
  snapshots: HostSnapshots;
  age_seconds: number | null;
  stale: boolean;
  auth_events: EventEnvelope[];
  state_changes: EventEnvelope[];
  alerts: EventEnvelope[];
}

export interface HostRecord {
  instance_id: string;
  hostname: string | null;
  account: string | null;
  region: string | null;
  active: boolean;
  updated_at: string | null;
  extra?: HostExtra | null;
}

// Heartbeat-extra payload from the EC2 agent (v1.1+)
export interface HostExtra {
  uptime_seconds?: number | null;
  agent_version?: string | null;
  tick_duration_ms?: number | null;
  tags?: Record<string, string> | null;
  collector_errors?: Record<string, string> | null;
  stalled_collectors?: string[] | null;
  active_sessions?: HostSession[] | null;
  rpm_db_corrupted?: { lock_count: number } | null;
  memory?: {
    used_pct?: number | null;
    used_kb?: number | null;
    total_kb?: number | null;
  } | null;
  cpu?: {
    load_1min?: number | null;
    load_5min?: number | null;
    load_norm_1min?: number | null;
    cpu_count?: number | null;
  } | null;
  _state?: { cpu_anomaly_active?: boolean | null } | null;
  _baseline_cpu?: { mean: number; n: number } | null;
  [k: string]: unknown;
}

export interface HostSession {
  user: string;
  tty: string;
  source: string | null;
  login: string;
}

export interface HostSnapshots {
  ports?: HostPort[];
  processes?: HostProcess[];
  users?: HostUser[];
  authorized_keys?: HostAuthorizedKey[];
  sudoers?: Record<string, string>;
  critical_files?: Record<string, string>;
  cron?: Record<string, string>;
  systemd_units?: string[];
  kernel_modules?: string[];
  suid?: string[];
  packages?: string[];
  disk?: HostDisk[];
}

export interface HostPort {
  proto: string;
  address: string;
  port: number;
  process: string | null;
}

export interface HostProcess {
  user: string;
  pid: number;
  comm: string;
  args: string;
}

export interface HostUser {
  name: string;
  uid: number;
  shell: string;
}

export interface HostAuthorizedKey {
  user: string;
  fingerprint: string;
  preview: string;
}

export interface HostDisk {
  mount: string;
  fs_type: string;
  used_pct: number;
  used: number;
  total: number;
}

// --- Services --------------------------------------------------------------

export interface ProbeAgent {
  vpc: string;
  active: boolean | null;
  agent_version: string | null;
  last_report: string | null;
}

export interface ServiceTarget {
  id: string;
  name: string;
  vpc: string;
  tier: string;
  enabled: boolean;
  severity_when_down: Severity | string;
  tags: Record<string, string> | null;
  status: "up" | "down" | "degraded" | "unknown" | string;
  last_seen: string | null;
  age_seconds: number | null;
  stale: boolean;
  latency_ms: number | null;
  consecutive_fails: number;
  config?: Record<string, unknown> | null;
}

export interface ServicesListResponse {
  agents: ProbeAgent[];
  grouped: Record<string, ServiceTarget[]>;
}

// --- Rules + noise --------------------------------------------------------

export interface Rule {
  id: string;
  title: string;
  enabled: boolean;
  action: string;
  severity: Severity | string | null;
  tags: string[];
}

export interface RulesResponse {
  count: number;
  rules: Rule[];
  muted: string[];
}

// --- Buckets --------------------------------------------------------------

export interface BlockPublicAccess {
  block_public_acls: boolean;
  ignore_public_acls: boolean;
  block_public_policy: boolean;
  restrict_public_buckets: boolean;
}

export interface BucketStatus {
  bucket_name: string;
  region: string | null;
  account: string | null;
  public: boolean;
  public_reasons: string[] | null;
  encryption: string;
  versioning: "Enabled" | "Suspended" | "Disabled" | string | null;
  mfa_delete: boolean | null;
  block_public_access: BlockPublicAccess | null;
  logging_target: string | null;
  tags: Record<string, string> | null;
  last_scan: string | null;
}

export interface BucketsListResponse {
  count: number;
  buckets: BucketStatus[];
  counts: {
    total: number;
    public: number;
    unencrypted: number;
    no_versioning: number;
  };
}

// --- Connectors -----------------------------------------------------------

export type ConnectorType =
  | "aws_cloudtrail_sqs"
  | "aws_ecs_health"
  | "aws_s3_drift"
  | "aws_posture_drift"
  | "cert_probe";

export interface Connector {
  id: string;
  name: string;
  type: ConnectorType | string;
  enabled: boolean;
  verified: boolean;
  config: Record<string, unknown>;
  last_run_at: string | null;
  last_status: "ok" | "error" | null | string;
  last_error: string | null;
}

export interface ConnectorsListResponse {
  count: number;
  connectors: Connector[];
}

// Per-type config field maps (loose — backend is Pydantic-validated)
export interface CloudTrailSqsConfig {
  target_module?: string;
  queue_url?: string;
  aws_region?: string;
  aws_profile?: string;
  interval_seconds?: number;
}

export interface EcsHealthConfig {
  vpc?: string;
  aws_region?: string;
  aws_profile?: string;
  interval_seconds?: number;
  running_smoothing_minutes?: number;
}

export interface S3DriftConfig {
  aws_profile?: string;
  interval_seconds?: number;
}

export interface CertProbeTarget {
  name: string;
  host: string;
  port: number;
  sni?: string | null;
}

export interface CertProbeConfig {
  targets?: CertProbeTarget[];
  interval_seconds?: number;
  timeout_seconds?: number;
}

export interface PostureDriftConfig {
  aws_profile?: string;
  regions?: string[];
  interval_seconds?: number;
  check_sg_public_ingress?: boolean;
  check_ebs_encryption?: boolean;
  check_ebs_snapshot_public?: boolean;
  check_ec2_imdsv2?: boolean;
  check_ami_public?: boolean;
  check_iam_user_no_mfa?: boolean;
  check_iam_key_age?: boolean;
  check_iam_key_unused?: boolean;
  check_iam_role_wildcard_trust?: boolean;
  check_kms_rotation?: boolean;
  check_kms_policy_wildcard?: boolean;
  check_cloudtrail_validation?: boolean;
  check_rds?: boolean;
  iam_key_max_age_days?: number;
  iam_key_unused_threshold_days?: number;
}
