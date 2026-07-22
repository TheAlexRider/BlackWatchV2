import { notFound } from "next/navigation";

import { fetchPerfAlerts, fetchPerfAlert } from "@/lib/api";
import { PerfAlertForm } from "@/components/domain/notifications/PerfAlertForm";

import { updatePerfAlertAction } from "../../actions";

// PerfAlertForm renders the whole wizard shell (back link + title + stepper),
// so this page is intentionally a bare passthrough — no PageHeader / BackLink
// here or they'd double up.
export default async function EditPerfAlertPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  // Fire in parallel — the rule fetch is the gate; instances/channels are
  // for the same form's selects.
  const [rule, list] = await Promise.all([
    fetchPerfAlert(id).catch(() => null),
    fetchPerfAlerts(),
  ]);
  if (!rule) {
    notFound();
  }

  const action = updatePerfAlertAction.bind(null, id);

  return (
    <PerfAlertForm
      mode="edit"
      rule={rule}
      instances={list.instances}
      channels={list.channels}
      action={action}
    />
  );
}
