# BlackWatch Cycle — responsive UI QA report

**Cycle:** 2026-08-25
**Trigger:** `BLACKWATCH CYCLE`
**Focus:** UI responsiveness, normal layout behavior, and elimination of nested scrollbars.
**HEAD inspected:** `a3b1a4813206264d8bed33855d2c0c249cd7737d`

## Findings

### QA-001 — Page and table scrolling overlap

**Severity:** high  **Confidence:** high

The first screenshot shows a wide data surface inside a scrolling main region;
the second shows a table scrollbar together with separate vertical scrollbars
and clipped content. This matches the current combination of
`AppShell`'s `main.overflow-auto` and `.bw-table-shell.overflow-x-auto`, with
additional `DataPanel.overflow-auto` surfaces on detail pages.

**Expected:** scrolling ownership is predictable: the page scrolls vertically;
a wide table may scroll horizontally in one bounded region; a log/JSON viewer
may scroll internally only when explicitly bounded.

### QA-002 — Resizable table dimensions defeat narrow-layout behavior

**Severity:** high  **Confidence:** high

`ResizableTable` writes inline table `width` and `minWidth` from the sum of
column widths. The mobile card rules in `globals.css` set their own width and
min-width, but inline styles win. Saved desktop column widths can therefore
reappear as a wide table on a small viewport. Injected resize handles also do
not belong in card mode.

### QA-003 — Fixed tracks and action groups are not consistently collapsible

**Severity:** high  **Confidence:** medium

The codebase contains fixed grid tracks and dense action groups in shared and
page-level components. Examples include `FormRow`'s `200px 1fr`, notification
summary rows, and table action cells. At narrow widths these can force clipping,
unexpected horizontal overflow, or controls that are only partly visible.

### QA-004 — Pagination is vulnerable at narrow widths

**Severity:** medium  **Confidence:** high

`TablePagination` wraps its outer row but keeps the select/page indicator/
buttons in a single non-wrapping inner flex group. It can exceed a narrow table
card or compete with the table's horizontal scroll region.

### QA-005 — Bounded inner scrolling needs a deliberate exception policy

**Severity:** medium  **Confidence:** high

Some bounded log, JSON, and host detail panels use `max-h-* overflow-auto` for
good reasons. The problem is that the same visual treatment is mixed with
ordinary data panels, so users cannot tell whether they are scrolling the page,
the table, or a log viewer. These regions need an explicit primitive or
documented class with accessible labeling and a test that prevents accidental
nesting.

## Suggested verification matrix

- Widths: 320, 375, 768, 1024, 1280, and 1440 CSS pixels.
- Routes: Overview, Services, Events, Notifications, Rules, Hosts detail,
  Investigations notebook, Tools/IP lookup, and at least one create/edit form.
- Verify: no viewport-wide horizontal scroll; sidebar/drawer behavior; table
  card mode; table horizontal scroll only when required; pagination reachability;
  long IDs/ARNs; modal height; keyboard focus; and intentional log/JSON scroll.
- Preserve: table sorting, column visibility, desktop resize persistence,
  pagination, and action buttons.

## Proposed task mapping

- BW-008 covers shell/container sizing and scroll ownership.
- BW-009 covers tables, mobile card mode, resize handles, and pagination.
- BW-010 covers fixed-width page layouts plus automated/static responsive QA.

## Cycle execution note

QA was started in parallel with R&D as required, but the delegated worker did
not return within the bounded window and was shut down. This report was
reconciled by the coordinator from direct repository evidence and the supplied
screenshots. No application files were changed during this cycle.
