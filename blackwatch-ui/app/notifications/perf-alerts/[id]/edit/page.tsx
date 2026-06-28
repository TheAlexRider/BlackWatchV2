import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { notFound } from "next/navigation";

import { fetchPerfAlerts, fetchPerfAlert } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
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
      <div className="mb-4">
        <Link
          href="/notifications"
          className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft size={12} /> back to notifications
        </Link>
      </div>

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
