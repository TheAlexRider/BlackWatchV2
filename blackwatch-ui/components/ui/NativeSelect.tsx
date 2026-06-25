import { forwardRef } from "react";
import clsx from "clsx";

// Plain native <select> styled to match the design system. Used inside
// GET forms where we want the URL to update on submit (no JS needed).
// For richer in-page UX use a Radix Select primitive later.
export interface NativeSelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {}

export const NativeSelect = forwardRef<HTMLSelectElement, NativeSelectProps>(
  ({ className, children, ...props }, ref) => {
    return (
      <select
        ref={ref}
        className={clsx(
          "h-8 appearance-none border border-line bg-surface-1 px-2.5 pr-7 text-sm text-fg",
          "focus-visible:border-signal focus-visible:outline-none",
          "disabled:cursor-not-allowed disabled:opacity-40",
          // chevron rendered via background-image (no extra DOM)
          "bg-[image:url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2210%22 height=%2210%22 viewBox=%220 0 10 10%22><path d=%22M2 4l3 3 3-3%22 stroke=%22%239CA3AF%22 stroke-width=%221.2%22 fill=%22none%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22/></svg>')]",
          "bg-[length:10px_10px] bg-[position:right_0.625rem_center] bg-no-repeat",
          className,
        )}
        {...props}
      >
        {children}
      </select>
    );
  },
);

NativeSelect.displayName = "NativeSelect";
