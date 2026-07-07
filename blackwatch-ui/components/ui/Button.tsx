import { Slot } from "@radix-ui/react-slot";
import { forwardRef } from "react";
import clsx from "clsx";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "secondary", size = "md", asChild = false, className, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={clsx(
          // base
          "inline-flex select-none items-center justify-center gap-2 whitespace-nowrap border font-medium",
          "transition-colors duration-100",
          "focus-visible:outline-none focus-visible:border-signal",
          "disabled:cursor-not-allowed disabled:opacity-40",

          // sizes
          size === "sm" && "h-7 px-2.5 text-xs",
          size === "md" && "h-8 px-3 text-sm",

          // variants
          variant === "primary" &&
            "border-signal bg-signal text-canvas hover:bg-signal/90",
          variant === "secondary" &&
            "border-line bg-surface-1 text-fg hover:bg-surface-2",
          variant === "ghost" &&
            "border-transparent bg-transparent text-fg-muted hover:bg-surface-1 hover:text-fg",
          variant === "danger" &&
            "border-transparent bg-sev-critical text-canvas hover:bg-sev-critical/90",

          className,
        )}
        {...props}
      />
    );
  },
);

Button.displayName = "Button";
