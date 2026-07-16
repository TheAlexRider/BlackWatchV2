import { notFound } from "next/navigation";

import { fetchPerfAlerts, fetchPerfAlert } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { BackLink } from "@/components/ui/BackLink";
import { PerfAlertForm } from "@/components/domain/notifications/PerfAlertForm";

import { updatePerfAlertAction } from "../../actions";

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

  // bind the rule id into the action
  const action = updatePerfAlertAction.bind(null, id);

  return (
    <>
      <BackLink href="/notifications" label="back to notifications" />

      <PageHeader
        title="Edit performance alert"
        subtitle={rule.name}
      />

      <div className="mt-4">
        <PerfAlertForm
          mode="edit"
          rule={rule}
          instances={list.instances}
          channels={list.channels}
          action={action}
        />
      </div>
    </>
  );
}
