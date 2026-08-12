// Page-level header. Title stays h1 for a11y; subtitle now accepts any
// ReactNode so callers can embed colored counts, links, etc. On narrow
// screens actions wrap below the title-block rather than fighting for
// horizontal space.
export function PageHeader({
  title,
  subtitle,
  actions,
  breadcrumbs,
}: {
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  breadcrumbs?: BreadcrumbItem[];
}) {
  return (
    <header className="mb-6 flex flex-col gap-3 md:mb-6 md:flex-row md:items-end md:justify-between md:gap-4">
      <div className="min-w-0">
        {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
        <h1 className="break-words text-pretty text-xl font-medium tracking-tight text-fg">
          {title}
        </h1>
        {subtitle && (
          <div className="mt-1 text-sm text-fg-muted">{subtitle}</div>
        )}
      </div>
      {actions && (
        <div className="flex flex-wrap gap-2 md:shrink-0">{actions}</div>
      )}
    </header>
  );
}
import { Breadcrumbs, type BreadcrumbItem } from "./Breadcrumbs";
