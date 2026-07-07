import { forwardRef } from "react";
import clsx from "clsx";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  mono?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, mono = false, ...props }, ref) => {
    return (
      <input
        ref={ref}
        className={clsx(
          "h-8 w-full border border-line bg-surface-1 px-2.5 text-sm text-fg",
          "placeholder:text-fg-disabled",
          "focus-visible:border-signal",
          "disabled:cursor-not-allowed disabled:opacity-40",
          mono && "font-mono",
          className,
        )}
        {...props}
      />
    );
  },
);

Input.displayName = "Input";
