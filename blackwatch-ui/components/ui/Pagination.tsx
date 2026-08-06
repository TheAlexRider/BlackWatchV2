"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "./Button";

export function TablePagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : page * pageSize + 1;
  const last = Math.min(total, (page + 1) * pageSize);

  return (
    <nav
      aria-label="Table pagination"
      className="flex flex-wrap items-center justify-between gap-3 border-t border-line-soft bg-surface-1 px-3 py-2.5 text-xs text-fg-muted"
    >
      <span aria-live="polite" className="font-mono text-[11px]">
        {first}–{last} <span className="text-fg-disabled">of</span> {total}
      </span>
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1.5">
          <span className="hidden sm:inline">Rows</span>
          <select
            aria-label="Rows per page"
            value={pageSize}
            onChange={(event) => onPageSizeChange(Number(event.target.value))}
            className="h-7 border border-line-soft bg-canvas px-1.5 text-xs text-fg"
          >
            {[10, 25, 50, 100].map((size) => (
              <option key={size} value={size}>{size}</option>
            ))}
          </select>
        </label>
        <span className="min-w-16 text-center font-mono text-[11px] text-fg-subtle">
          {page + 1} / {pageCount}
        </span>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          aria-label="Previous page"
          disabled={page === 0}
          onClick={() => onPageChange(Math.max(0, page - 1))}
        >
          <ChevronLeft size={14} aria-hidden="true" />
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          aria-label="Next page"
          disabled={page >= pageCount - 1}
          onClick={() => onPageChange(Math.min(pageCount - 1, page + 1))}
        >
          <ChevronRight size={14} aria-hidden="true" />
        </Button>
      </div>
    </nav>
  );
}
