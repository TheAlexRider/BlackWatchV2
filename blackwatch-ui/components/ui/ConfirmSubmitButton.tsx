"use client";

import { useFormStatus } from "react-dom";
import { Loader2 } from "lucide-react";

import { Button, type ButtonProps } from "./Button";

export function ConfirmSubmitButton({
  confirmMessage,
  pendingLabel = "Working…",
  children,
  disabled,
  ...props
}: ButtonProps & {
  confirmMessage: string;
  pendingLabel?: string;
  children: React.ReactNode;
}) {
  const { pending } = useFormStatus();

  return (
    <Button
      type="submit"
      disabled={disabled || pending}
      onClick={(event) => {
        if (!window.confirm(confirmMessage)) event.preventDefault();
      }}
      {...props}
    >
      {pending ? (
        <>
          <Loader2 size={12} className="animate-spin" aria-hidden="true" />
          <span>{pendingLabel}</span>
        </>
      ) : (
        children
      )}
    </Button>
  );
}
