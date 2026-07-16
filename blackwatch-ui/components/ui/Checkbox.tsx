import { forwardRef } from "react";
import clsx from "clsx";

export interface CheckboxProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: string;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, label, ...props }, ref) => {
    const input = (
      <input
        ref={ref}
        type="checkbox"
        className={clsx(
          "h-3.5 w-3.5 cursor-pointer appearance-none border border-line bg-surface-1",
          "checked:border-signal checked:bg-signal/20",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal",
          "disabled:cursor-not-allowed disabled:opacity-40",
          className,
        )}
        {...props}
      />
    );

    if (!label) return input;

    return (
      <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-fg-muted">
        {input}
        <span>{label}</span>
      </label>
    );
  },
);

Checkbox.displayName = "Checkbox";
