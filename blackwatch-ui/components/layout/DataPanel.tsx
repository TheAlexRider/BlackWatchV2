import clsx from "clsx";

// The bordered/tinted section every table sits inside. On narrow viewports
// wide tables would either force horizontal page scroll or squish into
// unreadable columns — so we make the panel's inner region scroll
// horizontally by default (`overflow-x-auto`). Callers that don't have
// a table (e.g. embed a form or a description panel) can opt out with
// `scrollX={false}`, and pages that historically shipped
// `className="overflow-hidden"` still work because the outer section
// itself is unchanged.
export function DataPanel({
  children,
  className,
  scrollX = true,
}: {
  children: React.ReactNode;
  className?: string;
  scrollX?: boolean;
}) {
  const content = scrollX ? (
    <div className="overflow-x-auto">{children}</div>
  ) : (
    children
  );
  return (
    <section
      className={clsx("border border-line-soft bg-surface-1", className)}
    >
      {content}
    </section>
  );
}
