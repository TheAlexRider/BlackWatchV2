"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import clsx from "clsx";
import {
  LayoutDashboard,
  Server,
  HardDrive,
  Activity,
  ScrollText,
  Shield,
  Database,
  Bell,
  Plug,
  Settings as SettingsIcon,
  Lock,
  Wrench,
  Key,
  FileLock2,
  ChevronsLeft,
  ChevronsRight,
  type LucideIcon,
} from "lucide-react";

type NavEntry = {
  href: string;
  label: string;
  icon: LucideIcon;
};

const primaryNav: NavEntry[] = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/services", label: "Services", icon: Server },
  { href: "/hosts", label: "Hosts", icon: HardDrive },
  { href: "/fim", label: "File integrity", icon: FileLock2 },
  { href: "/vpn", label: "VPN", icon: Lock },
  { href: "/events", label: "Events", icon: Activity },
  { href: "/iam", label: "IAM", icon: Key },
  { href: "/rds", label: "RDS", icon: Database },
  { href: "/rules", label: "Rules", icon: ScrollText },
  { href: "/aws-posture", label: "AWS posture", icon: Shield },
  { href: "/buckets", label: "Buckets", icon: Database },
  { href: "/notifications", label: "Notifications", icon: Bell },
];

const secondaryNav: NavEntry[] = [
  { href: "/tools", label: "Tools", icon: Wrench },
  { href: "/connectors", label: "Connectors", icon: Plug },
  { href: "/settings", label: "Settings", icon: SettingsIcon },
];

const STORAGE_KEY = "bw-sidenav-collapsed";

export function SideNav() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const stored = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    if (stored === "true") setCollapsed(true);
  }, []);

  function toggle() {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, String(next));
      } catch {
        /* ignore storage errors (private mode, quota) */
      }
      return next;
    });
  }

  return (
    <nav
      aria-label="Primary"
      className={clsx(
        "flex shrink-0 flex-col border-r border-line-soft transition-[width] duration-200 ease-out",
        collapsed ? "w-12" : "w-56",
      )}
    >
      <div className="flex flex-1 flex-col gap-px py-2">
        {primaryNav.map((item) => (
          <NavItem
            key={item.href}
            item={item}
            active={isActive(pathname, item.href)}
            collapsed={collapsed}
          />
        ))}
        <div className="my-2 mx-3 h-px bg-line-soft" />
        {secondaryNav.map((item) => (
          <NavItem
            key={item.href}
            item={item}
            active={isActive(pathname, item.href)}
            collapsed={collapsed}
          />
        ))}
      </div>

      <button
        type="button"
        onClick={toggle}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        className="flex h-9 items-center justify-center border-t border-line-soft text-fg-subtle transition-colors hover:text-fg"
      >
        {collapsed ? <ChevronsRight size={14} /> : <ChevronsLeft size={14} />}
      </button>
    </nav>
  );
}

function NavItem({
  item,
  active,
  collapsed,
}: {
  item: NavEntry;
  active: boolean;
  collapsed: boolean;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      title={collapsed ? item.label : undefined}
      className={clsx(
        "relative mx-2 flex h-8 items-center gap-3 px-2 text-sm transition-colors",
        active ? "text-fg" : "text-fg-subtle hover:text-fg",
      )}
    >
      {active && (
        <span
          aria-hidden
          className="absolute -left-2 top-1/2 h-4 w-0.5 -translate-y-1/2 bg-signal"
        />
      )}
      <Icon size={14} strokeWidth={1.5} className="shrink-0" />
      {!collapsed && <span className="truncate">{item.label}</span>}
    </Link>
  );
}

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}
