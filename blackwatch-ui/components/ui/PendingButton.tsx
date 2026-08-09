"use client";

import { useFormStatus } from "react-dom";
import { Loader2, Lock } from "lucide-react";
import { Button, type ButtonProps } from "./Button";
import { useAuth } from "@/components/auth/AuthProvider";

type PendingButtonProps = ButtonProps & {
  pendingLabel?: string;
  children: React.ReactNode;
};

// Submit button that consults its enclosing <form>'s pending state via
// React's useFormStatus. Renders a spinner + "pendingLabel" while the server
// action is running, so the user gets instant visual feedback that the click
// actually did something — even if the network is slow.
//
// Belt-and-suspenders RBAC: auto-disables and shows a lock when the current
// user is a viewer. Backend still enforces the actual gate.
export function PendingButton({
  pendingLabel,
  children,
  disabled,
  title,
  ...rest
}: PendingButtonProps) {
  const { pending } = useFormStatus();
  const { role, loading } = useAuth();
  const readOnly = !loading && role !== "admin";
  return (
    <Button
      type="submit"
      disabled={disabled || pending || readOnly}
      title={readOnly ? "Read-only — admin role required" : title}
      {...rest}
    >
      {pending ? (
        <>
          <Loader2 size={12} className="animate-spin" />
          <span>{pendingLabel ?? "Working…"}</span>
        </>
      ) : readOnly ? (
        <>
          <Lock size={12} />
          <span>{children}</span>
        </>
      ) : (
        children
      )}
    </Button>
  );
}
