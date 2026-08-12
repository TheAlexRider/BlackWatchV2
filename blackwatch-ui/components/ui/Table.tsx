"use client";

import clsx from "clsx";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import {
  Children,
  cloneElement,
  isValidElement,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
  useId,
} from "react";
import { ResizableTable } from "./ResizableTable";
import { TablePagination } from "./Pagination";
import { LiveRegion } from "./LiveRegion";
import {
  DEFAULT_TABLE_PAGE_SIZE,
  TABLE_PAGE_SIZE_EVENT,
  readTablePageSize,
} from "./TablePreferences";


/** Canonical table wrapper. Every table gets the same responsive styling,
 * stable resize behavior, and pagination (25 rows per page by default). */
export function Table({
  tableId,
  children,
  className,
  ariaLabel,
  responsive = true,
  sortable = true,
}: {
  tableId?: string;
  children: ReactNode;
  className?: string;
  ariaLabel?: string;
  responsive?: boolean;
  sortable?: boolean;
}) {
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(DEFAULT_TABLE_PAGE_SIZE);
  const [sortColumn, setSortColumn] = useState<number | null>(null);
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [liveMessage, setLiveMessage] = useState("");
  const tableInstanceId = useId().replace(/:/g, "");
  const [hiddenColumns, setHiddenColumns] = useState<number[]>([]);
  const [columnVisibilityHydrated, setColumnVisibilityHydrated] = useState(false);
  const parts = Children.toArray(children);
  const tbodyIndex = parts.findIndex(
    (child) => isValidElement(child) && child.type === "tbody",
  );
  const tbody = tbodyIndex >= 0 ? parts[tbodyIndex] : null;
  const tbodyElement = tbody && isValidElement(tbody)
    ? (tbody as ReactElement<{ children?: ReactNode }>)
    : null;
  const rows = tbodyElement
    ? Children.toArray(tbodyElement.props.children)
    : [];
  const dataRows = rows.filter((row) => isDataRow(row));
  const sortedRows = useMemo(() => {
    if (!sortable || sortColumn === null) return dataRows;
    return [...dataRows].sort((left, right) => {
      const comparison = compareCellValues(
        cellText(left, sortColumn),
        cellText(right, sortColumn),
      );
      return sortDirection === "asc" ? comparison : -comparison;
    });
  }, [dataRows, sortColumn, sortDirection, sortable]);
  const pageCount = Math.max(1, Math.ceil(sortedRows.length / pageSize));

  useEffect(() => {
    setPage((current) => Math.min(current, pageCount - 1));
  }, [pageCount]);

  useEffect(() => {
    const applyDefault = () => {
      setPageSize(readTablePageSize());
      setPage(0);
    };
    applyDefault();
    window.addEventListener(TABLE_PAGE_SIZE_EVENT, applyDefault);
    return () => window.removeEventListener(TABLE_PAGE_SIZE_EVENT, applyDefault);
  }, []);

  const visibleRows = useMemo(() => {
    const visible = new Set(
      sortedRows.slice(page * pageSize, (page + 1) * pageSize),
    );
    return rows.filter((row) => {
      if (!isDataRow(row)) return true;
      const keep = visible.has(row);
      return keep;
    });
  }, [page, pageSize, rows, sortedRows]);

  const paginatedParts = parts.slice();
  const theadIndex = paginatedParts.findIndex((child) => isValidElement(child) && child.type === "thead");
  const thead = theadIndex >= 0 && isValidElement(paginatedParts[theadIndex])
    ? paginatedParts[theadIndex] as ReactElement<{ children?: ReactNode }>
    : null;
  const columnLabels = thead ? readColumnLabels(thead) : [];
  const hiddenColumnSet = useMemo(() => new Set(hiddenColumns), [hiddenColumns]);
  const columnStorageKey = `bw-column-visibility-v1-${tableId ?? `auto-${tableInstanceId}`}`;

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(columnStorageKey);
      const parsed = raw ? JSON.parse(raw) : [];
      if (Array.isArray(parsed)) {
        setHiddenColumns(parsed.filter((index): index is number =>
          Number.isInteger(index) && index >= 0 && index < columnLabels.length,
        ));
      }
    } catch {
      // Storage can be unavailable in private browsing.
    }
    setColumnVisibilityHydrated(true);
  }, [columnStorageKey, columnLabels.length]);

  useEffect(() => {
    if (!columnVisibilityHydrated) return;
    try {
      window.localStorage.setItem(columnStorageKey, JSON.stringify(hiddenColumns));
    } catch {
      // Storage can be unavailable in private browsing.
    }
  }, [columnStorageKey, columnVisibilityHydrated, hiddenColumns]);

  const toggleColumn = (index: number) => {
    setHiddenColumns((current) => {
      const next = current.includes(index)
        ? current.filter((value) => value !== index)
        : [...current, index].sort((a, b) => a - b);
      setLiveMessage(`${columnLabels[index] ?? "Column"} ${next.includes(index) ? "hidden" : "shown"}.`);
      return next;
    });
  };

  const visibleThead = thead
    ? hideColumnsInSection(thead, hiddenColumnSet)
    : null;
  if (sortable && thead) {
    paginatedParts[theadIndex] = enhanceHead(visibleThead ?? thead, sortColumn, sortDirection, (index, label, direction) => {
      setPage(0);
      setSortColumn(index);
      setSortDirection(direction);
      setLiveMessage(`${label} sorted ${direction === "asc" ? "ascending" : "descending"}.`);
    });
  }
  if (tbodyElement) {
    paginatedParts[tbodyIndex] = cloneElement(
      tbodyElement,
      undefined,
      visibleRows.map((row) => hideColumnsInRow(row, hiddenColumnSet)),
    );
  }

  return (
    <div className="min-w-0">
      <LiveRegion message={liveMessage} />
      {columnLabels.length > 1 && (
        <div className="mb-2 flex justify-end">
          <details className="relative">
            <summary className="cursor-pointer list-none rounded border border-line-soft px-2.5 py-1 text-[10px] uppercase tracking-wider text-fg-muted transition-colors hover:border-signal hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal">
              Columns
            </summary>
            <div className="absolute right-0 z-20 mt-1 min-w-48 border border-line bg-surface-2 p-2 shadow-lg">
              <p className="mb-2 text-[10px] uppercase tracking-wider text-fg-subtle">Visible columns</p>
              <div className="space-y-1">
                {columnLabels.map((column, index) => (
                  <label key={`${column.label}-${index}`} className="flex items-center gap-2 px-1 py-1 text-xs text-fg hover:bg-surface-1">
                    <input
                      type="checkbox"
                      checked={!hiddenColumnSet.has(index)}
                      disabled={column.isActions}
                      onChange={() => toggleColumn(index)}
                      className="h-3.5 w-3.5 accent-[var(--color-signal)]"
                    />
                    <span className="min-w-0 truncate">{column.label}</span>
                  </label>
                ))}
              </div>
              <button
                type="button"
                onClick={() => {
                  setHiddenColumns([]);
                  setSortColumn(null);
                  setLiveMessage("All columns restored.");
                }}
                className="mt-2 w-full border-t border-line-soft pt-2 text-left text-[10px] uppercase tracking-wider text-fg-muted transition-colors hover:text-signal focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal"
              >
                Reset columns
              </button>
            </div>
          </details>
        </div>
      )}
      <ResizableTable tableId={tableId}>
        <table
          className={clsx("bw-table text-sm", className)}
          data-responsive={responsive ? "cards" : "scroll"}
          aria-label={ariaLabel}
        >
          {paginatedParts}
        </table>
      </ResizableTable>
      <TablePagination
        page={page}
        pageSize={pageSize}
        total={dataRows.length}
        onPageChange={(nextPage) => {
          setPage(nextPage);
          setLiveMessage(`Showing page ${nextPage + 1} of ${pageCount}.`);
        }}
        onPageSizeChange={(size) => {
          setPageSize(size);
          setPage(0);
          setLiveMessage(`Showing ${size} rows per page.`);
        }}
      />
    </div>
  );
}

