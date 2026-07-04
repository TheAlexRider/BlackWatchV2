import Link from "next/link";
import { Menu, Settings as SettingsIcon, X } from "lucide-react";
import { LiveCounter } from "./LiveCounter";

// Top navigation. On mobile the hamburger toggles the SideNav drawer; on
// desktop it's hidden.
//
// The Settings button now navigates to /settings (was a dead button
// before). The account pill was decorative-only; kept as a static badge
// since there's no user-switch UI in this app.
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
        <span
          aria-hidden
          className="flex h-6 w-6 items-center justify-center border border-line font-mono text-[10px] uppercase tracking-wider text-fg-muted"
        >
          TA
        </span>
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
