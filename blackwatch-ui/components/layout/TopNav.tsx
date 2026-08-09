"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { LogOut, Menu, Settings as SettingsIcon, X } from "lucide-react";

import { LiveCounter } from "./LiveCounter";
import { logoutAction } from "@/app/login/actions";
import { useAuth } from "@/components/auth/AuthProvider";

// Top navigation. On mobile the hamburger toggles the SideNav drawer; on
// desktop it's hidden. The account pill opens a small popover with a
// Sign out action; the Settings icon jumps to /settings.
export function TopNav({
  onMenuClick,
  menuOpen = false,
}: {
  onMenuClick?: () => void;
  menuOpen?: boolean;
}) {
  return (
    <header className="flex h-12 shrink-0 items-center border-b border-line-soft px-3 md:px-4">
      <button
        type="button"
        onClick={onMenuClick}
        aria-label={menuOpen ? "Close menu" : "Open menu"}
        aria-expanded={menuOpen}
        aria-controls="mobile-navigation"
        className="mr-2 flex h-9 w-9 items-center justify-center text-fg-muted transition-colors hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal md:hidden"
      >
        {menuOpen ? <X size={16} /> : <Menu size={16} />}
      </button>

      <div className="flex items-center gap-2.5">
        <Logo />
        <span className="hidden font-mono text-xs uppercase tracking-[0.18em] text-fg-muted sm:inline">
          blackwatch
        </span>
      </div>

      <div className="ml-auto flex items-center gap-3 md:gap-5">
        <LiveCounter />
        <Link
          href="/settings"
          aria-label="Settings"
          className="flex h-8 w-8 items-center justify-center text-fg-subtle transition-colors hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal"
        >
          <SettingsIcon size={15} strokeWidth={1.5} />
        </Link>
        <AccountMenu />
      </div>
    </header>
  );
}

function Logo() {
  return (
    <div
      className="grid h-5 w-5 place-items-center border border-signal text-signal"
      aria-hidden
    >
      <span className="font-mono text-[9px] font-medium leading-none">BW</span>
    </div>
  );
}

function AccountMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { user, role, loading } = useAuth();
  const initials = (user ?? "??").slice(0, 2).toUpperCase();
  const isViewer = !loading && role === "viewer";
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      const items = Array.from(
        ref.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [],
      );
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
      } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const current = items.indexOf(document.activeElement as HTMLElement);
        const offset = e.key === "ArrowDown" ? 1 : -1;
        items[(current + offset + items.length) % items.length]?.focus();
      } else if (e.key === "Home") {
        e.preventDefault();
        items[0]?.focus();
      } else if (e.key === "End") {
        e.preventDefault();
        items[items.length - 1]?.focus();
      }
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    requestAnimationFrame(() => {
      ref.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    });
  }, [open]);

  return (
    <div className="relative flex items-center gap-2" ref={ref}>
      {isViewer && (
        <span
          className="hidden border border-line-soft px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-fg-subtle sm:inline"
          title="Read-only role — mutations disabled"
        >
          viewer
        </span>
      )}
      <button
        ref={triggerRef}
        type="button"
        aria-label="Account"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex h-6 w-6 items-center justify-center border border-line font-mono text-[10px] uppercase tracking-wider text-fg-muted transition-colors hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal"
      >
        {initials}
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-9 z-50 min-w-[200px] border border-line bg-canvas py-1 shadow-lg"
        >
          <div className="border-b border-line-soft px-3 py-1.5 text-[10px] uppercase tracking-wider text-fg-subtle">
            <div className="truncate normal-case tracking-normal text-fg">{user ?? "unknown"}</div>
            <div className="font-mono">{loading ? "…" : role}</div>
          </div>
          <Link
            href="/settings"
            role="menuitem"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-fg-muted transition-colors hover:bg-surface-1 hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-signal"
            onClick={() => setOpen(false)}
          >
            <SettingsIcon size={12} aria-hidden="true" /> Settings
          </Link>
          <form action={logoutAction} className="block">
            <button
              type="submit"
              role="menuitem"
              className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-fg-muted transition-colors hover:bg-surface-1 hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-signal"
            >
              <LogOut size={12} aria-hidden="true" /> Sign out
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
