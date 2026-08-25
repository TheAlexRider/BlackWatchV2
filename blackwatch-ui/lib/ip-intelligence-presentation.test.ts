import test from "node:test";
import assert from "node:assert/strict";

import {
  groupIndicators,
  providerEvidence,
  providerStatusPresentation,
} from "./ip-intelligence-presentation.ts";

test("maps provider states to consistent operator language", () => {
  assert.deepEqual(providerStatusPresentation("success"), {
    label: "Available",
    severity: "low",
  });
  assert.deepEqual(providerStatusPresentation("not_configured"), {
    label: "Optional",
    severity: "neutral",
  });
  assert.deepEqual(providerStatusPresentation("rate_limited"), {
    label: "Rate limited",
    severity: "medium",
  });
});

test("turns provider fields into ordered evidence lines", () => {
  assert.deepEqual(
    providerEvidence({
      id: "abuseipdb",
      label: "AbuseIPDB",
      status: "success",
      source: "https://example.com",
      reputation: "0% abuse confidence",
      classification: "Fixed Line ISP",
      confidence: 0,
      asn: "7018",
      organization: "AT&T",
      lastSeen: "2026-08-25T00:00:00Z",
    }),
    [
      "0% abuse confidence",
      "Fixed Line ISP",
      "confidence: 0%",
      "AS7018",
      "AT&T",
      "last seen: 2026-08-25T00:00:00Z",
    ],
  );
});

test("groups investigation indicators without hiding their values", () => {
  const groups = groupIndicators([
    { kind: "domain", value: "example.com", source: "dns", relation: "reverse DNS" },
    { kind: "hash", value: "abc", source: "provider", relation: "related hash" },
    { kind: "domain", value: "example.org", source: "crt.sh", relation: "certificate name" },
  ]);

  assert.deepEqual(groups.map((group) => group.kind), ["domain", "hash"]);
  assert.deepEqual(groups[0].items.map((item) => item.value), ["example.com", "example.org"]);
});

