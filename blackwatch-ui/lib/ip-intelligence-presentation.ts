import type {
  IpIndicator,
  IndicatorKind,
  ProviderResult,
  ProviderStatus,
} from "./ip-intelligence";

export type ProviderSeverity = "critical" | "medium" | "low" | "neutral";

export interface ProviderStatusPresentation {
  label: string;
  severity: ProviderSeverity;
}

export interface IndicatorGroup {
  kind: IndicatorKind;
  label: string;
  items: IpIndicator[];
}

const INDICATOR_LABELS: Record<IndicatorKind, string> = {
  domain: "Domains",
  certificate: "Certificates",
  url: "URLs",
  hash: "Hashes",
  event: "Events",
};

export function providerStatusPresentation(
  status: ProviderStatus,
): ProviderStatusPresentation {
  switch (status) {
    case "success":
      return { label: "Available", severity: "low" };
    case "not_configured":
      return { label: "Optional", severity: "neutral" };
    case "rate_limited":
      return { label: "Rate limited", severity: "medium" };
    case "error":
      return { label: "Unavailable", severity: "critical" };
  }
}

export function providerEvidence(provider: ProviderResult): string[] {
  return [
    provider.reputation,
    provider.classification,
    provider.confidence === null || provider.confidence === undefined
      ? null
      : `confidence: ${provider.confidence}%`,
    provider.asn ? `AS${provider.asn}` : null,
    provider.organization,
    provider.firstSeen ? `first seen: ${provider.firstSeen}` : null,
    provider.lastSeen ? `last seen: ${provider.lastSeen}` : null,
  ].filter((value): value is string => !!value);
}

export function groupIndicators(indicators: IpIndicator[]): IndicatorGroup[] {
  const groups: IndicatorGroup[] = [];
  const byKind = new Map<IndicatorKind, IndicatorGroup>();
  for (const indicator of indicators) {
    let group = byKind.get(indicator.kind);
    if (!group) {
      group = {
        kind: indicator.kind,
        label: INDICATOR_LABELS[indicator.kind],
        items: [],
      };
      byKind.set(indicator.kind, group);
      groups.push(group);
    }
    group.items.push(indicator);
  }
  return groups;
}

