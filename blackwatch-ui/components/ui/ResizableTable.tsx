"use client";

import { useEffect, useRef } from "react";

const DEFAULT_MIN_COLUMN_WIDTH = 72;

/**
 * Adds predictable column sizing to the shared Table component.
 *
 * Handles are real buttons, so resizing works with a pointer and keyboard.
 * Widths are stored per table and reapplied after hydration without causing
 * the table to jump between an auto layout and a fixed layout.
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
    const table = wrapper?.querySelector("table");
    if (!wrapper || !table) return;

    const headers = Array.from(
      table.querySelectorAll<HTMLTableCellElement>("thead th"),
    );
    if (!headers.length) return;

    const storageId = tableId
      ? tableId
      : `auto-${headers.length}-${hashString(
          headers.map((header) => header.textContent?.trim() ?? "").join("|"),
        )}`;
    const storageKey = `bw-cols-${storageId}`;
    let saved = readWidths(storageKey, minColumnWidth);
    const cleanupHandles: Array<() => void> = [];
    const labels = headers.map((header) =>
      header.hasAttribute("data-actions")
        ? "Actions"
        : header.textContent?.trim() ?? "",
    );

    table.querySelectorAll<HTMLTableRowElement>("tbody tr").forEach((row) => {
      Array.from(row.children).forEach((cell, index) => {
        if (cell instanceof HTMLElement && !cell.dataset.label && labels[index]) {
          cell.dataset.label = labels[index];
        }
      });
    });

    const setWidth = (header: HTMLTableCellElement, width: number) => {
      const next = Math.max(minColumnWidth, Math.round(width));
      header.style.width = `${next}px`;
      header.style.minWidth = `${next}px`;
    };

    headers.forEach((header, index) => {
      setWidth(
        header,
        saved[index] ?? Math.max(minColumnWidth, header.getBoundingClientRect().width),
      );

      const handle = document.createElement("button");
      handle.type = "button";
      handle.className = "bw-col-resize-handle";
      handle.setAttribute("aria-label", `Resize ${header.textContent?.trim() || `column ${index + 1}`} column`);
      handle.title = "Drag to resize. Use arrow keys for precision.";

      let startX = 0;
      let startWidth = 0;
      let activePointerId: number | null = null;

      const persist = () => {
        saved = Object.fromEntries(
          headers.map((cell, cellIndex) => [cellIndex, Math.round(cell.getBoundingClientRect().width)]),
        );
        try {
          localStorage.setItem(storageKey, JSON.stringify(saved));
        } catch {
          // Storage can be unavailable in private browsing.
        }
      };

      const onPointerMove = (event: PointerEvent) => {
        if (activePointerId !== event.pointerId) return;
        setWidth(header, startWidth + event.clientX - startX);
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
        startWidth = header.getBoundingClientRect().width;
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        window.addEventListener("pointermove", onPointerMove);
        window.addEventListener("pointerup", onPointerUp);
      };

      const onKeyDown = (event: KeyboardEvent) => {
        const step = event.shiftKey ? 32 : 8;
        const currentWidth = header.getBoundingClientRect().width;
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          setWidth(header, currentWidth + (event.key === "ArrowRight" ? step : -step));
          persist();
        }
      };

      handle.addEventListener("pointerdown", onPointerDown);
      handle.addEventListener("keydown", onKeyDown);
      header.appendChild(handle);

      cleanupHandles.push(() => {
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
      cleanupHandles.forEach((cleanup) => cleanup());
    };
    // The table DOM is intentionally managed once per table identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableId, minColumnWidth]);

  return (
    <div ref={wrapperRef} className={`bw-table-shell ${className ?? ""}`}>
      {children}
    </div>
  );
}

function readWidths(key: string, minWidth: number): Record<number, number> {
  try {
    const raw = localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== "object") return {};
    return Object.fromEntries(
      Object.entries(parsed).filter(
        ([, value]) => typeof value === "number" && value >= minWidth,
      ),
    ) as Record<number, number>;
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
