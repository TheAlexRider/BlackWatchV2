import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import { ROUTE_MANIFEST } from "./route-manifest.ts";

const root = process.cwd();
const read = (relativePath: string) => fs.readFileSync(path.join(root, relativePath), "utf8");

test("notification compatibility routes point to canonical destinations", () => {
  const rules = read("app/notifications/rules/[id]/page.tsx");
  const routing = read("app/notifications/routing/page.tsx");
  const quick = read("app/notifications/perf-alerts/quick/page.tsx");
  assert.match(rules, /redirect\(`\/notifications\/rules\/\$\{encodeURIComponent\(id\)\}\/edit`\)/);
  assert.match(routing, /redirect\("\/notifications"\)/);
  assert.match(quick, /redirect\("\/notifications"\)/);
});

test("manifest has one canonical notification landing route", () => {
  const canonical = ROUTE_MANIFEST.filter((entry) => entry.kind === "canonical" && entry.path === "/notifications");
  assert.equal(canonical.length, 1);
  for (const entry of ROUTE_MANIFEST.filter((item) => item.kind === "compatibility")) {
    assert.ok(entry.destination, `${entry.path} needs a compatibility destination`);
  }
});

test("internal notification links do not target retired landing routes", () => {
  const sourceFiles = [
    "app/notifications/page.tsx",
    "app/notifications/create/page.tsx",
    "app/notifications/AlertWizard.tsx",
    "components/domain/notifications/RulePresets.tsx",
  ];
  for (const file of sourceFiles) {
    const source = read(file);
    assert.doesNotMatch(source, /\/notifications\/(routing|perf-alerts\/quick)/);
  }
});

test("contextual IP actions prefer investigations while keeping the tool secondary", () => {
  const ipCell = read("components/domain/IpCell.tsx");
  const modal = read("components/domain/IpLookupModal.tsx");
  const notebook = read("app/investigations/InvestigationNotebook.tsx");
  assert.match(ipCell, /investigationStartHref\(value\)/);
  assert.match(modal, /href=\{investigationStartHref\(ip\)\}/);
  assert.match(notebook, /<InvestigationIpIntelligence ip=\{ip\} \/>/);
});
