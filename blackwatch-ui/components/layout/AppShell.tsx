"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import { TopNav } from "./TopNav";
import { SideNav } from "./SideNav";

// Root layout. Desktop = fixed sidebar + scrollable main; mobile = drawer
// nav opened via the TopNav hamburger. The auth pages (/login and any
// future sign-up) render bare — no chrome — so a not-yet-authenticated
// user doesn't see teasing navigation before they're allowed in.
//
// `min-h-dvh` prevents the iOS mobile-Safari 100vh trap where the
// toolbar overlaps the last row of content.
const CHROMELESS_PREFIXES = ["/login"];

export function AppShell({ children }: { children: React.ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  const pathname = usePathname();
  const chromeless = CHROMELESS_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(p + "/"),
  );

  if (chromeless) {
    return <div className="min-h-dvh">{children}</div>;
  }

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
