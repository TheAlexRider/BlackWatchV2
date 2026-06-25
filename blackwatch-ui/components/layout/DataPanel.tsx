import clsx from "clsx";

export function DataPanel({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={clsx("border border-line-soft bg-surface-1", className)}>
      {children}
    </section>
  );
}