function isDataRow(row: ReactNode): row is ReactElement {
  if (!isValidElement(row) || row.type !== "tr") return false;
  const children = Children.toArray(
    (row as ReactElement<{ children?: ReactNode }>).props.children,
  );
  return !children.some(
    (cell) =>
      isValidElement(cell) &&
      (cell as ReactElement<{ colSpan?: number }>).props.colSpan,
  );
}

function cellText(row: ReactElement, column: number): string {
  const cells = Children.toArray((row.props as { children?: ReactNode }).children);
  return nodeText(cells[column]);
}

function readColumnLabels(thead: ReactElement<{ children?: ReactNode }>) {
  const firstRow = Children.toArray(thead.props.children).find(
    (row) => isValidElement(row) && row.type === "tr",
  );
  if (!isValidElement(firstRow)) return [];
  return Children.toArray((firstRow.props as { children?: ReactNode }).children)
    .map((cell, index) => {
      if (!isValidElement(cell) || cell.type !== "th") {
        return { index, label: `Column ${index + 1}`, isActions: false };
      }
      const props = cell.props as { children?: ReactNode; "data-actions"?: boolean };
      return {
        index,
        label: nodeText(props.children).trim() || `Column ${index + 1}`,
        isActions: Boolean(props["data-actions"]),
      };
    });
}

