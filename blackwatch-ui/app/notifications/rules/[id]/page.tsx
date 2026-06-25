import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import {
  fetchNotificationRule,
  fetchNotificationChannels,
} from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
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
      <div className="mb-4">
        <Link
          href="/notifications"
          className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft size={12} /> back to notifications
        </Link>
      </div>
      <PageHeader title={`Edit · ${rule.name}`} subtitle={rule.id} />
      <DataPanel className="overflow-hidden">
        <RuleForm existing={rule} channels={channels} />
      </DataPanel>
    </>
  );
}
