"use client";

import { useEffect, useRef } from "react";

/**
 * ResizableTable — drop-in wrapper that makes ANY child `<table>`'s columns
 * drag-resizable, with widths persisted to localStorage keyed by `tableId`.
 *
 * Usage:
 *   <ResizableTable tableId="fim-hosts">
 *     <table className="w-full table-fixed text-sm">
 *       <thead>
 *         <tr><th>Col 1</th><th>Col 2</th>...</tr>
 *       </thead>
 *       ...
 *     </table>
 *   </ResizableTable>
 *
 * Pick a stable, unique `tableId` per logical table — that's the localStorage
 * key. Reusing the same id across two different tables would have them share
 * widths (which is occasionally what you want, but usually a bug).
 *
 * Design choices:
 *  - DOM-side rather than React-side. We attach handles to <th> elements via
 *    refs + native events. This lets existing server-rendered tables stay as
 *    they are — no need to convert every table to a client component.
 *  - Inline `style.width` wins over Tailwind width classes (`w-44` etc), so
 *    saved widths take precedence after first paint.
 *  - 6px hit area for the handle, visible only on hover (subtle until needed).
 *  - Min width 40px to prevent users from accidentally hiding a column.
 *  - Drag updates DOM directly for smoothness; we persist on mouseup.
 */
export function ResizableTable({
  tableId,
  children,
  className,
  minColumnWidth = 40,
}: {
  tableId: string;
  children: React.ReactNode;
  className?: string;
  minColumnWidth?: number;
}) {
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    const table = wrapper.querySelector("table");
    if (!table) return;
    const ths = Array.from(
      table.querySelectorAll<HTMLTableCellElement>("thead th"),
    );
    if (ths.length === 0) return;

    // Load saved widths (per-column, by zero-based index).
    let saved: Record<number, number> = {};
    try {
      const raw = localStorage.getItem(`bw-cols-${tableId}`);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object") {
          saved = parsed;
        }
      }
    } catch {
      // ignore — corrupted entry, just use defaults
    }

    // Apply saved widths immediately so the first paint matches user's choice.
    ths.forEach((th, i) => {
      if (typeof saved[i] === "number" && saved[i] >= minColumnWidth) {
        th.style.width = `${saved[i]}px`;
      }
      // Position relative so the handle can absolute-position to the right edge.
      if (getComputedStyle(th).position === "static") {
        th.style.position = "relative";
      }
    });

    // Attach a resize handle to each <th>. We skip the last column — resizing
    // it would just trigger horizontal scroll inside the table, which is
    // surprising; leaving it flexible looks more natural.
    const handles: HTMLDivElement[] = [];
    ths.forEach((th, index) => {
      if (index === ths.length - 1) return;

      const handle = document.createElement("div");
      handle.className = "bw-col-resize-handle";
      handle.setAttribute("aria-hidden", "true");
      handle.style.position = "absolute";
      handle.style.right = "-3px";
      handle.style.top = "0";
      handle.style.width = "6px";
      handle.style.height = "100%";
      handle.style.cursor = "col-resize";
      handle.style.zIndex = "10";
      handle.style.userSelect = "none";

      const onMouseDown = (e: MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        const startX = e.clientX;
        const startWidth = th.offsetWidth;

        const onMove = (ev: MouseEvent) => {
          const delta = ev.clientX - startX;
          const next = Math.max(minColumnWidth, startWidth + delta);
          th.style.width = `${next}px`;
        };
        const onUp = () => {
          // Persist all current widths so a multi-column drag session
          // captures every change. Stored as {index: width}.
          const out: Record<number, number> = { ...saved };
          ths.forEach((cell, i) => {
            out[i] = cell.offsetWidth;
          });
          try {
            localStorage.setItem(`bw-cols-${tableId}`, JSON.stringify(out));
            saved = out;
          } catch {
            // ignore — quota or private mode
          }
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          document.body.style.cursor = "";
          document.body.style.userSelect = "";
        };

        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
      };

      handle.addEventListener("mousedown", onMouseDown);
      th.appendChild(handle);
      handles.push(handle);
    });

    return () => {
      handles.forEach((h) => h.remove());
    };
    // We re-run when tableId changes (different table = different storage key)
    // and when minColumnWidth changes (rare, but should re-apply). Children
    // shouldn't matter — the effect operates on the live DOM.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableId, minColumnWidth]);

  return (
    <div ref={wrapperRef} className={className}>
      {children}
    </div>
  );
}