function hideColumnsInSection(
  section: ReactElement<{ children?: ReactNode }>,
  hidden: Set<number>,
) {
  if (hidden.size === 0) return section;
  const rows = Children.toArray(section.props.children).map((row) => {
    if (!isValidElement(row) || row.type !== "tr") return row;
    return hideColumnsInRow(row, hidden);
  });
  return cloneElement(section, undefined, rows);
}

function hideColumnsInRow(row: ReactNode, hidden: Set<number>): ReactNode {
  if (!isValidElement(row) || row.type !== "tr" || hidden.size === 0) return row;
  const cells = Children.toArray((row.props as { children?: ReactNode }).children);
  if (cells.some((cell) => isValidElement(cell) && (cell.props as { colSpan?: number }).colSpan)) return row;
  return cloneElement(row as ReactElement<{ children?: ReactNode }>, undefined,
    cells.filter((_, index) => !hidden.has(index)),
  );
}

function nodeText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join(" ");
  if (isValidElement(node)) {
    const props = node.props as {
      children?: ReactNode;
      value?: ReactNode;
      label?: ReactNode;
      name?: ReactNode;
      title?: ReactNode;
      severity?: ReactNode;
      status?: ReactNode;
      id?: ReactNode;
    };
    if (props.children !== undefined) return nodeText(props.children);
    for (const value of [props.value, props.label, props.name, props.title, props.severity, props.status, props.id]) {
      if (value !== undefined && value !== null) return nodeText(value);
    }
  }
  return "";
}

function enhanceHead(
  thead: ReactElement<{ children?: ReactNode }>,
  sortColumn: number | null,
  sortDirection: "asc" | "desc",
  onSort: (column: number, label: string, direction: "asc" | "desc") => void,
) {
  const rows = Children.toArray(thead.props.children);
  const headRows = rows.map((row) => {
    if (!isValidElement(row) || row.type !== "tr") return row;
    const cells = Children.toArray((row.props as { children?: ReactNode }).children);
    return cloneElement(row as ReactElement<{ children?: ReactNode }>, undefined, cells.map((cell, index) => {
      if (!isValidElement(cell) || cell.type !== "th") return cell;
      const label = nodeText((cell.props as { children?: ReactNode }).children).trim();
      const isActionsColumn = Boolean((cell.props as { "data-actions"?: boolean })["data-actions"]);
      if (isActionsColumn || !label || hasInteractiveChild((cell.props as { children?: ReactNode }).children)) return cell;
      const active = sortColumn === index;
      const nextDirection = active && sortDirection === "asc" ? "desc" : "asc";
      const SortIcon = active ? (sortDirection === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
      return cloneElement(cell as ReactElement<{ children?: ReactNode; "aria-sort"?: "none" | "ascending" | "descending" }>, {
        "aria-sort": active ? (sortDirection === "asc" ? "ascending" : "descending") : "none",
      }, <button type="button" onClick={() => onSort(index, label, nextDirection)} aria-label={`Sort ${label} ${active ? ` ${nextDirection}` : ""}`} title={`Sort by ${label}`} className="inline-flex w-full items-center justify-between gap-2 text-left text-inherit focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal"><span>{(cell.props as { children?: ReactNode }).children}</span><SortIcon size={13} aria-hidden="true" className={active ? "text-signal" : "text-fg-subtle"} /></button>);
    }));
  });
  return cloneElement(thead, undefined, headRows);
}

function compareCellValues(left: string, right: string): number {
  const a = left.trim();
  const b = right.trim();
  if (!a && !b) return 0;
  if (!a) return 1;
  if (!b) return -1;

  const numericPattern = /^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:\s*(?:kb|mb|gb|tb|%))?$/i;
  const numericA = numericPattern.test(a) ? Number.parseFloat(a) : Number.NaN;
  const numericB = numericPattern.test(b) ? Number.parseFloat(b) : Number.NaN;
  if (Number.isFinite(numericA) && Number.isFinite(numericB)) return numericA - numericB;

  const dateA = Date.parse(a);
  const dateB = Date.parse(b);
  const looksLikeDate = /\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}/;
  if (looksLikeDate.test(a) && looksLikeDate.test(b) && Number.isFinite(dateA) && Number.isFinite(dateB)) {
    return dateA - dateB;
  }

  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

function hasInteractiveChild(node: ReactNode): boolean {
  if (!isValidElement(node)) return false;
  if (node.type === "button" || node.type === "a") return true;
  return hasInteractiveChild((node.props as { children?: ReactNode }).children);
}

export function TableEmpty({
  columns,
  children,
}: {
  columns: number;
  children: ReactNode;
}) {
  return (
    <tr data-empty="true">
      <td colSpan={columns} className="bw-empty">
        {children}
      </td>
    </tr>
  );
}
