"use client";

import { useEffect, useRef } from "react";

/**
 * ResizableTable — drop-in wrapper that makes ANY child `<table>`'s columns
 * drag-resizable, with widths persisted to localStorage keyed by `tableId`.
 *
 * Most callers should use the higher-level `<Table>` wrapper in Table.tsx
 * instead — it applies the shared `.bw-table` CSS AND the resize handles.
 * ResizableTable is only used directly by tables that need custom shell
 * markup around the <table> element.
 *
 * `tableId` is optional: when omitted, an id is auto-derived from the
 * sequence of header labels — stable across renders and unique per header
 * layout. Provide an explicit id only when two tables share the same
 * headers but should NOT share saved widths.
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
  /** Optional. If omitted, an id is auto-derived from the sequence of
   *  header labels — stable across renders as long as the header changes
   *  don't. Pass an explicit id when two tables in the same app share
   *  headers but should NOT share widths. */
  tableId?: string;
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

    // Derive a storage key from either the explicit prop or a hash of the
    // header labels + column count. Header text is stable across renders,
    // so widths persist correctly even when the caller didn't bother to
    // hand-craft a `tableId`.
    const derivedId = tableId
      ? tableId
      : `auto-${ths.length}-${_hashString(
          ths.map((t) => (t.textContent || "").trim()).join("|"),
        )}`;

    // Load saved widths (per-column, by zero-based index).
    let saved: Record<number, number> = {};
    try {
      const raw = localStorage.getItem(`bw-cols-${derivedId}`);
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
            localStorage.setItem(`bw-cols-${derivedId}`, JSON.stringify(out));
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

// Tiny DJB2-ish string hash so the auto-tableId is short but stable. We
// don't need cryptographic strength — this key only namespaces widths
// inside a single browser's localStorage.
function _hashString(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  }
  // 32-bit unsigned → base36 for compactness.
  return (h >>> 0).toString(36);
}
