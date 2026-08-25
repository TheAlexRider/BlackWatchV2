import {
  extractIndicators,
  isIpAddress,
  normalizeProviderStatus,
  type IpApiResponse,
  type IpIndicator,
  type IpLookupResponse,
  type ObservedEventSummary,
  type ProviderResult,
  type ProviderStatus,
} from "./ip-intelligence";

const IPAPI_SOURCE = "https://www.ip-api.com/";
const GREYNOISE_SOURCE = "https://docs.greynoise.io/reference/getcommunityip";
const ABUSEIPDB_SOURCE = "https://www.abuseipdb.com/api";
const VIRUSTOTAL_SOURCE = "https://docs.virustotal.com/reference/get-ip-address";
const CRT_SOURCE = "https://crt.sh/";
const LOCAL_FEEDS_SOURCE = "https://github.com/sharmaapoorva1/BlackWatchV2/blob/main/docs/threat-intel.md";
const CACHE_SECONDS = 15 * 60;
const REQUEST_TIMEOUT_MS = 8_000;

const IPAPI_FIELDS = [
  "status", "message", "query",
  "country", "countryCode",
  "region", "regionName", "city", "zip",
  "lat", "lon",
  "timezone",
  "isp", "org", "as", "asname",
  "reverse",
  "mobile", "proxy", "hosting",
].join(",");

type JsonRecord = Record<string, unknown>;

function record(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as JsonRecord
    : {};
}

