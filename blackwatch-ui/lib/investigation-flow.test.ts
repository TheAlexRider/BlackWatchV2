import assert from "node:assert/strict";
import test from "node:test";

import {
  investigationDetailHref,
  investigationIpLookupHref,
  investigationStartHref,
} from "./investigation-flow.ts";

test("builds an investigation start link with an encoded IP", () => {
  assert.equal(
    investigationStartHref(" 2001:db8::1 "),
    "/investigations?ip=2001%3Adb8%3A%3A1",
  );
});

test("keeps the investigation list link clean when no IP is provided", () => {
  assert.equal(investigationStartHref(""), "/investigations");
});

test("builds an encoded investigation detail link", () => {
  assert.equal(
    investigationDetailHref("case/with spaces"),
    "/investigations/case%2Fwith%20spaces",
  );
});

test("builds the automatic IP intelligence request for an investigation", () => {
  assert.equal(
    investigationIpLookupHref(" 8.8.8.8 "),
    "/api/tools/ip-lookup?ip=8.8.8.8",
  );
});

test("uses investigations as the contextual destination for an IP action", () => {
  assert.equal(
    investigationStartHref("8.8.8.8"),
    "/investigations?ip=8.8.8.8",
  );
});
