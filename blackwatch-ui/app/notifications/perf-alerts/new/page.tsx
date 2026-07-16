import { fetchPerfAlerts } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { BackLink } from "@/components/ui/BackLink";
import { PerfAlertForm } from "@/components/domain/notifications/PerfAlertForm";

import { createPerfAlertAction } from "../actions";

export default async function NewPerfAlertPage() {
  const { instances, channels } = await fetchPerfAlerts();

  return (
    <>
      <BackLink href="/notifications" label="back to notifications" />

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
