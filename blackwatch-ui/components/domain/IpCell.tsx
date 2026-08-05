"use client";

import { useState, useRef, useEffect } from "react";
import clsx from "clsx";
import { Search, Copy, Check, ExternalLink } from "lucide-react";

import { IpLookupModal } from "./IpLookupModal";

// Renders an IP (or hostname) with a right-click context menu offering
// "Lookup IP" (opens a modal in-place) plus "Copy" and "Open in IP tool"
// (full-page view).
//
// Right-click is intercepted; left-click is preserved for native text
// selection. Esc / click-outside / scroll closes the menu.

interface IpCellProps {
  value: string | null | undefined;
  className?: string;
  fallback?: React.ReactNode;
}

export function IpCell({ value, className, fallback = "—" }: IpCellProps) {
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const [modalIp, setModalIp] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenu(null);
    };
    const onScroll = () => setMenu(null);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [menu]);

  useEffect(() => {
    return () => {
      if (closeTimer.current) clearTimeout(closeTimer.current);
    };
  }, []);

  if (!value) {
    return <span className={clsx("text-fg-disabled", className)}>{fallback}</span>;
  }

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY });
  };

  const handleLookup = () => {
    setMenu(null);
    setModalIp(value);
  };

  const handleOpenInTool = () => {
    setMenu(null);
    // Navigate via plain anchor so middle-click / cmd-click work too
    window.location.href = `/tools/ip-lookup?ip=${encodeURIComponent(value)}`;
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (closeTimer.current) clearTimeout(closeTimer.current);
      closeTimer.current = setTimeout(() => {
        setMenu(null);
        setCopied(false);
      }, 700);
    } catch {
      setMenu(null);
    }
  };

  return (
    <>
      <code
        onContextMenu={handleContextMenu}
        className={clsx(
          "cursor-context-menu font-mono select-text hover:text-signal",
          className,
        )}
        title="Right-click for actions"
      >
        {value}
      </code>

      {menu && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setMenu(null)}
            onContextMenu={(e) => {
              e.preventDefault();
              setMenu(null);
            }}
          />
          <div
            role="menu"
            className="fixed z-50 min-w-[200px] border border-line bg-surface-2 shadow-xl"
            style={{
              top: Math.min(menu.y, window.innerHeight - 140),
              left: Math.min(menu.x, window.innerWidth - 220),
            }}
          >
            <div className="border-b border-line-soft px-3 py-2 font-mono text-[11px] text-fg-subtle">
              {value}
            </div>
            <MenuItem onClick={handleLookup} icon={Search}>
              Lookup IP
            </MenuItem>
            <MenuItem onClick={handleOpenInTool} icon={ExternalLink}>
              Open in IP tool
            </MenuItem>
            <MenuItem onClick={handleCopy} icon={copied ? Check : Copy}>
              {copied ? "Copied" : "Copy"}
            </MenuItem>
          </div>
        </>
      )}

      <IpLookupModal ip={modalIp} onClose={() => setModalIp(null)} />
    </>
  );
}

function MenuItem({
  onClick,
  icon: Icon,
  children,
}: {
  onClick: () => void;
  icon: typeof Search;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-fg-muted transition-colors hover:bg-surface-1 hover:text-fg"
    >
      <Icon size={12} strokeWidth={1.5} className="text-fg-subtle" />
      <span>{children}</span>
    </button>
  );
}
