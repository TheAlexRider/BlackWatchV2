// Server-only fetch helpers. Called from Server Components / route handlers.
// Targets the FastAPI JSON API (mounted at /api/* on the backend).
//
// In docker-compose:    BW_API_URL=http://app:8000   (set in compose env)
// Local dev (host):     defaults to http://localhost:8000

import type {
  EventEnvelope,
  EventsResponse,
  PostureFinding,
  PostureFindingsResponse,
  HostsListResponse,
  HostDetailResponse,
  HostMetricsResponse,
  ServicesListResponse,
  RulesResponse,
  BucketsListResponse,
  Connector,
  ConnectorsListResponse,
  OverviewResponse,
  VpnResponse,
  RdsViewResponse,
  RdsSummaryResponse,
  RdsLiveResponse,
  RdsSessionsResponse,
  RdsAuthFailuresResponse,
  RdsProxySourcesResponse,
  RdsShapeBResponse,
  RdsAllowlistResponse,
  ApiGwSummary,
  ApiGwApisResponse,
  ApiGwSourcesResponse,
  ApiGwAlertsResponse,
  ApiGwFailuresResponse,
  IamViewResponse,
  NotificationChannel,
  NotificationChannelsResponse,
  NotificationRule,
  NotificationRulesResponse,
  NotificationCardsResponse,
  RoutesResponse,
  NotificationLogResponse,
  PerfQuickResponse,
  NotificationAcksResponse,
  LivePingResponse,
  FimViewResponse,
  FimInstanceResponse,
  PerfAlertRule,
  PerfAlertsListResponse,
} from "./types";

export const API_BASE = process.env.BW_API_URL ?? "http://localhost:8000";

const SESSION_COOKIE = "bw_session";

// Server-side fetches originating in Server Components do not automatically
// carry the browser's cookies — Node.js has no idea which browser tab this
// render belongs to. But the FastAPI backend now requires a valid session
// cookie on every /api/* route (see blackwatch/main.py auth middleware).
// So we look up the current request's cookie via next/headers and attach
// it manually to every server-side fetch. Client-side fetches (from
// components that use previewTemplate etc.) still work because the
// browser attaches the cookie itself on relative-URL fetches.
async function _authHeader(): Promise<Record<string, string>> {
  if (typeof window !== "undefined") return {}; // client — browser handles it
  try {
    // Dynamic import so client bundles don't drag in next/headers.
    const mod = await import("next/headers");
    const store = await mod.cookies();
    const sid = store.get(SESSION_COOKIE)?.value;
    return sid ? { Cookie: `${SESSION_COOKIE}=${sid}` } : {};
  } catch {
    // Not inside a Next.js request context (e.g. during a static build).
    return {};
  }
}

// Exported so server actions in app/**/actions.ts can piggy-back on the
// same cookie-forwarding logic instead of each hand-rolling its own auth.
export async function bwFetch(pathOrUrl: string, init?: RequestInit): Promise<Response> {
  const auth = await _authHeader();
  // Accept either a plain path (`/api/events`) or an absolute URL. This
  // matters because some callers build query strings on top of API_BASE
  // and pass the full URL — we want them to work through bwFetch too.
  const url = pathOrUrl.startsWith("http") ? pathOrUrl : `${API_BASE}${pathOrUrl}`;
  return fetch(url, {
    ...init,
    cache: init?.cache ?? "no-store",
    headers: {
      ...(init?.headers as Record<string, string> | undefined),
      ...auth,
    },
  });
}

export interface EventsQuery {
  q?: string;
  severity?: string;
  category?: string;
  module?: string;
  action?: string;
  limit?: number;
}

