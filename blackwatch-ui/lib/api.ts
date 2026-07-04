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
  IamViewResponse,
  NotificationChannel,
  NotificationChannelsResponse,
  NotificationRule,
  NotificationRulesResponse,
  NotificationCardsResponse,
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
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`fetchEvents failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as EventsResponse;
}

export async function fetchEvent(eventId: string): Promise<EventEnvelope | null> {
  const url = `${API_BASE}/api/events/${encodeURIComponent(eventId)}`;
  const res = await fetch(url, { cache: "no-store" });
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
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`fetchPostureFindings failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as PostureFindingsResponse;
}

export async function fetchPostureFinding(
  findingId: string,
): Promise<PostureFinding | null> {
  const url = `${API_BASE}/api/posture/findings/${encodeURIComponent(findingId)}`;
  const res = await fetch(url, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`fetchPostureFinding failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as PostureFinding;
}

// --- Hosts ----------------------------------------------------------------

export async function fetchHosts(): Promise<HostsListResponse> {
  const res = await fetch(`${API_BASE}/api/hosts`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchHosts failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as HostsListResponse;
}

export async function fetchHostDetail(
  instanceId: string,
): Promise<HostDetailResponse> {
  const url = `${API_BASE}/api/hosts/${encodeURIComponent(instanceId)}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`fetchHostDetail failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as HostDetailResponse;
}

// --- File Integrity (FIM) -------------------------------------------------

export async function fetchFimView(): Promise<FimViewResponse> {
  const res = await fetch(`${API_BASE}/api/fim`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchFimView failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as FimViewResponse;
}

export async function fetchFimInstance(
  instanceId: string,
): Promise<FimInstanceResponse> {
  const url = `${API_BASE}/api/fim/${encodeURIComponent(instanceId)}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`fetchFimInstance failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as FimInstanceResponse;
}

// --- Performance alerts ---------------------------------------------------

export async function fetchPerfAlerts(): Promise<PerfAlertsListResponse> {
  const res = await fetch(`${API_BASE}/api/perf-alerts`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchPerfAlerts failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as PerfAlertsListResponse;
}

export async function fetchPerfAlert(ruleId: string): Promise<PerfAlertRule> {
  const url = `${API_BASE}/api/perf-alerts/${encodeURIComponent(ruleId)}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`fetchPerfAlert failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as PerfAlertRule;
}

// --- Services --------------------------------------------------------------

export async function fetchServices(): Promise<ServicesListResponse> {
  const res = await fetch(`${API_BASE}/api/services`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchServices failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as ServicesListResponse;
}

// --- Rules + noise -------------------------------------------------------

export async function fetchRules(): Promise<RulesResponse> {
  const res = await fetch(`${API_BASE}/api/rules`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchRules failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as RulesResponse;
}

// --- Buckets -------------------------------------------------------------

export async function fetchBuckets(): Promise<BucketsListResponse> {
  const res = await fetch(`${API_BASE}/api/buckets`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchBuckets failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as BucketsListResponse;
}

// --- Notifications -------------------------------------------------------

export async function fetchNotificationChannels(): Promise<NotificationChannelsResponse> {
  const res = await fetch(`${API_BASE}/api/notifications/channels`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchNotificationChannels failed: ${res.status}`);
  return (await res.json()) as NotificationChannelsResponse;
}

export async function fetchNotificationChannel(id: string): Promise<NotificationChannel | null> {
  const res = await fetch(
    `${API_BASE}/api/notifications/channels/${encodeURIComponent(id)}`,
    { cache: "no-store" },
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`fetchNotificationChannel failed: ${res.status}`);
  return (await res.json()) as NotificationChannel;
}

export async function fetchNotificationRules(): Promise<NotificationRulesResponse> {
  const res = await fetch(`${API_BASE}/api/notifications/rules`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchNotificationRules failed: ${res.status}`);
  return (await res.json()) as NotificationRulesResponse;
}

export async function fetchNotificationCards(): Promise<NotificationCardsResponse> {
  const res = await fetch(`${API_BASE}/api/notifications/cards`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchNotificationCards failed: ${res.status}`);
  return (await res.json()) as NotificationCardsResponse;
}

export async function fetchPerfQuick(): Promise<PerfQuickResponse> {
  const res = await fetch(`${API_BASE}/api/notifications/perf-alerts/quick`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`fetchPerfQuick failed: ${res.status}`);
  return (await res.json()) as PerfQuickResponse;
}

