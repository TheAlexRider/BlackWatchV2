"use client";

import { useFormStatus } from "react-dom";
import { Loader2 } from "lucide-react";
import { Button, type ButtonProps } from "./Button";

type PendingButtonProps = ButtonProps & {
  pendingLabel?: string;
  children: React.ReactNode;
};

// Submit button that consults its enclosing <form>'s pending state via
// React's useFormStatus. Renders a spinner + "pendingLabel" while the server
// action is running, so the user gets instant visual feedback that the click
// actually did something — even if the network is slow.
export function PendingButton({
  pendingLabel,
  children,
  disabled,
  ...rest
}: PendingButtonProps) {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" disabled={disabled || pending} {...rest}>
      {pending ? (
        <>
          <Loader2 size={12} className="animate-spin" />
          <span>{pendingLabel ?? "Working…"}</span>
        </>
      ) : (
        children
      )}
    </Button>
  );
}
