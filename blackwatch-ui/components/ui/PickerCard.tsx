import Link from "next/link";
import clsx from "clsx";

export function PickerCard({
  href,
  icon,
  title,
  blurb,
  badge,
  dashed = false,
}: {
  href: string;
  icon: React.ReactNode;
  title: string;
  blurb: string;
  badge?: string;
  dashed?: boolean;
}) {
  return (
    <Link
      href={href}
      className={clsx(
        "group flex flex-col gap-2 px-4 py-4 transition-colors hover:bg-surface-2",
        dashed
          ? "border border-dashed border-line-soft hover:border-line"
          : "border border-line-soft bg-surface-1 hover:border-line",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="text-fg-subtle transition-colors group-hover:text-signal">
          {icon}
        </span>
        <span className="text-sm text-fg">{title}</span>
        {badge && (
          <code className="ml-auto font-mono text-[10px] text-fg-subtle">
            {badge}
          </code>
        )}
      </div>
      <p className="text-xs text-fg-muted">{blurb}</p>
    </Link>
  );
}
