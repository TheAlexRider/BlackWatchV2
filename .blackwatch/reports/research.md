# BlackWatch Cycle — responsive UI architecture review

**Cycle:** 2026-08-25
**Trigger:** `BLACKWATCH CYCLE`
**Focus:** UI responsiveness, normal layout behavior, and elimination of nested scrollbars.
**HEAD inspected:** `a3b1a4813206264d8bed33855d2c0c249cd7737d`

## Executive finding

The screenshots show a systemic overflow contract problem, not one broken page.
BlackWatch currently has several independent scrolling owners: the app shell's
`main`, the table shell, and selected data panels. Wide tables and fixed-width
controls can therefore create both page-level and component-level scrollbars,
while narrow layouts clip controls or push content outside the viewport.

## Evidence

- `blackwatch-ui/components/layout/AppShell.tsx`: the content region is
  `flex-1 overflow-auto`, but the flex item and its inner max-width wrapper do
  not explicitly establish `min-width: 0`. A wide descendant can enlarge the
  layout before the intended table scroll region owns the overflow.
- `blackwatch-ui/app/globals.css`: `.bw-table-shell` is always
  `overflow-x: auto` with vertical overflow visible. This is useful on desktop,
  but becomes a second scroll context when nested inside the scrolling app main
  or a panel with its own overflow.
- `blackwatch-ui/components/ui/ResizableTable.tsx`: every table receives
  inline pixel `width` and `minWidth` equal to the sum of saved column widths.
  The mobile card CSS in `globals.css` cannot reliably override those inline
  dimensions, so tables can retain a wide horizontal surface at narrow
  viewports even when `data-responsive="cards"` is enabled.
- `blackwatch-ui/components/ui/Pagination.tsx`: the control group is not
  independently allowed to wrap, and its fixed `min-w-16` page indicator plus
  select and buttons can exceed a narrow panel.
- `blackwatch-ui/components/ui/FormRow.tsx` and notification/dashboard views
  contain fixed grid tracks such as `200px 1fr`, `1fr 220px 80px`, and other
  non-collapsing desktop layouts. These need responsive fallbacks or a shared
  responsive field-row primitive.
- Several detail pages intentionally use `DataPanel` with `max-h-* overflow-auto`
  (`hosts/[id]`, event/detail and connector views). These should remain only
  where a bounded log/JSON viewport is intentional and should be visually
  identified as an inner scroll region.

## Recommended responsive model

1. The app shell owns vertical page scrolling. Every flex/grid ancestor between
   the shell and a data surface must be shrinkable (`min-w-0`, and
   `min-h-0` where a bounded vertical region is intentional).
2. A table owns horizontal scrolling on desktop only when it cannot become a
   readable card/list on mobile. It must not also own vertical scrolling unless
   the component explicitly declares a bounded log surface.
3. Mobile card mode must disable the resizable table's inline fixed widths and
   resize handles. Desktop column preferences must not force mobile overflow.
4. Fixed desktop grid tracks need a mobile stack or an adaptive minmax track.
   Controls should wrap as a group without widening their parent.
5. Each intentional inner scroll region needs a clear label/affordance and a
   regression check at representative widths.

## Proposed work

- BW-008: establish the shell/container overflow contract and eliminate page
  horizontal overflow caused by shrinkable flex/grid ancestors.
- BW-009: normalize table and pagination responsiveness, especially the
  interaction between `ResizableTable` inline widths and mobile card mode.
- BW-010: audit fixed-width layouts and add a responsive verification matrix
  for primary pages, tables, forms, dialogs, and intentional bounded logs.

All three are proposed only. No application files were changed during this
analysis cycle.

## Acceptance direction

At narrow, medium, and desktop widths, primary routes should have one clear
vertical page scroll context; no accidental horizontal viewport scroll; tables
should either fit, become cards, or expose one deliberate horizontal region;
pagination and actions must remain reachable; intentional JSON/log scrolling
must remain bounded and distinguishable. Existing desktop column resize and
data visibility behavior must be preserved.

## Cycle execution note

R&D was started in parallel with QA as required, but the delegated worker did
not produce a report within the bounded window and was shut down. This report
was reconciled by the coordinator from direct current-HEAD evidence.