export async function fetchNotificationRule(id: string): Promise<NotificationRule | null> {
  const res = await fetch(
    `${API_BASE}/api/notifications/rules/${encodeURIComponent(id)}`,
    { cache: "no-store" },
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
  const res = await fetch(`${API_BASE}/api/notifications/log?${search}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchNotificationLog failed: ${res.status}`);
  return (await res.json()) as NotificationLogResponse;
}

export async function fetchNotificationAcks(): Promise<NotificationAcksResponse> {
  const res = await fetch(`${API_BASE}/api/notifications/acks`, { cache: "no-store" });
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
export async function fetchTemplatePresets(channelType: string): Promise<TemplatePreset[]> {
  const res = await fetch(
    `/api/notifications/templates?channel_type=${encodeURIComponent(channelType)}`,
    { cache: "no-store" },
  );
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
  | "rds_auth_failure";

export async function previewTemplate(
  template: string,
  opts?: {
    channelName?: string;
    channelType?: string;
    sampleEvent?: PreviewSampleKind;
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
    }),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`previewTemplate failed: ${res.status}`);
  return (await res.json()) as { rendered: string; error: string | null };
}

// --- IAM ------------------------------------------------------------------

export async function fetchIam(): Promise<IamViewResponse> {
  const res = await fetch(`${API_BASE}/api/iam`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchIam failed: ${res.status}`);
  return (await res.json()) as IamViewResponse;
}

// --- VPN ------------------------------------------------------------------

export async function fetchVpn(): Promise<VpnResponse> {
  const res = await fetch(`${API_BASE}/api/vpn`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchVpn failed: ${res.status}`);
  return (await res.json()) as VpnResponse;
}

// --- RDS ------------------------------------------------------------------

export async function fetchRds(): Promise<RdsViewResponse> {
  const res = await fetch(`${API_BASE}/api/rds`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchRds failed: ${res.status}`);
  return (await res.json()) as RdsViewResponse;
}

export async function fetchRdsSummary(): Promise<RdsSummaryResponse> {
  const res = await fetch(`${API_BASE}/api/rds/summary`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchRdsSummary failed: ${res.status}`);
  return (await res.json()) as RdsSummaryResponse;
}

export async function fetchRdsLive(db?: string): Promise<RdsLiveResponse> {
  const qs = db ? `?db=${encodeURIComponent(db)}` : "";
  const res = await fetch(`${API_BASE}/api/rds/live${qs}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchRdsLive failed: ${res.status}`);
  return (await res.json()) as RdsLiveResponse;
}

export async function fetchRdsSessions(
  hours: number = 24, db?: string, user?: string,
): Promise<RdsSessionsResponse> {
  const parts = [`hours=${hours}`];
  if (db) parts.push(`db=${encodeURIComponent(db)}`);
  if (user) parts.push(`user=${encodeURIComponent(user)}`);
  const res = await fetch(`${API_BASE}/api/rds/sessions?${parts.join("&")}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchRdsSessions failed: ${res.status}`);
  return (await res.json()) as RdsSessionsResponse;
}

export async function fetchRdsAuthFailures(
  hours: number = 24, db?: string,
): Promise<RdsAuthFailuresResponse> {
  const parts = [`hours=${hours}`];
  if (db) parts.push(`db=${encodeURIComponent(db)}`);
  const res = await fetch(`${API_BASE}/api/rds/auth-failures?${parts.join("&")}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchRdsAuthFailures failed: ${res.status}`);
  return (await res.json()) as RdsAuthFailuresResponse;
}

// --- Live ping (called from the LiveCounter client component) -------------

export async function fetchLivePing(): Promise<LivePingResponse> {
  const res = await fetch(`${API_BASE}/api/live/ping`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchLivePing failed: ${res.status}`);
  return (await res.json()) as LivePingResponse;
}

// --- Overview ------------------------------------------------------------

export async function fetchOverview(): Promise<OverviewResponse> {
  const res = await fetch(`${API_BASE}/api/overview`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchOverview failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as OverviewResponse;
}

// --- Connectors ----------------------------------------------------------

export async function fetchConnectors(): Promise<ConnectorsListResponse> {
  const res = await fetch(`${API_BASE}/api/connectors`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchConnectors failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as ConnectorsListResponse;
}

export async function fetchConnector(id: string): Promise<Connector | null> {
  const res = await fetch(
    `${API_BASE}/api/connectors/${encodeURIComponent(id)}`,
    { cache: "no-store" },
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`fetchConnector failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as Connector;
}
