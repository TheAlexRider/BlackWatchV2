import clsx from "clsx";
import { StatusDot } from "./StatusDot";

type EmptyStateSize = "sm" | "md" | "lg";
type EmptyStateTone = "neutral" | "ok";

const SIZE_CLASS: Record<EmptyStateSize, string> = {
  sm: "px-6 py-8",
  md: "px-6 py-10",
  lg: "px-6 py-16",
};

/** Shared empty content treatment for panels and data views. */
export function EmptyState({
  children,
  size = "md",
  tone = "neutral",
  className,
}: {
  children: React.ReactNode;
  size?: EmptyStateSize;
  tone?: EmptyStateTone;
  className?: string;
}) {
  return (
    <div
      className={clsx(
        "flex items-center justify-center gap-2 text-center text-sm",
        SIZE_CLASS[size],
        "text-fg-muted",
        className,
      )}
    >
      {tone === "ok" && <StatusDot severity="resolved" />}
      {children}
    </div>
  );
}
