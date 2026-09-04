"use client";

import { Loader2, Play, ShieldCheck } from "lucide-react";
import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import type { ConnectorOperation } from "@/lib/types";
import {
  getConnectorOperationAction,
  startConnectorOperationAction,
} from "@/app/connectors/actions";
import { Button } from "@/components/ui/Button";

type Kind = "manual" | "test";

export function ConnectorActionButton({
  connectorId,
  kind,
  disabled = false,
}: {
  connectorId: string;
  kind: Kind;
  disabled?: boolean;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [operation, setOperation] = useState<ConnectorOperation | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const status = operation?.status;
    if (!operation || (status !== "queued" && status !== "running")) return;
    const timer = window.setInterval(() => {
      void getConnectorOperationAction(operation.operation_id).then((result) => {
        const next = result?.operation as ConnectorOperation | undefined;
        if (!next) return;
        setOperation(next);
        if (!["queued", "running"].includes(next.status)) {
          window.clearInterval(timer);
          setMessage(
            next.status === "succeeded"
              ? "completed"
              : next.status === "timed_out"
                ? "timed out"
                : next.status === "failed"
                  ? "failed — open diagnostics"
                  : next.status,
          );
          router.refresh();
        }
      });
    }, 1200);
    return () => window.clearInterval(timer);
  }, [operation, router]);

  const start = () => {
    setMessage(null);
    startTransition(async () => {
      const result = await startConnectorOperationAction(connectorId, kind);
      const next = result.operation as ConnectorOperation | undefined;
      if (next) setOperation(next);
      if (result.duplicate) {
        setMessage("already running");
      } else if (result.accepted) {
        setMessage("queued");
      } else {
        setMessage(String(result.reason ?? result.error ?? "could not start"));
      }
      router.refresh();
    });
  };

  const active = pending || ["queued", "running"].includes(operation?.status ?? "");
  const label = kind === "test" ? "Test" : "Run now";
  return (
    <span className="inline-flex items-center gap-1">
      <Button
        type="button"
        size="sm"
        variant="secondary"
        onClick={start}
        disabled={disabled || active}
        aria-busy={active}
        title={disabled ? "Test successfully first" : `Start ${kind} operation`}
      >
        {active ? <Loader2 size={12} className="animate-spin" /> : kind === "test" ? <ShieldCheck size={12} /> : <Play size={12} />}
        {active ? (operation?.status === "running" ? "Running…" : "Queued…") : label}
      </Button>
      {message && (
        <span role="status" className="max-w-28 truncate text-[10px] text-fg-muted" title={message}>
          {message}
        </span>
      )}
    </span>
  );
}
