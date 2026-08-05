import clsx from "clsx";
import { ResizableTable } from "./ResizableTable";

/**
 * `<Table>` — the one canonical wrapper for every data table in the app.
 *
 * Consolidates three things every table should have:
 *   1. Consistent CSS via the global `.bw-table` class (headers, hairline
 *      column + row dividers, sticky headers, hover states, tabular nums).
 *   2. Drag-to-resize columns via ResizableTable (widths persist per
 *      `tableId` in localStorage).
 *   3. Horizontal scroll on narrow viewports via the surrounding
 *      DataPanel's `overflow-x-auto` — combined with `.bw-table`'s
 *      `min-width: max-content` this scrolls the columns without
 *      squishing them.
 *
 * Usage (server component — no `"use client"` required at the call site):
 *
 *   <Table tableId="hosts-list">
 *     <thead>
 *       <tr>
 *         <th style={{ width: 200 }}>Hostname</th>
 *         <th style={{ width: 140 }}>State</th>
 *         <th data-align="right" style={{ width: 140 }}>Last seen</th>
 *         <th data-actions />
 *       </tr>
 *     </thead>
 *     <tbody>
 *       {rows.map(r => (
 *         <tr key={r.id}>
 *           <td>{r.hostname}</td>
 *           <td>{r.state}</td>
 *           <td data-align="right">{r.lastSeen}</td>
 *           <td data-actions><Button size="sm">Edit</Button></td>
 *         </tr>
 *       ))}
 *     </tbody>
 *   </Table>
 *
 * Rules of thumb picked up from the four UI skills:
 *  - Give a stable, unique `tableId` — persists the resize state.
 *  - Set `width` via inline `style={{ width: N }}` on the <th> — that's
 *    what the ResizableTable seeds and what users adjust on drag.
 *  - Use `data-align="right"` for numeric columns to get tabular
 *    right-alignment without one-off classes.
 *  - Use `data-actions` for the trailing action column — the CSS shades
 *    it and adds a subtle left divider so the eye reads it as an anchor.
 */
export function Table({
  tableId,
  children,
  className,
  ariaLabel,
}: {
  /** Optional. Omit to auto-derive an id from the header labels. Pass an
   *  explicit id only when two tables share the same headers but should
   *  NOT share saved widths. */
  tableId?: string;
  children: React.ReactNode;
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <ResizableTable tableId={tableId}>
      <table
        className={clsx("bw-table text-sm", className)}
        aria-label={ariaLabel}
      >
        {children}
      </table>
    </ResizableTable>
  );
}

/**
 * `<TableEmpty>` — the standard empty-state row for tables. Renders one
 * <tr> containing a single <td> that spans every column. Callers pass
 * the column count they used in <thead>.
 */
export function TableEmpty({
  columns,
  children,
}: {
  columns: number;
  children: React.ReactNode;
}) {
  return (
    <tr>
      <td colSpan={columns} className="bw-empty">
        {children}
      </td>
    </tr>
  );
}
