export type ProviderStatus =
  | "success"
  | "not_configured"
  | "rate_limited"
  | "error";

export type IndicatorKind =
  | "domain"
  | "certificate"
  | "url"
  | "hash"
  | "event";

export interface IpIndicator {
  kind: IndicatorKind;
  value: string;
  source: string;
  relation: string;
}

export interface ProviderResult {
  id: string;
  label: string;
  status: ProviderStatus;
  source: string;
  message?: string;
  confidence?: number | null;
  reputation?: string | null;
  classification?: string | null;
  firstSeen?: string | null;
  lastSeen?: string | null;
  asn?: string | null;
  organization?: string | null;
  indicators?: IpIndicator[];
}

export interface IpApiResponse {
  status: "success" | "fail";
  message?: string;
  query?: string;
  country?: string;
  countryCode?: string;
  region?: string;
  regionName?: string;
  city?: string;
  zip?: string;
  lat?: number;
  lon?: number;
  timezone?: string;
  isp?: string;
  org?: string;
  as?: string;
  asname?: string;
  reverse?: string;
  mobile?: boolean;
  proxy?: boolean;
  hosting?: boolean;
}

export interface ObservedEventSummary {
  eventId: string;
  eventTime: string | null;
  action: string;
  module: string;
  severity: string | null;
  summary: string;
}

export interface IpLookupResponse extends IpApiResponse {
  providers: ProviderResult[];
  indicators: IpIndicator[];
  observedEvents: ObservedEventSummary[];
  investigationStatus: ProviderStatus;
  investigationMessage?: string;
}

const IPV4_PATTERN = /^(?:\d{1,3}\.){3}\d{1,3}$/;
const IPV6_PATTERN = /^[0-9a-f:]+$/i;
const HOSTNAME_PATTERN = /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i;
const URL_PATTERN = /\bhttps?:\/\/[^\s"'<>]+/gi;
const HASH_PATTERN = /\b[a-f0-9]{32}(?:[a-f0-9]{8}|[a-f0-9]{32})?\b/gi;
const DOMAIN_PATTERN = /\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\b/gi;

function isValidIpv4(value: string): boolean {
  return IPV4_PATTERN.test(value)
    && value.split(".").every((part) => Number(part) >= 0 && Number(part) <= 255);
}

function isValidIpv6(value: string): boolean {
  return value.includes(":")
    && IPV6_PATTERN.test(value)
    && value.split(":").length <= 8;
}

export function isValidObservable(value: string): boolean {
  const candidate = value.trim();
  if (!candidate || candidate.length > 253 || /[\s/\\?#%]/.test(candidate)) {
    return false;
  }
  return isValidIpv4(candidate) || isValidIpv6(candidate) || HOSTNAME_PATTERN.test(candidate);
}

export function isIpAddress(value: string): boolean {
  const candidate = value.trim();
  return isValidIpv4(candidate) || isValidIpv6(candidate);
}

export function normalizeProviderStatus(status: number): Exclude<ProviderStatus, "not_configured"> {
  if (status === 429) return "rate_limited";
  if (status >= 200 && status < 300) return "success";
  return "error";
}

function addIndicator(
  output: IpIndicator[],
  seen: Set<string>,
  kind: IndicatorKind,
  value: string,
  source: string,
  relation: string,
): void {
  const normalized = value.trim().replace(/[),.;]+$/, "");
  if (!normalized) return;
  const key = `${kind}:${normalized.toLowerCase()}`;
  if (seen.has(key)) return;
  seen.add(key);
  output.push({ kind, value: normalized, source, relation });
}

export function extractIndicators(
  values: unknown[],
  source: string,
  relation = "related observable",
): IpIndicator[] {
  const output: IpIndicator[] = [];
  const seen = new Set<string>();
  const visit = (value: unknown): void => {
    if (typeof value === "string") {
      for (const match of value.matchAll(URL_PATTERN)) {
        addIndicator(output, seen, "url", match[0], source, relation);
      }
      for (const match of value.matchAll(HASH_PATTERN)) {
        addIndicator(output, seen, "hash", match[0], source, relation);
      }
      for (const match of value.matchAll(DOMAIN_PATTERN)) {
        addIndicator(output, seen, "domain", match[0], source, relation);
      }
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value.slice(0, 100)) visit(item);
      return;
    }
    if (value && typeof value === "object") {
      for (const item of Object.values(value).slice(0, 100)) visit(item);
    }
  };
  for (const value of values.slice(0, 100)) visit(value);
  return output;
}
