import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { fetchPerfAlerts } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { PerfAlertForm } from "@/components/domain/notifications/PerfAlertForm";

import { createPerfAlertAction } from "../actions";

export default async function NewPerfAlertPage() {
  const { instances, channels } = await fetchPerfAlerts();

  return (
    <>
      <div className="mb-4">
        <Link
          href="/notifications"
          className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft size={12} /> back to notifications
        </Link>
      </div>

      <PageHeader
        title="New performance alert"
        subtitle="Threshold-based alerting on EC2 metrics — memory, CPU, disk"
      />

      <div className="mt-4">
        <PerfAlertForm
          mode="create"
          instances={instances}
          channels={channels}
          action={createPerfAlertAction}
        />
      </div>
    </>
  );
}
