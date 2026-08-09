"use client";

import { useEffect, useRef } from "react";

const DEFAULT_MIN_COLUMN_WIDTH = 72;

/**
 * Adds stable, accessible column resizing to a semantic table.
 *
 * Widths are applied to a <colgroup>, rather than only to <th> elements. That
 * is important: the browser then has one source of truth for the entire
 * column, so a long cell cannot unexpectedly move the resize handle or make
 * neighbouring columns jump.
 */
export function ResizableTable({
  tableId,
  children,
  className,
  minColumnWidth = DEFAULT_MIN_COLUMN_WIDTH,
}: {
  tableId?: string;
  children: React.ReactNode;
  className?: string;
  minColumnWidth?: number;
}) {
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const wrapper = wrapperRef.current;
    const table = wrapper?.querySelector<HTMLTableElement>("table");
    if (!wrapper || !table) return;

    const headers = Array.from(
      table.querySelectorAll<HTMLTableCellElement>("thead th"),
    );
    if (headers.length === 0) return;

    const storageId = tableId
      ? tableId
      : `auto-${headers.length}-${hashString(
          headers.map((header) => header.textContent?.trim() ?? "").join("|"),
        )}`;
    const storageKey = `bw-cols-${storageId}`;
    const saved = readWidths(storageKey, minColumnWidth);
    const cleanups: Array<() => void> = [];

    // Create one <col> per header. Col widths are much more predictable than
    // mutating header widths when table-layout is fixed.
    const colgroup = document.createElement("colgroup");
    const columns = headers.map(() => document.createElement("col"));
    columns.forEach((column) => colgroup.appendChild(column));
    table.insertBefore(colgroup, table.firstChild);
    table.style.tableLayout = "fixed";

    const labels = headers.map((header, index) =>
      header.hasAttribute("data-actions")
        ? "Actions"
        : header.textContent?.trim() || `Column ${index + 1}`,
    );

    const initialWidths = headers.map((header, index) =>
      clamp(
        saved[index] ?? Math.round(header.getBoundingClientRect().width),
        minColumnWidth,
      ),
    );

    // Batch initial reads before writes to avoid layout thrashing.
    initialWidths.forEach((width, index) => setColumnWidth(columns[index], width, minColumnWidth));

    table.querySelectorAll<HTMLTableRowElement>("tbody tr").forEach((row) => {
      Array.from(row.children).forEach((cell, index) => {
        if (cell instanceof HTMLElement && !cell.dataset.label && labels[index]) {
          cell.dataset.label = labels[index];
        }
      });
    });

    const persist = () => {
      const widths = columns.map((column) => Math.round(column.getBoundingClientRect().width));
      try {
        localStorage.setItem(storageKey, JSON.stringify(widths));
      } catch {
        // Storage can be unavailable in private browsing.
      }
    };

    headers.forEach((header, index) => {
      const handle = document.createElement("button");
      handle.type = "button";
      handle.className = "bw-col-resize-handle";
      handle.setAttribute("aria-label", `Resize ${labels[index]} column`);
      handle.setAttribute("aria-keyshortcuts", "ArrowLeft ArrowRight");
      handle.title = "Drag to resize. Use arrow keys for precision.";

      let startX = 0;
      let startWidth = 0;
      let activePointerId: number | null = null;

      const onPointerMove = (event: PointerEvent) => {
        if (activePointerId !== event.pointerId) return;
        setColumnWidth(columns[index], startWidth + event.clientX - startX, minColumnWidth);
      };

      const onPointerUp = (event: PointerEvent) => {
        if (activePointerId !== event.pointerId) return;
        activePointerId = null;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", onPointerUp);
        persist();
      };

      const onPointerDown = (event: PointerEvent) => {
        event.preventDefault();
        event.stopPropagation();
        activePointerId = event.pointerId;
        startX = event.clientX;
        startWidth = columns[index].getBoundingClientRect().width;
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        window.addEventListener("pointermove", onPointerMove);
        window.addEventListener("pointerup", onPointerUp);
      };

      const onKeyDown = (event: KeyboardEvent) => {
        const step = event.shiftKey ? 32 : 8;
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        const current = columns[index].getBoundingClientRect().width;
        setColumnWidth(columns[index], current + (event.key === "ArrowRight" ? step : -step), minColumnWidth);
        persist();
      };

      handle.addEventListener("pointerdown", onPointerDown);
      handle.addEventListener("keydown", onKeyDown);
      header.appendChild(handle);

      cleanups.push(() => {
        handle.removeEventListener("pointerdown", onPointerDown);
        handle.removeEventListener("keydown", onKeyDown);
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", onPointerUp);
        handle.remove();
      });
    });

    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      cleanups.forEach((cleanup) => cleanup());
      colgroup.remove();
      table.style.tableLayout = "";
    };
  }, [tableId, minColumnWidth]);

  return (
    <div ref={wrapperRef} className={`bw-table-shell ${className ?? ""}`}>
      {children}
    </div>
  );
}

function setColumnWidth(column: HTMLTableColElement, width: number, minWidth: number) {
  const next = Math.max(minWidth, Math.round(width));
  column.style.width = `${next}px`;
  column.style.minWidth = `${next}px`;
}

function clamp(value: number, min: number) {
  return Math.max(min, Number.isFinite(value) ? value : min);
}

function readWidths(key: string, minWidth: number): Record<number, number> {
  try {
    const raw = localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return {};
    return Object.fromEntries(
      parsed
        .map((value, index) => [index, value] as const)
        .filter(([, value]) => typeof value === "number" && value >= minWidth),
    );
  } catch {
    return {};
  }
}

function hashString(value: string): string {
  let hash = 5381;
  for (let index = 0; index < value.length; index++) {
    hash = ((hash << 5) + hash + value.charCodeAt(index)) | 0;
  }
  return (hash >>> 0).toString(36);
}
