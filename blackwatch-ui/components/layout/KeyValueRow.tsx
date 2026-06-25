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
        "grid grid-cols-[140px_1fr] items-baseline gap-4 border-b border-line-soft px-4 py-2.5 last:border-0",
        className,
      )}
    >
      <dt className="text-xs uppercase tracking-[0.06em] text-fg-subtle">
        {label}
      </dt>
      <dd className="text-sm text-fg">{children}</dd>
    </div>
  );
}
