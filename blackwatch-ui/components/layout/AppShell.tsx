"use client";

import { useState } from "react";
import { TopNav } from "./TopNav";
import { SideNav } from "./SideNav";

// Root layout. On desktop: fixed sidebar + scrollable main. On mobile the
// sidebar becomes an off-canvas drawer opened by the TopNav hamburger.
// The `min-h-dvh` unit prevents the iOS mobile-Safari 100vh trap where
// the toolbar overlaps the last row of content.
export function AppShell({ children }: { children: React.ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="flex min-h-dvh flex-col">
      <TopNav onMenuClick={() => setNavOpen((v) => !v)} menuOpen={navOpen} />
      <div className="flex flex-1 overflow-hidden">
        <SideNav mobileOpen={navOpen} onCloseMobile={() => setNavOpen(false)} />
        <main className="flex-1 overflow-auto px-3 py-4 md:px-8 md:py-6">
          <div className="mx-auto w-full max-w-[1280px]">{children}</div>
        </main>
      </div>
    </div>
  );
}
