"use client";

import { useEffect, useState } from "react";

export const TABLE_PAGE_SIZE_KEY = "bw.table.defaultPageSize";
export const TABLE_PAGE_SIZE_EVENT = "bw:table-page-size";
export const TABLE_PAGE_SIZES = [10, 25, 50, 100] as const;
export const DEFAULT_TABLE_PAGE_SIZE = 25;

export function readTablePageSize(): number {
  try {
    const value = Number(localStorage.getItem(TABLE_PAGE_SIZE_KEY));
    return TABLE_PAGE_SIZES.includes(value as (typeof TABLE_PAGE_SIZES)[number])
      ? value
      : DEFAULT_TABLE_PAGE_SIZE;
  } catch {
    return DEFAULT_TABLE_PAGE_SIZE;
  }
}

export function TablePageSizeSetting() {
  const [value, setValue] = useState(DEFAULT_TABLE_PAGE_SIZE);

  useEffect(() => {
    setValue(readTablePageSize());
  }, []);

  function onChange(next: number) {
    setValue(next);
    try {
      localStorage.setItem(TABLE_PAGE_SIZE_KEY, String(next));
      window.dispatchEvent(new CustomEvent(TABLE_PAGE_SIZE_EVENT, { detail: next }));
    } catch {
      // Browser storage can be unavailable in private browsing.
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <p className="text-sm text-fg">Default table rows</p>
        <p className="mt-1 text-xs text-fg-muted">
          Applies to every table in this browser. You can still change an
          individual table temporarily from its footer.
        </p>
      </div>
      <label className="flex items-center gap-2 text-xs text-fg-muted">
        <span className="sr-only">Default rows per table</span>
        <select
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
          className="h-8 border border-line bg-surface-1 px-2 text-xs text-fg"
          aria-label="Default rows per table"
        >
          {TABLE_PAGE_SIZES.map((size) => (
            <option key={size} value={size}>{size} rows</option>
          ))}
        </select>
      </label>
    </div>
  );
}
