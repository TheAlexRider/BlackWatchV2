import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (relativePath: string) =>
  fs.readFileSync(path.join(root, relativePath), "utf8");

test("app shell keeps page overflow inside a shrinkable vertical content region", () => {
  const source = read("components/layout/AppShell.tsx");
  const css = read("app/globals.css");
  assert.match(source, /flex h-dvh min-w-0 .* flex-col overflow-hidden/);
  assert.match(source, /flex min-h-0 min-w-0 flex-1 overflow-hidden/);
  assert.match(source, /min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto/);
  assert.match(css, /html, body \{[\s\S]*overflow: hidden;/);
});

test("mobile card tables do not keep a desktop width or horizontal scrollbar", () => {
  const tableSource = read("components/ui/ResizableTable.tsx");
  const css = read("app/globals.css");
  assert.match(tableSource, /matchMedia\("\(max-width: 767px\)"\)/);
  assert.match(tableSource, /bw-table-shell-cards/);
  assert.match(css, /bw-table-shell-cards/);
  assert.match(css, /bw-col-resize-handle[^}]*display: none/s);
});

test("narrow table pagination can wrap its controls", () => {
  const source = read("components/ui/Pagination.tsx");
  assert.match(source, /flex w-full flex-wrap/);
  assert.match(source, /sm:w-auto/);
});

test("shared form rows and notification summary rows collapse on narrow screens", () => {
  const formRow = read("components/ui/FormRow.tsx");
  const keyValue = read("components/layout/KeyValueRow.tsx");
  const channelForm = read("components/domain/notifications/ChannelForm.tsx");
  const notifications = read("app/notifications/page.tsx");
  assert.match(formRow, /grid-cols-1[^\n]*sm:grid-cols-\[minmax\(140px,200px\)_minmax\(0,1fr\)\]/);
  assert.match(keyValue, /grid-cols-1[^\n]*sm:grid-cols-\[minmax\(140px,1fr\)_minmax\(0,2fr\)\]/);
  assert.match(channelForm, /grid-cols-1[^\n]*sm:grid-cols-\[minmax\(0,1fr\)_auto\]/);
  assert.match(notifications, /grid-cols-1[^\n]*sm:grid-cols-\[minmax\(0,1fr\)_220px_80px\]/);
});

test("responsive QA matrix covers the primary routes and target widths", () => {
  const guide = read("../docs/ui-responsive-qa.md");
  for (const width of [320, 375, 768, 1024, 1280, 1440]) {
    assert.match(guide, new RegExp(`\\b${width}px\\b`));
  }
  for (const route of ["Overview", "Services", "Events", "Notifications", "Rules", "Hosts detail", "Investigations", "Tools/IP lookup"]) {
    assert.match(guide, new RegExp(route.replace("/", "\\/")));
  }
  assert.match(guide, /document\.documentElement/);
  assert.match(guide, /scrollWidth > .*clientWidth/);
});
