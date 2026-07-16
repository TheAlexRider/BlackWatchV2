import clsx from "clsx";

export function ReviewGrid({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <dl
      className={clsx(
        "grid grid-cols-[140px_1fr] gap-y-3 text-sm",
        className,
      )}
    >
      {children}
    </dl>
  );
}

export function ReviewLabel({ children }: { children: React.ReactNode }) {
  return (
    <dt className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
      {children}
    </dt>
  );
}

export function ReviewValue({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <dd className={className}>{children}</dd>;
}
