import clsx from "clsx";

// Two-column key/value row. Label left, value right. Used for status panels.
export function KeyValueRow({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={clsx(
        "grid min-w-0 grid-cols-1 items-baseline gap-1 border-b border-line-soft px-4 py-2.5 last:border-0 sm:grid-cols-[minmax(140px,1fr)_minmax(0,2fr)] sm:gap-4",
        className,
      )}
    >
      <dt className="text-xs uppercase tracking-[0.08em] text-fg-subtle">
        {label}
      </dt>
      <dd className="min-w-0 break-words text-sm text-fg">{children}</dd>
    </div>
  );
}
