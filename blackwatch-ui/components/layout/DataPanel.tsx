import clsx from "clsx";

// The bordered/tinted section every table sits inside. Overflow belongs on
// the panel itself so layout classes such as `grid`, `flex`, and `p-*` apply
// to the actual content instead of an invisible wrapper.
export function DataPanel({
  children,
  className,
  scrollX = true,
}: {
  children: React.ReactNode;
  className?: string;
  scrollX?: boolean;
}) {
  return (
    <section
      className={clsx(
        "border border-line-soft bg-surface-1",
        scrollX && "max-w-full overflow-x-auto",
        className,
      )}
      style={scrollX ? { overflowX: "auto" } : undefined}
    >
      {children}
    </section>
  );
}
