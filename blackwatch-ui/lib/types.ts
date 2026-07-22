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

// --- IAM (AWS control-plane: logins, IAM, network, KMS, storage, CT) -----
// Sourced exclusively from CloudTrail → EventBridge → Lambda → SQS. Host
// SSH/sudo + VPN auth + host posture live on /hosts and /vpn — they're not
// AWS-API events and don't belong on this page.

export interface IamCounts {
  logins_ok: number;
  logins_failed: number;
  logins_root: number;
  logins_sso: number;
  iam_changes: number;
  mfa_disabled: number;
  sg_changes: number;
  network_topology: number;
  kms_changes: number;
  storage_exposure: number;
  ct_tamper: number;
  posture_findings_new: number;
}

export interface IamViewResponse {
  counts: IamCounts;
  logins: EventEnvelope[];
  iam_changes: EventEnvelope[];
  sg_changes: EventEnvelope[];
  network_topology: EventEnvelope[];
  storage_exposure: EventEnvelope[];
  kms_changes: EventEnvelope[];
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

// --- RDS module (log-based session tracking) ------------------------------

export interface RdsSession {
  session_id: string;
  db_instance: string;
  source_type: string;
  db_user: string | null;
  db_name: string | null;
  source_ip: string | null;
  source_port: number | null;
  connected_at: string | null;
  disconnected_at: string | null;
  duration_seconds: number;
  active: boolean;
}

export interface RdsDbSummary {
  db_instance: string;
  source_type: string;
  active: number;
  total_seen: number;
  last_activity: string | null;
  auth_failures_24h: number;
}

export interface RdsSummaryResponse {
  databases: RdsDbSummary[];
  auth_failures_24h_total: number;
}

export interface RdsLiveResponse {
  count: number;
  sessions: RdsSession[];
}

export interface RdsSessionsResponse {
  count: number;
  hours: number;
  sessions: RdsSession[];
}

export interface RdsAuthFailure {
  event_id: string | null;
  event_time: string | null;
  db_instance: string | null;
  source_type: string | null;
  user: string | null;
  source_ip: string | null;
  reason: string | null;
  message: string | null;
}

export interface RdsAuthFailuresResponse {
  count: number;
  hours: number;
  failures: RdsAuthFailure[];
}

// --- RDS Shape B --------------------------------------------------------

export interface RdsProxySource {
  source_ip: string;
  first_seen_at: string;
  last_seen_at: string;
  connect_count: number;
}

export interface RdsProxySourcesResponse {
  count: number;
  sources: RdsProxySource[];
}

export type RdsShapeBAction =
  | "rds.proxy.source.new"
  | "rds.session.new_source"
  | "rds.user.unknown";

export interface RdsShapeBAlert {
  event_id: string | null;
  event_time: string | null;
  action: RdsShapeBAction;
  db_instance: string | null;
  user: string | null;
  source_ip: string | null;
  trigger: string | null;
  message: string | null;
}

export interface RdsShapeBResponse {
  count: number;
  hours: number;
  alerts: RdsShapeBAlert[];
}

export interface RdsAllowlistEntry {
  username: string;
  kind: "human" | "service";
  note: string | null;
  added_at: string;
}

export interface RdsAllowlistResponse {
  count: number;
  users: RdsAllowlistEntry[];
}

// --- API Gateway --------------------------------------------------------

export interface ApiGwSummary {
  sources: number;
  requests: number;
  err_4xx: number;
  err_5xx: number;
  last_activity: string | null;
}

export interface ApiGwApi {
  api_name: string;
  source_count: number;
  request_count: number;
  error_4xx_count: number;
  error_5xx_count: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

export interface ApiGwApisResponse {
  count: number;
  apis: ApiGwApi[];
}

export interface ModulesRefreshRunEntry {
  connector_id: string;
  connector_name: string | null;
  type: string;
  status: string | null;
  ingested: number;
  error: string | null;
}

export interface ModulesRefreshResponse {
  ran: ModulesRefreshRunEntry[];
  total_ingested: number;
}

export interface ApiGwSource {
  source_ip: string;
  api_name: string;
  first_seen_at: string;
  last_seen_at: string;
  request_count: number;
  error_4xx_count: number;
  error_5xx_count: number;
}

export interface ApiGwSourcesResponse {
  count: number;
  sources: ApiGwSource[];
}

export type ApiGwAlertAction =
  | "api.source.new"
  | "api.auth.burst"
  | "api.error.burst"
  | "api.scanner_ua";

export interface ApiGwAlert {
  event_id: string | null;
  event_time: string | null;
  action: ApiGwAlertAction;
  api_name: string | null;
  source_ip: string | null;
  user_agent: string | null;
  scanner_signature: string | null;
  failure_count: number | null;
  error_count: number | null;
  message: string | null;
}

export interface ApiGwAlertsResponse {
  count: number;
  hours: number;
  alerts: ApiGwAlert[];
}

export interface ApiGwFailure {
  event_id: string | null;
  event_time: string | null;
  action: "api.auth.failure" | "api.error";
  api_name: string | null;
  source_ip: string | null;
  method: string | null;
  status: number | null;
  user_agent: string | null;
  reason: string | null;
  response_latency_ms: number | null;
}

export interface ApiGwFailuresResponse {
  count: number;
  hours: number;
  failures: ApiGwFailure[];
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

// --- Module cards (simple per-module routing) ----------------------------

export type CardThresholdKey = "critical" | "high" | "medium" | "low";

export interface CardThreshold {
  key: CardThresholdKey;
  label: string;
  includes: string[];
}

export interface CompanionRule {
  id: string;
  name: string;
  enabled: boolean;
  channels: string[];
}

export interface NotificationCard {
  module: string;
  label: string;
  icon: string;
  blurb: string;
  enabled: boolean;
  channel: string | null;
  threshold: CardThresholdKey;
  silence_until: string | null;
  rule_id: string | null;
  companion_rules: CompanionRule[];
}

export interface NotificationCardsResponse {
  cards: NotificationCard[];
  channels: Array<{ id: string; name: string; type: string; enabled: boolean }>;
  thresholds: CardThreshold[];
}

// --- Routes view (one page, everything's a rule) -------------------------

export type SeverityKey = "informational" | "low" | "medium" | "high" | "critical";

export interface Route {
  id: string;
  name: string | null;
  enabled: boolean;
  channel: string | null;
  channels: string[];
  severities: SeverityKey[];
  kind: "simple" | "custom";
  silence_until: string | null;
  silenced: boolean;
  match: Record<string, unknown>;
  message_template: string | null;
  module: string; // extracted from match; "__custom__" if none
  module_label: string;
}

export interface ModuleCatalogEntry {
  key: string;
  label: string;
  blurb: string;
}

export interface RoutesResponse {
  routes: Route[];
  catalog: ModuleCatalogEntry[];
  custom_bucket_key: string;
  channels: Array<{ id: string; name: string; type: string; enabled: boolean }>;
}

// --- Quick perf-alert cards ----------------------------------------------

export type PerfQuickMetric = "memory_pct" | "cpu_load_norm" | "disk_pct_max";

export interface PerfQuickExistingRule {
  id: string;
  name: string;
  enabled: boolean;
  instance_id: string | null;
  metric: PerfQuickMetric | string;
  threshold: number;
  window_seconds: number;
  severity: string;
  channels: string[];
}

export interface PerfQuickCard {
  metric: PerfQuickMetric;
  label: string;
  blurb: string;
  default_threshold: number;
  default_window_minutes: number;
  default_severity: string;
  existing: PerfQuickExistingRule[];
}

export interface PerfQuickResponse {
  cards: PerfQuickCard[];
  channels: Array<{ name: string; type: string; enabled: boolean }>;
  instances: Array<{ instance_id: string; hostname: string | null }>;
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
  display_name: string | null;
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

export interface HostMetricsHourlyRow {
  hour_start: string;
  mem_min: number | null;
  mem_avg: number | null;
  mem_max: number | null;
  cpu_min: number | null;
  cpu_avg: number | null;
  cpu_max: number | null;
  sample_count: number;
}

export interface HostMetricsResponse {
  instance_id: string;
  hours: number;
  count: number;
  series: HostMetricsHourlyRow[];
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
  fim_coverage: FimCoverage | null;
  fim_recent_changes: FimChange[];
}

// FIM coverage + per-file change history.
//   Part 1 (periodic baseline): paths_configured, files_tracked, scan stats
//   Part 2 (real-time inotify): paths_inotify, inotify_active, watch count
//   Part 3 (whodata via auditd): auditd_active + per-change actor fields
//                                + configured_paths for the "what are we watching" UI
export interface FimCoverage {
  paths_configured: number;
  files_tracked: number;
  last_full_scan_at: string | null;
  last_scan_duration_ms: number | null;
  scan_errors: number;
  updated_at: string | null;
  paths_inotify: number;
  paths_baseline_only: number;
  inotify_active: boolean;
  inotify_watch_count: number;
  auditd_active: boolean;
  configured_paths: FimConfiguredPaths | null;
}

export interface FimConfiguredPaths {
  critical_files: string[];
  critical_dirs: string[];
  binary_dirs: string[];
}

export interface FimChange {
  path: string;
  changed_at: string | null;
  change_type:
    | "created"
    | "modified"
    | "deleted"
    | "perm_changed"
    | "owner_changed";
  sha256_before: string | null;
  sha256_after: string | null;
  size_before: number | null;
  size_after: number | null;
  perm_before: number | null;
  perm_after: number | null;
  owner_before: string | null;
  owner_after: string | null;
  event_id: string | null;
  // Which detection path caught this change.
  detection: "baseline" | "inotify" | "auditd" | null;
  // Part 3 — populated only when auditd whodata had a fresh hit.
  actor_uid: number | null;
  actor_gid: number | null;
  actor_pid: number | null;
  actor_comm: string | null;
  actor_exe: string | null;
  actor_proctitle: string | null;
}

// FIM cross-host view (drives the /fim top-level page).

export interface FimHostRow {
  instance_id: string;
  hostname: string | null;
  account: string | null;
  region: string | null;
  tags: Record<string, string> | null;
  host_updated_at: string | null;
  age_seconds: number | null;
  stale: boolean;
  files_tracked: number;
  paths_configured: number;
  last_full_scan_at: string | null;
  inotify_active: boolean;
  inotify_watch_count: number;
  auditd_active: boolean;
  coverage_updated_at: string | null;
  scan_errors: number;
}

// FIM history with instance_id attached (cross-host activity table).
export interface FimChangeWithInstance extends FimChange {
  instance_id: string;
}

export interface FimViewResponse {
  count: number;
  hosts: FimHostRow[];
  recent_changes: FimChangeWithInstance[];
}

// Per-instance FIM detail page.

export interface FimPathSummary {
  category: "critical_files" | "critical_dirs" | "binary_dirs";
  category_label: string;
  path: string;
  file_count: number;
  total_size_bytes: number;
}

export interface FimStrayBaseline {
  path: string;
  sha256: string;
  size: number;
  perm: number;
  owner_uid: number;
  owner_gid: number;
  last_seen_at: string | null;
}

export interface FimInstanceResponse {
  instance_id: string;
  coverage: FimCoverage | null;
  paths_summary: FimPathSummary[];
  stray_baselines: FimStrayBaseline[];
  stray_count: number;
  recent_changes: FimChange[];
}

// --- Performance alert rules -----------------------------------------------

export type PerfMetric =
  | "memory_pct"
  | "cpu_load_norm"
  | "cpu_utilization_pct"
  | "disk_pct_max";

export type PerfComparison = "gte" | "gt" | "lte" | "lt";

export type PerfSeverity =
  | "informational"
  | "low"
  | "medium"
  | "high"
  | "critical";

export interface PerfAlertRule {
  id: string;
  name: string;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
  module: string;
  instance_id: string | null;
  tag_key: string | null;
  tag_value: string | null;
  instance_ids: string[];
  metric: PerfMetric;
  comparison: PerfComparison;
  threshold: number;
  window_seconds: number;
  min_breach_ratio: number;
  severity: PerfSeverity;
  channels: string[];
  throttle_seconds: number;
  message_template?: string | null;
  samples?: Array<{ t: number; b: boolean; v: number }>;
  last_fired_at?: string | null;
  last_value: number | null;
}

export interface PerfAlertInstance {
  instance_id: string;
  hostname: string | null;
  display_name: string | null;
  tags: Record<string, string> | null;
}

export interface PerfAlertChannel {
  id: string;
  name: string;
  type: string | null;
  enabled: boolean;
}

export interface PerfAlertsListResponse {
  rules: PerfAlertRule[];
  instances: PerfAlertInstance[];
  channels: PerfAlertChannel[];
}

export interface HostRecord {
  instance_id: string;
  hostname: string | null;
  display_name: string | null;
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
  down_since: string | null;
  config?: Record<string, unknown> | null;
}

export interface ServiceCounts {
  total: number;
  up: number;
  down: number;
  degraded: number;
  unknown: number;
  disabled: number;
}

export interface ServicesListResponse {
  agents: ProbeAgent[];
  grouped: Record<string, ServiceTarget[]>;
  counts: Record<string, ServiceCounts>;
  archived: ServiceTarget[];
  archive_threshold_days: number;
}

// --- Rules + noise --------------------------------------------------------

export interface Rule {
  id: string;
  title: string;
  description?: string;
  enabled: boolean;
  /** The rule's OWN action — "alert" or "suppress". */
  rule_action: "alert" | "suppress";
  /** The event action strings this rule fires on, extracted from the
   *  match condition. Empty for rules that match on non-action fields
   *  (e.g. tag-based matches). */
  matched_actions: string[];
  severity: Severity | string | null;
  tags: string[];
}

export interface MutedEvent {
  id: number;
  action: string;
  /** NULL = matches any value on the incoming event. */
  source_type: string | null;
  username: string | null;
  reason: string | null;
  note: string | null;
  created_at: string;
}

export interface RulesResponse {
  count: number;
  rules: Rule[];
  muted: MutedEvent[];
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
