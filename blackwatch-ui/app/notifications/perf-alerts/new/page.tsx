import { fetchPerfAlerts } from "@/lib/api";
import { PerfAlertForm } from "@/components/domain/notifications/PerfAlertForm";

import { createPerfAlertAction } from "../actions";

// PerfAlertForm renders the whole wizard shell (back link + title + stepper),
// so this page is intentionally a bare passthrough — no PageHeader / BackLink
// here or they'd double up.
export default async function NewPerfAlertPage() {
  const { instances, channels } = await fetchPerfAlerts();

  return (
    <PerfAlertForm
      mode="create"
      instances={instances}
      channels={channels}
      action={createPerfAlertAction}
    />
  );
}
