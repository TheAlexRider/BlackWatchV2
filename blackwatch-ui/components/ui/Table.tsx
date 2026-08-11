"use client";

import clsx from "clsx";
import {
  Children,
  cloneElement,
  isValidElement,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import { ResizableTable } from "./ResizableTable";
import { TablePagination } from "./Pagination";

const DEFAULT_PAGE_SIZE = 25;

/** Canonical table wrapper. Every table gets the same responsive styling,
 * stable resize behavior, and pagination (25 rows per page by default). */
export function Table({
  tableId,
  children,
  className,
  ariaLabel,
  responsive = true,
}: {
  tableId?: string;
  children: ReactNode;
  className?: string;
  ariaLabel?: string;
  responsive?: boolean;
}) {
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
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
  const pageCount = Math.max(1, Math.ceil(dataRows.length / pageSize));

  useEffect(() => {
    setPage((current) => Math.min(current, pageCount - 1));
  }, [pageCount]);

  const visibleRows = useMemo(() => {
    const visible = new Set(
      dataRows.slice(page * pageSize, (page + 1) * pageSize),
    );
    return rows.filter((row) => {
      if (!isDataRow(row)) return true;
      const keep = visible.has(row);
      return keep;
    });
  }, [dataRows, page, pageSize, rows]);

  const paginatedParts = parts.slice();
  if (tbodyElement) {
    paginatedParts[tbodyIndex] = cloneElement(
      tbodyElement,
      undefined,
      visibleRows,
    );
  }

  return (
    <div className="min-w-0">
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
        onPageChange={setPage}
        onPageSizeChange={(size) => {
          setPageSize(size);
          setPage(0);
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
