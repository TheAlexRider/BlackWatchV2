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
    headers.forEach((header) => {
      if (!header.hasAttribute("scope")) header.setAttribute("scope", "col");
    });

    const schemaHash = hashString(
      headers.map((header) => header.textContent?.trim() ?? "").join("|"),
    );
    const storageId = tableId
      ? `${tableId}-${schemaHash}`
      : `${window.location.pathname}-auto-${headers.length}-${schemaHash}`;
    // v4 uses the independent-column model. The versioned key also
    // prevents widths saved by that model from making columns unexpectedly
    // narrow after the resize behavior changes.
    const storageKey = `bw-cols-v4-${storageId}`;
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

    // Keep an explicit pixel width for every column. Native table layout can
    // redistribute space when only one <col> is changed, so the width array
    // is the source of truth during a drag.
    let widths = initialWidths.slice();

    const applyColumnWidths = () => {
      widths.forEach((width, index) => {
        setColumnWidth(columns[index], width, minColumnWidth);
      });
      const total = widths.reduce((sum, width) => sum + width, 0);
      // Exact sum means the final column edge is the table edge. The shell
      // provides the horizontal scrollbar when this exceeds the viewport.
      table.style.width = `${Math.ceil(total)}px`;
      table.style.minWidth = `${Math.ceil(total)}px`;
    };
    applyColumnWidths();

    table.querySelectorAll<HTMLTableRowElement>("tbody tr").forEach((row) => {
      Array.from(row.children).forEach((cell, index) => {
        if (cell instanceof HTMLElement && !cell.dataset.label && labels[index]) {
          cell.dataset.label = labels[index];
        }
      });
    });

    const persist = () => {
      try {
        localStorage.setItem(storageKey, JSON.stringify(widths));
      } catch {
        // Storage can be unavailable in private browsing.
      }
    };

    headers.forEach((header, index) => {
      const handle = document.createElement("button");
      handle.type = "button";
      handle.className = `bw-col-resize-handle${index === headers.length - 1 ? " bw-col-resize-handle-last" : ""}`;
      handle.setAttribute("role", "separator");
      handle.setAttribute("aria-orientation", "vertical");
      handle.setAttribute("aria-valuemin", String(minColumnWidth));
      handle.setAttribute("aria-label", `Resize ${labels[index]} column`);
      handle.setAttribute("aria-keyshortcuts", "ArrowLeft ArrowRight");
      handle.title = "Drag to resize. Use arrow keys for precision.";

      let startX = 0;
      let startWidths: number[] = [];
      let activePointerId: number | null = null;
      let frame: number | null = null;
      const updateAria = () => {
        handle.setAttribute("aria-valuenow", String(Math.round(widths[index])));
        handle.setAttribute("aria-valuetext", `${Math.round(widths[index])} pixels`);
      };
      updateAria();

      const applyWidths = (delta: number) => {
        const targetStart = startWidths[index];
        widths[index] = Math.max(minColumnWidth, Math.round(targetStart + delta));
        applyColumnWidths();
        updateAria();
      };

      const onPointerMove = (event: PointerEvent) => {
        if (activePointerId !== event.pointerId) return;
        const delta = event.clientX - startX;
        if (frame !== null) cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => applyWidths(delta));
      };

      const finishPointerResize = (pointerId: number) => {
        if (activePointerId !== pointerId) return;
        activePointerId = null;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", onPointerUp);
        window.removeEventListener("pointercancel", onPointerCancel);
        if (frame !== null) cancelAnimationFrame(frame);
        frame = null;
        persist();
      };

      const onPointerUp = (event: PointerEvent) => {
        finishPointerResize(event.pointerId);
      };

      const onPointerCancel = (event: PointerEvent) => {
        finishPointerResize(event.pointerId);
      };

      const onPointerDown = (event: PointerEvent) => {
        event.preventDefault();
        event.stopPropagation();
        activePointerId = event.pointerId;
        startX = event.clientX;
        startWidths = widths.slice();
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        handle.setPointerCapture?.(event.pointerId);
        window.addEventListener("pointermove", onPointerMove);
        window.addEventListener("pointerup", onPointerUp);
        window.addEventListener("pointercancel", onPointerCancel);
      };

      const onKeyDown = (event: KeyboardEvent) => {
        const step = event.shiftKey ? 32 : 8;
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        startWidths = widths.slice();
        applyWidths(event.key === "ArrowRight" ? step : -step);
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
        window.removeEventListener("pointercancel", onPointerCancel);
        if (activePointerId !== null) {
          try {
            handle.releasePointerCapture?.(activePointerId);
          } catch {
            // Pointer capture may already have been implicitly released.
          }
        }
        handle.remove();
      });
    });

    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      cleanups.forEach((cleanup) => cleanup());
      colgroup.remove();
      table.style.tableLayout = "";
      table.style.width = "";
      table.style.minWidth = "";
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
