import { Settings as SettingsIcon } from "lucide-react";
import { LiveCounter } from "./LiveCounter";

export function TopNav() {
  return (
    <header className="flex h-12 shrink-0 items-center border-b border-line-soft px-4">
      <div className="flex items-center gap-2.5">
        <Logo />
        <span className="font-mono text-xs uppercase tracking-[0.18em] text-fg-muted">
          blackwatch
        </span>
      </div>

      <div className="ml-auto flex items-center gap-5">
        <LiveCounter />
        <button
          type="button"
          aria-label="Settings"
          className="text-fg-subtle transition-colors hover:text-fg"
        >
          <SettingsIcon size={15} strokeWidth={1.5} />
        </button>
        <button
          type="button"
          aria-label="Account"
          className="flex h-6 w-6 items-center justify-center border border-line font-mono text-[10px] uppercase tracking-wider text-fg-muted transition-colors hover:text-fg"
        >
          TA
        </button>
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
