import test from "node:test";
import assert from "node:assert/strict";

import {
  extractIndicators,
  isValidObservable,
  normalizeProviderStatus,
  type ProviderStatus,
} from "./ip-intelligence.ts";

test("accepts IP addresses and hostnames but rejects unsafe observables", () => {
  assert.equal(isValidObservable("8.8.8.8"), true);
  assert.equal(isValidObservable("2001:4860:4860::8888"), true);
  assert.equal(isValidObservable("dns.google"), true);
  assert.equal(isValidObservable("not a host"), false);
  assert.equal(isValidObservable("https://example.com/path"), false);
  assert.equal(isValidObservable("10.0.0.1;drop"), false);
});

test("maps provider responses to operator-visible states", () => {
  assert.equal(normalizeProviderStatus(200), "success");
  assert.equal(normalizeProviderStatus(429), "rate_limited");
  assert.equal(normalizeProviderStatus(503), "error");
});

test("extracts and deduplicates safe indicators with provenance", () => {
  const indicators = extractIndicators(
    [
      "https://example.com/login",
      "example.com",
      "sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "https://example.com/login",
    ],
    "test-provider",
  );

  assert.deepEqual(
    indicators.map(({ kind, value, source }) => ({ kind, value, source })),
    [
      { kind: "url", value: "https://example.com/login", source: "test-provider" },
      { kind: "domain", value: "example.com", source: "test-provider" },
      {
        kind: "hash",
        value: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        source: "test-provider",
      },
    ],
  );
});

const _providerStatusTypeCheck: ProviderStatus = "not_configured";
void _providerStatusTypeCheck;
