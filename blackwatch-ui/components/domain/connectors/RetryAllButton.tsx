"use client";

import { Loader2, RotateCcw } from "lucide-react";
import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import type { ConnectorOperation } from "@/lib/types";
import {
  getConnectorOperationAction,
  retryAllConnectorsAction,
} from "@/app/connectors/actions";
import { Button } from "@/components/ui/Button";

export function RetryAllButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [operation, setOperation] = useState<ConnectorOperation | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!operation || !["queued", "running"].includes(operation.status)) return;
    const timer = window.setInterval(() => {
      void getConnectorOperationAction(operation.operation_id).then((result) => {
        const next = result?.operation as ConnectorOperation | undefined;
        if (!next) return;
        setOperation(next);
        if (!["queued", "running"].includes(next.status)) {
          window.clearInterval(timer);
          setMessage(next.status === "succeeded" ? "completed" : "completed with failures");
          router.refresh();
        }
      });
    }, 1200);
    return () => window.clearInterval(timer);
  }, [operation, router]);

  const start = () => {
    setMessage(null);
    startTransition(async () => {
      const result = await retryAllConnectorsAction("eligible");
      const next = result.operation as ConnectorOperation | undefined;
      if (next) setOperation(next);
      setMessage(
        result.accepted
          ? "queued"
          : String(result.reason ?? result.error ?? "could not queue"),
      );
      router.refresh();
    });
  };

  const active = pending || ["queued", "running"].includes(operation?.status ?? "");
  const progress = operation?.outcome as { completed?: number; total?: number } | undefined;
  return (
    <span className="inline-flex items-center gap-2">
      <Button type="button" size="sm" variant="primary" onClick={start} disabled={active} aria-busy={active}>
        {active ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />}
        {active ? "Retrying…" : "Retry eligible"}
      </Button>
      {active && progress && (
        <span role="status" className="font-mono text-[10px] text-fg-muted">
          {progress.completed ?? 0}/{progress.total ?? 0}
        </span>
      )}
      {message && !active && <span role="status" className="text-[10px] text-fg-muted">{message}</span>}
    </span>
  );
}
