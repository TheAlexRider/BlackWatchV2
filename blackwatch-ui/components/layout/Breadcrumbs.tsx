import Link from "next/link";
import { ChevronRight } from "lucide-react";

export type BreadcrumbItem = {
  label: string;
  href?: string;
};

export function Breadcrumbs({ items }: { items: BreadcrumbItem[] }) {
  if (items.length === 0) return null;
  return (
    <nav aria-label="Breadcrumb" className="mb-2">
      <ol className="flex min-w-0 flex-wrap items-center gap-1 text-[10px] uppercase tracking-[0.08em] text-fg-subtle">
        {items.map((item, index) => (
          <li key={`${item.label}-${index}`} className="flex min-w-0 items-center gap-1">
            {index > 0 && <ChevronRight size={11} aria-hidden="true" />}
            {item.href ? (
              <Link href={item.href} className="truncate transition-colors hover:text-signal focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal">
                {item.label}
              </Link>
            ) : (
              <span className="truncate text-fg-muted" aria-current="page">{item.label}</span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
