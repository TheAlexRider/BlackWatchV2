import { notFound } from "next/navigation";

import {
  fetchNotificationRule,
  fetchNotificationChannels,
} from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { BackLink } from "@/components/ui/BackLink";
import { RuleForm } from "@/components/domain/notifications/RuleForm";

export default async function EditRulePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [rule, { channels }] = await Promise.all([
    fetchNotificationRule(id),
    fetchNotificationChannels(),
  ]);
  if (!rule) notFound();

  return (
    <>
      <BackLink href="/notifications" label="back to notifications" />
      <PageHeader title={`Edit · ${rule.name}`} subtitle={rule.id} />
      <DataPanel className="overflow-hidden">
        <RuleForm existing={rule} channels={channels} />
      </DataPanel>
    </>
  );
}
