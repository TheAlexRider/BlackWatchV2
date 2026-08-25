export function investigationStartHref(ip?: string): string {
  const value = ip?.trim();
  return value
    ? `/investigations?ip=${encodeURIComponent(value)}`
    : "/investigations";
}

export function investigationDetailHref(id: string): string {
  return `/investigations/${encodeURIComponent(id)}`;
}

export function investigationIpLookupHref(ip: string): string {
  return `/api/tools/ip-lookup?ip=${encodeURIComponent(ip.trim())}`;
}