export async function fetchEvents(query: EventsQuery = {}): Promise<EventsResponse> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  if (!query.limit) search.set("limit", "200");

  const url = `${API_BASE}/api/events?${search.toString()}`;
  const res = await bwFetch(url);
  if (!res.ok) {
    throw new Error(`fetchEvents failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as EventsResponse;
}

export async function fetchEvent(eventId: string): Promise<EventEnvelope | null> {
  const url = `${API_BASE}/api/events/${encodeURIComponent(eventId)}`;
  const res = await bwFetch(url);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`fetchEvent failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as EventEnvelope;
}

// --- Posture findings ------------------------------------------------------

export async function fetchPostureFindings(query: {
  unresolved_only?: boolean;
  resource_type?: string;
  account?: string;
} = {}): Promise<PostureFindingsResponse> {
  const search = new URLSearchParams();
  if (query.unresolved_only !== undefined) {
    search.set("unresolved_only", String(query.unresolved_only));
  }
  if (query.resource_type) search.set("resource_type", query.resource_type);
  if (query.account) search.set("account", query.account);

  const url = `${API_BASE}/api/posture/findings?${search.toString()}`;
  const res = await bwFetch(url);
  if (!res.ok) {
    throw new Error(`fetchPostureFindings failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as PostureFindingsResponse;
}

export async function fetchPostureFinding(
  findingId: string,
): Promise<PostureFinding | null> {
  const url = `${API_BASE}/api/posture/findings/${encodeURIComponent(findingId)}`;
  const res = await bwFetch(url);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`fetchPostureFinding failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as PostureFinding;
}

// --- Hosts ----------------------------------------------------------------

export async function fetchHosts(): Promise<HostsListResponse> {
  const res = await bwFetch(`/api/hosts`);
  if (!res.ok) throw new Error(`fetchHosts failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as HostsListResponse;
}

export async function fetchHostDetail(
  instanceId: string,
): Promise<HostDetailResponse> {
  const url = `${API_BASE}/api/hosts/${encodeURIComponent(instanceId)}`;
  const res = await bwFetch(url);
  if (!res.ok) {
    throw new Error(`fetchHostDetail failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as HostDetailResponse;
}

// Hourly memory/CPU rollup for the chart on the host detail page.
// Server caps `hours` at the 9-day retention window (216).
//
// Called from a CLIENT component (HostMetricsChart), so this MUST use a
// relative URL. The browser can't reach API_BASE (which is the Docker-
// internal FastAPI hostname / localhost:8000) — Next.js's rewrite rule in
// next.config.mjs proxies /api/* to the FastAPI server. Same pattern as
// fetchTemplatePresets / previewTemplate / setHostDisplayName.
export async function fetchHostMetrics(
  instanceId: string,
  hours: number = 48,
): Promise<HostMetricsResponse> {
  const res = await fetch(
    `/api/hosts/${encodeURIComponent(instanceId)}/metrics?hours=${hours}`,
    { cache: "no-store" },
  );
  if (!res.ok) {
    throw new Error(`fetchHostMetrics failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as HostMetricsResponse;
}

// Set the user-editable friendly name for a host. Client-callable — uses a
// relative URL so the browser's cookie is attached. Server clears the name
// on empty/null so callers can wipe it back to "hostname > id" fallback.
export async function setHostDisplayName(
  instanceId: string,
  displayName: string | null,
): Promise<{ instance_id: string; display_name: string | null }> {
  const res = await fetch(
    `/api/hosts/${encodeURIComponent(instanceId)}/display-name`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: displayName }),
      cache: "no-store",
    },
  );
  if (!res.ok) throw new Error(`setHostDisplayName failed: ${res.status}`);
  return await res.json();
}

// Resolve the display label for a host object across the UI. Single source
// of truth: display_name > hostname > instance_id. Every list/card/select
// that shows an instance should call this.
export function hostLabel(host: {
  display_name?: string | null;
  hostname?: string | null;
  instance_id: string;
}): string {
  return host.display_name || host.hostname || host.instance_id;
}

// --- File Integrity (FIM) -------------------------------------------------

export async function fetchFimView(): Promise<FimViewResponse> {
  const res = await bwFetch(`/api/fim`);
  if (!res.ok) throw new Error(`fetchFimView failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as FimViewResponse;
}

export async function fetchFimInstance(
  instanceId: string,
): Promise<FimInstanceResponse> {
  const url = `${API_BASE}/api/fim/${encodeURIComponent(instanceId)}`;
  const res = await bwFetch(url);
  if (!res.ok) {
    throw new Error(`fetchFimInstance failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as FimInstanceResponse;
}

// --- Performance alerts ---------------------------------------------------

export async function fetchPerfAlerts(): Promise<PerfAlertsListResponse> {
  const res = await bwFetch(`/api/perf-alerts`);
  if (!res.ok) throw new Error(`fetchPerfAlerts failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as PerfAlertsListResponse;
}

export async function fetchPerfAlert(ruleId: string): Promise<PerfAlertRule> {
  const url = `${API_BASE}/api/perf-alerts/${encodeURIComponent(ruleId)}`;
  const res = await bwFetch(url);
  if (!res.ok) {
    throw new Error(`fetchPerfAlert failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as PerfAlertRule;
}

// --- Services --------------------------------------------------------------

export async function fetchServices(): Promise<ServicesListResponse> {
  const res = await bwFetch(`/api/services`);
  if (!res.ok) throw new Error(`fetchServices failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as ServicesListResponse;
}

// --- Rules + noise -------------------------------------------------------

export async function fetchRules(): Promise<RulesResponse> {
  const res = await bwFetch(`/api/rules`);
  if (!res.ok) throw new Error(`fetchRules failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as RulesResponse;
}

// --- Buckets -------------------------------------------------------------

export async function fetchBuckets(): Promise<BucketsListResponse> {
  const res = await bwFetch(`/api/buckets`);
  if (!res.ok) throw new Error(`fetchBuckets failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as BucketsListResponse;
}

// --- Notifications -------------------------------------------------------

export async function fetchNotificationChannels(): Promise<NotificationChannelsResponse> {
  const res = await bwFetch(`/api/notifications/channels`);
  if (!res.ok) throw new Error(`fetchNotificationChannels failed: ${res.status}`);
  return (await res.json()) as NotificationChannelsResponse;
}

export async function fetchNotificationChannel(id: string): Promise<NotificationChannel | null> {
  const res = await bwFetch(
    `/api/notifications/channels/${encodeURIComponent(id)}`,
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`fetchNotificationChannel failed: ${res.status}`);
  return (await res.json()) as NotificationChannel;
}

export async function fetchNotificationRules(): Promise<NotificationRulesResponse> {
  const res = await bwFetch(`/api/notifications/rules`);
  if (!res.ok) throw new Error(`fetchNotificationRules failed: ${res.status}`);
  return (await res.json()) as NotificationRulesResponse;
}

export async function fetchNotificationCards(): Promise<NotificationCardsResponse> {
  const res = await bwFetch(`/api/notifications/cards`);
  if (!res.ok) throw new Error(`fetchNotificationCards failed: ${res.status}`);
  return (await res.json()) as NotificationCardsResponse;
}

export async function fetchNotificationRoutes(): Promise<RoutesResponse> {
  const res = await bwFetch(`/api/notifications/routes`);
  if (!res.ok) throw new Error(`fetchNotificationRoutes failed: ${res.status}`);
  return (await res.json()) as RoutesResponse;
}

export async function fetchPerfQuick(): Promise<PerfQuickResponse> {
  const res = await bwFetch(`/api/notifications/perf-alerts/quick`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`fetchPerfQuick failed: ${res.status}`);
  return (await res.json()) as PerfQuickResponse;
}

export async function fetchNotificationRule(id: string): Promise<NotificationRule | null> {
  const res = await bwFetch(
    `/api/notifications/rules/${encodeURIComponent(id)}`,
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`fetchNotificationRule failed: ${res.status}`);
  return (await res.json()) as NotificationRule;
}

export async function fetchNotificationLog(query: {
  status?: string;
  channel?: string;
  rule?: string;
  limit?: number;
} = {}): Promise<NotificationLogResponse> {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== "") search.set(k, String(v));
  }
  const res = await bwFetch(`/api/notifications/log?${search}`);
  if (!res.ok) throw new Error(`fetchNotificationLog failed: ${res.status}`);
  return (await res.json()) as NotificationLogResponse;
}

export async function fetchNotificationAcks(): Promise<NotificationAcksResponse> {
  const res = await bwFetch(`/api/notifications/acks`);
  if (!res.ok) throw new Error(`fetchNotificationAcks failed: ${res.status}`);
  return (await res.json()) as NotificationAcksResponse;
}

// --- Template presets / preview (channel form helpers) -------------------

export type TemplatePreset = {
  id: string;
  name: string;
  blurb: string;
  template: string;
};

// NOTE: these two are called from a CLIENT component (TemplateEditor), so
// they MUST use a relative URL. The browser can't reach API_BASE (which is
// the Docker-internal FastAPI hostname). Next.js's rewrite rule in
// next.config.mjs proxies /api/* to FastAPI server-side, so a relative URL
// works in both dev and prod.
export type TemplateContextKind = "event" | "perf";

export async function fetchTemplatePresets(
  channelType: string,
  contextKind: TemplateContextKind = "event",
): Promise<TemplatePreset[]> {
  const qs = new URLSearchParams({ channel_type: channelType });
  if (contextKind !== "event") qs.set("context_kind", contextKind);
  const res = await fetch(`/api/notifications/templates?${qs.toString()}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`fetchTemplatePresets failed: ${res.status}`);
  const j = (await res.json()) as { type: string; presets: TemplatePreset[] };
  return j.presets ?? [];
}

export type PreviewSampleKind =
  | "vpn_failure"
  | "perf_alert"
  | "fim_modified"
  | "ssh_failure"
  | "iam_key_created"
  | "rds_auth_failure"
  | "service_down"
  | "service_degraded"
  | "service_up"
  | "probe_agent_stale";

// perf_context overlays the wizard's live form state on the server's
// default perf preview sample — metric, threshold, window, comparison,
// severity, hostname, tags — so the preview reflects the rule being built.
export type PerfPreviewContext = {
  metric?: string;
  metric_label?: string;
  threshold?: number;
  window_minutes?: number;
  comparison?: string;
  severity?: string;
  hostname?: string;
  instance_id?: string;
  tags?: Record<string, string>;
  rule_name?: string;
};

export async function previewTemplate(
  template: string,
  opts?: {
    channelName?: string;
    channelType?: string;
    sampleEvent?: PreviewSampleKind;
    eventId?: string;
    contextKind?: TemplateContextKind;
    perfContext?: PerfPreviewContext;
  },
): Promise<{ rendered: string; error: string | null }> {
  const res = await fetch(`/api/notifications/templates/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      template,
      channel_name: opts?.channelName,
      channel_type: opts?.channelType,
      sample_event: opts?.sampleEvent,
      event_id: opts?.eventId,
      context_kind: opts?.contextKind,
      perf_context: opts?.perfContext,
    }),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`previewTemplate failed: ${res.status}`);
  return (await res.json()) as { rendered: string; error: string | null };
}

// Fires the current template + sample through the named channel so the
// operator can see the exact message land in Slack/etc. Server renders,
// then delivers via the type-specific sender. Returns delivery status.
export async function testSendTemplate(opts: {
  channelName: string;
  template: string;
  channelType?: string;
  sampleEvent?: PreviewSampleKind;
  contextKind?: TemplateContextKind;
  perfContext?: PerfPreviewContext;
}): Promise<{
  channel: string;
  status: "sent" | "error" | "render_error" | "unknown_channel";
  detail?: string;
  rendered?: string;
}> {
  const res = await fetch(`/api/notifications/templates/test-send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      channel_name: opts.channelName,
      template: opts.template,
      channel_type: opts.channelType,
      sample_event: opts.sampleEvent,
      context_kind: opts.contextKind,
      perf_context: opts.perfContext,
    }),
    cache: "no-store",
  });
  if (!res.ok) {
    return {
      channel: opts.channelName,
      status: "error",
      detail: `HTTP ${res.status}`,
    };
  }
  return await res.json();
}

export interface RecentEventSample {
  event_id: string;
  event_time: string;
  action: string;
  severity: string | null;
  module: string | null;
  principal: string | null;
  target_name: string | null;
}

export async function fetchRecentEventsForPreview(
  limit = 20,
): Promise<RecentEventSample[]> {
  const res = await fetch(
    `/api/notifications/templates/recent-events?limit=${limit}`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(`fetchRecentEventsForPreview failed: ${res.status}`);
  const j = (await res.json()) as { events: RecentEventSample[] };
  return j.events ?? [];
}

// --- IAM ------------------------------------------------------------------

export async function fetchIam(): Promise<IamViewResponse> {
  const res = await bwFetch(`/api/iam`);
  if (!res.ok) throw new Error(`fetchIam failed: ${res.status}`);
  return (await res.json()) as IamViewResponse;
}

// --- VPN ------------------------------------------------------------------

export async function fetchVpn(): Promise<VpnResponse> {
  const res = await bwFetch(`/api/vpn`);
  if (!res.ok) throw new Error(`fetchVpn failed: ${res.status}`);
  return (await res.json()) as VpnResponse;
}

// --- RDS ------------------------------------------------------------------

export async function fetchRds(): Promise<RdsViewResponse> {
  const res = await bwFetch(`/api/rds`);
  if (!res.ok) throw new Error(`fetchRds failed: ${res.status}`);
  return (await res.json()) as RdsViewResponse;
}

export async function fetchRdsSummary(): Promise<RdsSummaryResponse> {
  const res = await bwFetch(`/api/rds/summary`);
  if (!res.ok) throw new Error(`fetchRdsSummary failed: ${res.status}`);
  return (await res.json()) as RdsSummaryResponse;
}

export async function fetchRdsLive(db?: string): Promise<RdsLiveResponse> {
  const qs = db ? `?db=${encodeURIComponent(db)}` : "";
  const res = await bwFetch(`/api/rds/live${qs}`);
  if (!res.ok) throw new Error(`fetchRdsLive failed: ${res.status}`);
  return (await res.json()) as RdsLiveResponse;
}

export async function fetchRdsSessions(
  hours: number = 24, db?: string, user?: string,
): Promise<RdsSessionsResponse> {
  const parts = [`hours=${hours}`];
  if (db) parts.push(`db=${encodeURIComponent(db)}`);
  if (user) parts.push(`user=${encodeURIComponent(user)}`);
  const res = await bwFetch(`/api/rds/sessions?${parts.join("&")}`);
  if (!res.ok) throw new Error(`fetchRdsSessions failed: ${res.status}`);
  return (await res.json()) as RdsSessionsResponse;
}

export async function fetchRdsAuthFailures(
  hours: number = 24, db?: string,
): Promise<RdsAuthFailuresResponse> {
  const parts = [`hours=${hours}`];
  if (db) parts.push(`db=${encodeURIComponent(db)}`);
  const res = await bwFetch(`/api/rds/auth-failures?${parts.join("&")}`);
  if (!res.ok) throw new Error(`fetchRdsAuthFailures failed: ${res.status}`);
  return (await res.json()) as RdsAuthFailuresResponse;
}

// --- RDS Shape B --------------------------------------------------------

export async function fetchRdsProxySources(
  limit: number = 100,
): Promise<RdsProxySourcesResponse> {
  const res = await bwFetch(`/api/rds/proxy-sources?limit=${limit}`);
  if (!res.ok) throw new Error(`fetchRdsProxySources failed: ${res.status}`);
  return (await res.json()) as RdsProxySourcesResponse;
}

export async function fetchRdsShapeB(
  hours: number = 24,
): Promise<RdsShapeBResponse> {
  const res = await bwFetch(`/api/rds/shape-b?hours=${hours}`);
  if (!res.ok) throw new Error(`fetchRdsShapeB failed: ${res.status}`);
  return (await res.json()) as RdsShapeBResponse;
}

export async function fetchRdsAllowlist(): Promise<RdsAllowlistResponse> {
  const res = await bwFetch(`/api/rds/allowlist`);
  if (!res.ok) throw new Error(`fetchRdsAllowlist failed: ${res.status}`);
  return (await res.json()) as RdsAllowlistResponse;
}

// --- API Gateway --------------------------------------------------------

export async function fetchApiGwSummary(): Promise<ApiGwSummary> {
  const res = await bwFetch(`/api/api-gw/summary`);
  if (!res.ok) throw new Error(`fetchApiGwSummary failed: ${res.status}`);
  return (await res.json()) as ApiGwSummary;
}

export async function fetchApiGwApis(): Promise<ApiGwApisResponse> {
  const res = await bwFetch(`/api/api-gw/apis`);
  if (!res.ok) throw new Error(`fetchApiGwApis failed: ${res.status}`);
  return (await res.json()) as ApiGwApisResponse;
}

export async function fetchApiGwSources(
  limit: number = 100,
): Promise<ApiGwSourcesResponse> {
  const res = await bwFetch(`/api/api-gw/sources?limit=${limit}`);
  if (!res.ok) throw new Error(`fetchApiGwSources failed: ${res.status}`);
  return (await res.json()) as ApiGwSourcesResponse;
}

export async function fetchApiGwAlerts(
  hours: number = 24,
): Promise<ApiGwAlertsResponse> {
  const res = await bwFetch(`/api/api-gw/alerts?hours=${hours}`);
  if (!res.ok) throw new Error(`fetchApiGwAlerts failed: ${res.status}`);
  return (await res.json()) as ApiGwAlertsResponse;
}

export async function fetchApiGwFailures(
  hours: number = 24,
): Promise<ApiGwFailuresResponse> {
  const res = await bwFetch(`/api/api-gw/failures?hours=${hours}`);
  if (!res.ok) throw new Error(`fetchApiGwFailures failed: ${res.status}`);
  return (await res.json()) as ApiGwFailuresResponse;
}

// --- Live ping (called from the LiveCounter client component) -------------

export async function fetchLivePing(): Promise<LivePingResponse> {
  const res = await bwFetch(`/api/live/ping`);
  if (!res.ok) throw new Error(`fetchLivePing failed: ${res.status}`);
  return (await res.json()) as LivePingResponse;
}

// --- Overview ------------------------------------------------------------

export async function fetchOverview(): Promise<OverviewResponse> {
  const res = await bwFetch(`/api/overview`);
  if (!res.ok) throw new Error(`fetchOverview failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as OverviewResponse;
}

// --- Connectors ----------------------------------------------------------

export async function fetchConnectors(): Promise<ConnectorsListResponse> {
  const res = await bwFetch(`/api/connectors`);
  if (!res.ok) throw new Error(`fetchConnectors failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as ConnectorsListResponse;
}

// --- UEBA ----------------------------------------------------------------

export interface UebaBaselineRow {
  principal_type: string;
  principal_id: string;
  dimension: string;
  value: string;
  first_seen: number;
  last_seen: number;
  count: number;
}

export interface UebaBaselinesResponse {
  count: number;
  baselines: UebaBaselineRow[];
}

export interface UebaAnomaliesResponse {
  count: number;
  anomalies: EventEnvelope[];
}

export async function fetchUebaBaselines(query: {
  principal_type?: string;
  principal_id?: string;
  dimension?: string;
  limit?: number;
} = {}): Promise<UebaBaselinesResponse> {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    search.set(k, String(v));
  }
  const res = await bwFetch(`/api/ueba/baselines?${search.toString()}`);
  if (!res.ok) throw new Error(`fetchUebaBaselines failed: ${res.status}`);
  return (await res.json()) as UebaBaselinesResponse;
}

export async function fetchUebaAnomalies(query: {
  principal?: string;
  limit?: number;
} = {}): Promise<UebaAnomaliesResponse> {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    search.set(k, String(v));
  }
  const res = await bwFetch(`/api/ueba/anomalies?${search.toString()}`);
  if (!res.ok) throw new Error(`fetchUebaAnomalies failed: ${res.status}`);
  return (await res.json()) as UebaAnomaliesResponse;
}

export async function fetchConnector(id: string): Promise<Connector | null> {
  const res = await bwFetch(
    `/api/connectors/${encodeURIComponent(id)}`,
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`fetchConnector failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as Connector;
}