function text(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function number(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return null;
}

function providerNotConfigured(
  id: string,
  label: string,
  source: string,
  message: string,
): ProviderResult {
  return { id, label, source, status: "not_configured", message };
}

function providerFailure(
  id: string,
  label: string,
  source: string,
  status: Exclude<ProviderStatus, "success" | "not_configured">,
  message: string,
): ProviderResult {
  return { id, label, source, status, message };
}

async function cachedJson(
  url: string,
  init: RequestInit = {},
): Promise<{ response: Response; payload: unknown }> {
  const shouldCache = init.cache !== "no-store";
  const response = await fetch(url, {
    ...init,
    signal: init.signal ?? AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    ...(shouldCache ? { next: { revalidate: CACHE_SECONDS } } : { cache: "no-store" }),
  } as RequestInit & { next: { revalidate: number } });
  const payload = await response.json().catch(() => null);
  return { response, payload };
}

function providerHttpFailure(
  id: string,
  label: string,
  source: string,
  response: Response,
): ProviderResult {
  const status = normalizeProviderStatus(response.status);
  const failureStatus = status === "rate_limited" ? "rate_limited" : "error";
  const message = status === "rate_limited"
    ? "Provider rate limit reached; try again later or configure a higher-quota key."
    : `Provider returned HTTP ${response.status}.`;
  return providerFailure(id, label, source, failureStatus, message);
}

function mergeIndicators(indicatorGroups: IpIndicator[][]): IpIndicator[] {
  const seen = new Set<string>();
  const output: IpIndicator[] = [];
  for (const group of indicatorGroups) {
    for (const indicator of group) {
      const key = `${indicator.kind}:${indicator.value.toLowerCase()}`;
      if (seen.has(key)) continue;
      seen.add(key);
      output.push(indicator);
    }
  }
  return output.slice(0, 200);
}

export async function fetchIpApi(observable: string): Promise<IpApiResponse> {
  const { response, payload } = await cachedJson(
    `http://ip-api.com/json/${encodeURIComponent(observable)}?fields=${IPAPI_FIELDS}`,
  );
  if (!response.ok) {
    return { status: "fail", message: `upstream HTTP ${response.status}` };
  }
  const data = record(payload);
  return {
    status: data.status === "success" ? "success" : "fail",
    message: text(data.message) ?? undefined,
    query: text(data.query) ?? undefined,
    country: text(data.country) ?? undefined,
    countryCode: text(data.countryCode) ?? undefined,
    region: text(data.region) ?? undefined,
    regionName: text(data.regionName) ?? undefined,
    city: text(data.city) ?? undefined,
    zip: text(data.zip) ?? undefined,
    lat: number(data.lat) ?? undefined,
    lon: number(data.lon) ?? undefined,
    timezone: text(data.timezone) ?? undefined,
    isp: text(data.isp) ?? undefined,
    org: text(data.org) ?? undefined,
    as: text(data.as) ?? undefined,
    asname: text(data.asname) ?? undefined,
    reverse: text(data.reverse) ?? undefined,
    mobile: data.mobile === true,
    proxy: data.proxy === true,
    hosting: data.hosting === true,
  };
}

async function fetchGreyNoise(ip: string): Promise<ProviderResult> {
  const key = process.env.GREYNOISE_API_KEY?.trim();
  const headers: HeadersInit = key ? { key } : {};
  try {
    const { response, payload } = await cachedJson(
      `https://api.greynoise.io/v3/community/${encodeURIComponent(ip)}`,
      { headers },
    );
    if (!response.ok) {
      const result = providerHttpFailure("greynoise", "GreyNoise Community", GREYNOISE_SOURCE, response);
      if (result.status === "rate_limited" && !key) {
        result.message = "Anonymous Community quota reached; add GREYNOISE_API_KEY for authenticated access.";
      }
      return result;
    }
    const data = record(payload);
    return {
      id: "greynoise",
      label: "GreyNoise Community",
      source: GREYNOISE_SOURCE,
      status: "success",
      message: key
        ? "Authenticated Community lookup."
        : "Anonymous Community lookup; quota is limited.",
      reputation: text(data.noise) ?? text(data.riot) ?? null,
      classification: text(data.classification) ?? text(data.name) ?? null,
      firstSeen: text(data.first_seen) ?? null,
      lastSeen: text(data.last_seen) ?? null,
      asn: text(data.asn) ?? null,
      organization: text(data.organization) ?? text(data.actors) ?? null,
      indicators: extractIndicators([data], "GreyNoise", "GreyNoise observation"),
    };
  } catch {
    return providerFailure("greynoise", "GreyNoise Community", GREYNOISE_SOURCE, "error", "Request failed or timed out.");
  }
}

async function fetchAbuseIpDb(ip: string): Promise<ProviderResult> {
  const key = process.env.ABUSEIPDB_API_KEY?.trim();
  if (!key) {
    return providerNotConfigured(
      "abuseipdb",
      "AbuseIPDB",
      ABUSEIPDB_SOURCE,
      "Optional: configure ABUSEIPDB_API_KEY for free-account checks.",
    );
  }
  try {
    const { response, payload } = await cachedJson(
      `https://api.abuseipdb.com/api/v2/check?ipAddress=${encodeURIComponent(ip)}&maxAgeInDays=90`,
      { headers: { Key: key, Accept: "application/json" } },
    );
    if (!response.ok) return providerHttpFailure("abuseipdb", "AbuseIPDB", ABUSEIPDB_SOURCE, response);
    const data = record(record(payload).data);
    const confidence = number(data.abuseConfidenceScore);
    return {
      id: "abuseipdb",
      label: "AbuseIPDB",
      source: ABUSEIPDB_SOURCE,
      status: "success",
      message: "Free-account check; quota is account-limited.",
      reputation: confidence === null ? null : `${confidence}% abuse confidence`,
      confidence,
      classification: text(data.usageType) ?? null,
      lastSeen: text(data.lastReportedAt) ?? null,
      asn: text(data.asn) ?? null,
      organization: text(data.isp) ?? text(data.domain) ?? null,
      indicators: extractIndicators([data.domain, data.isp], "AbuseIPDB", "reported network context"),
    };
  } catch {
    return providerFailure("abuseipdb", "AbuseIPDB", ABUSEIPDB_SOURCE, "error", "Request failed or timed out.");
  }
}

async function fetchVirusTotal(ip: string): Promise<ProviderResult> {
  const key = process.env.VIRUSTOTAL_API_KEY?.trim();
  if (!key) {
    return providerNotConfigured(
      "virustotal",
      "VirusTotal",
      VIRUSTOTAL_SOURCE,
      "Optional: configure VIRUSTOTAL_API_KEY for registered public-API lookups.",
    );
  }
  try {
    const { response, payload } = await cachedJson(
      `https://www.virustotal.com/api/v3/ip_addresses/${encodeURIComponent(ip)}`,
      { headers: { "x-apikey": key, Accept: "application/json" } },
    );
    if (!response.ok) return providerHttpFailure("virustotal", "VirusTotal", VIRUSTOTAL_SOURCE, response);
    const data = record(record(payload).data);
    const attributes = record(data.attributes);
    const analysis = record(attributes.last_analysis_stats);
    const malicious = number(analysis.malicious) ?? 0;
    const suspicious = number(analysis.suspicious) ?? 0;
    return {
      id: "virustotal",
      label: "VirusTotal",
      source: VIRUSTOTAL_SOURCE,
      status: "success",
      message: "Public API result; usage terms and quotas apply.",
      reputation: text(attributes.reputation) ?? `${malicious} malicious / ${suspicious} suspicious engines`,
      confidence: malicious + suspicious > 0 ? Math.min(100, malicious * 10 + suspicious * 5) : null,
      classification: text(attributes.type_description) ?? null,
      firstSeen: text(attributes.creation_date) ?? null,
      lastSeen: text(attributes.last_modification_date) ?? null,
      asn: text(attributes.asn) ?? null,
      organization: text(attributes.as_owner) ?? null,
      indicators: extractIndicators([attributes, record(payload).meta], "VirusTotal", "VirusTotal relationship"),
    };
  } catch {
    return providerFailure("virustotal", "VirusTotal", VIRUSTOTAL_SOURCE, "error", "Request failed or timed out.");
  }
}

async function fetchCertificateTransparency(reverse: string | undefined): Promise<ProviderResult> {
  const domain = reverse?.replace(/^\*\./, "").trim().toLowerCase();
  if (!domain || domain.split(".").length < 2) {
    return providerNotConfigured(
      "crtsh",
      "Certificate Transparency",
      CRT_SOURCE,
      "No reverse-DNS domain was available for a certificate pivot.",
    );
  }
  try {
    const { response, payload } = await cachedJson(
      `https://crt.sh/?q=${encodeURIComponent(`%.${domain}`)}&output=json`,
    );
    if (!response.ok) return providerHttpFailure("crtsh", "Certificate Transparency", CRT_SOURCE, response);
    const rows = Array.isArray(payload) ? payload.slice(0, 50).map(record) : [];
    const indicators: IpIndicator[] = [];
    const seen = new Set<string>();
    for (const row of rows) {
      const id = text(row.id);
      if (id) {
        const value = `crt.sh#${id}`;
        if (!seen.has(value)) {
          seen.add(value);
          indicators.push({ kind: "certificate", value, source: "crt.sh", relation: "certificate transparency record" });
        }
      }
    }
    return {
      id: "crtsh",
      label: "Certificate Transparency",
      source: CRT_SOURCE,
      status: "success",
      message: `${rows.length} certificate records found for ${domain}.`,
      indicators: mergeIndicators([indicators, extractIndicators(rows.map((row) => row.name_value), "crt.sh", "certificate name")]),
    };
  } catch {
    return providerFailure("crtsh", "Certificate Transparency", CRT_SOURCE, "error", "Certificate search failed or timed out.");
  }
}

function summarizeEvent(event: JsonRecord): ObservedEventSummary | null {
  const eventId = text(event.event_id);
  if (!eventId) return null;
  const source = record(event.source);
  const extra = record(event.extra);
  const action = text(event.action) ?? "event";
  const summary = text(extra.message) ?? text(extra.reason) ?? action;
  return {
    eventId,
    eventTime: text(event.event_time),
    action,
    module: text(source.module) ?? "unknown",
    severity: text(event.severity),
    summary,
  };
}

async function fetchObservedEvents(
  ip: string,
  request: Request,
): Promise<{ status: ProviderStatus; message?: string; events: ObservedEventSummary[]; indicators: IpIndicator[] }> {
  const base = process.env.BW_API_URL ?? "http://localhost:8000";
  const cookie = request.headers.get("cookie");
  try {
    const { response, payload } = await cachedJson(
      `${base}/api/events?q=${encodeURIComponent(ip)}&limit=100`,
      cookie ? { headers: { cookie }, cache: "no-store" } : { cache: "no-store" },
    );
    if (!response.ok) {
      return {
        status: response.status === 429 ? "rate_limited" : "error",
        message: response.status === 401 ? "Sign in to view matching BlackWatch events." : `BlackWatch events returned HTTP ${response.status}.`,
        events: [],
        indicators: [],
      };
    }
    const rawRows = record(payload).events;
    const rows: unknown[] = Array.isArray(rawRows) ? rawRows.slice(0, 100) : [];
    const events = rows.map(record).map(summarizeEvent).filter((value): value is ObservedEventSummary => value !== null).slice(0, 100);
    const eventIndicators = events.map((event) => ({
      kind: "event" as const,
      value: event.eventId,
      source: "BlackWatch events",
      relation: `observed ${event.action}`,
    }));
    const contextIndicators = extractIndicators(rows, "BlackWatch events", "observed event context");
    return { status: "success", message: `${events.length} matching event${events.length === 1 ? "" : "s"}.`, events, indicators: mergeIndicators([eventIndicators, contextIndicators]) };
  } catch {
    return { status: "error", message: "BlackWatch event pivot failed or timed out.", events: [], indicators: [] };
  }
}

async function fetchLocalIntel(ip: string, request: Request): Promise<ProviderResult> {
  const base = process.env.BW_API_URL ?? "http://localhost:8000";
  const cookie = request.headers.get("cookie");
  try {
    const { response, payload } = await cachedJson(
      `${base}/api/intel/lookup?ip=${encodeURIComponent(ip)}`,
      cookie ? { headers: { cookie }, cache: "no-store" } : { cache: "no-store" },
    );
    if (!response.ok) {
      return providerFailure("local-feeds", "BlackWatch local feeds", LOCAL_FEEDS_SOURCE, "error", "Local feed lookup is unavailable.");
    }
    const intel = record(record(payload).intel);
    const feeds = Array.isArray(intel.feeds)
      ? intel.feeds.filter((value): value is string => typeof value === "string")
      : [];
    const isTor = intel.is_tor === true;
    return {
      id: "local-feeds",
      label: "BlackWatch local feeds",
      source: LOCAL_FEEDS_SOURCE,
      status: "success",
      message: feeds.length > 0
        ? `Matched: ${feeds.join(", ")}${isTor ? " · Tor exit" : ""}.`
        : isTor ? "Tor exit node match." : "No local feed match.",
      reputation: feeds.length > 0 ? "feed match" : "no match",
      classification: isTor ? "Tor exit node" : null,
    };
  } catch {
    return providerFailure("local-feeds", "BlackWatch local feeds", LOCAL_FEEDS_SOURCE, "error", "Local feed lookup failed or timed out.");
  }
}

export async function buildIpLookupResponse(
  observable: string,
  base: IpApiResponse,
  request: Request,
): Promise<IpLookupResponse> {
  if (base.status !== "success") {
    return { ...base, providers: [], indicators: [], observedEvents: [], investigationStatus: "error" };
  }

  const targetIp = base.query && isIpAddress(base.query)
    ? base.query
    : isIpAddress(observable) ? observable : null;
  const baseIndicators = extractIndicators([base.reverse], "ip-api.com", "reverse DNS");
  if (!targetIp) {
    return {
      ...base,
      providers: [await fetchCertificateTransparency(base.reverse)],
      indicators: baseIndicators,
      observedEvents: [],
      investigationStatus: "not_configured",
      investigationMessage: "Threat providers require a resolved IP address; the fast lookup result is still available.",
    };
  }

  const [localFeeds, greyNoise, abuseIpDb, virusTotal, certificates, observed] = await Promise.all([
    fetchLocalIntel(targetIp, request),
    fetchGreyNoise(targetIp),
    fetchAbuseIpDb(targetIp),
    fetchVirusTotal(targetIp),
    fetchCertificateTransparency(base.reverse),
    fetchObservedEvents(targetIp, request),
  ]);
  return {
    ...base,
    providers: [localFeeds, greyNoise, abuseIpDb, virusTotal, certificates],
    indicators: mergeIndicators([
      baseIndicators,
      ...[localFeeds, greyNoise, abuseIpDb, virusTotal, certificates].map((provider) => provider.indicators ?? []),
      observed.indicators,
    ]),
    observedEvents: observed.events,
    investigationStatus: observed.status,
    investigationMessage: observed.message,
  };
}

export { IPAPI_SOURCE };
