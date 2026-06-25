import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { fetchNotificationChannels } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { RuleForm, type RulePrefill } from "@/components/domain/notifications/RuleForm";
import { RulePresets } from "@/components/domain/notifications/RulePresets";

type SearchParams = {
  preset?: string;
  blank?: string;
  name?: string;
  severity_at_least?: string;
  action_contains?: string;
  category?: string | string[];
  module?: string | string[];
};

// Two modes:
//   - landing (no params): show the preset picker
//   - building (any param present): show the form, pre-filled from URL
//
// The "blank=1" flag exists so the "start from blank" link still takes the
// user past the preset picker, even with no other params set.
export default async function NewRulePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const { channels } = await fetchNotificationChannels();

  const hasAnyParam =
    !!params.preset ||
    !!params.blank ||
    !!params.name ||
    !!params.severity_at_least ||
    !!params.action_contains ||
    !!params.category ||
    !!params.module;

  if (!hasAnyParam) {
    return (
      <>
        <BackLink />
        <PageHeader
          title="Add a rule"
          subtitle="Pick a recipe — or build a custom one. You can edit it after."
        />
        <RulePresets />
      </>
    );
  }

  const prefill: RulePrefill = {
    name: params.name,
    severity_at_least: params.severity_at_least,
    action_contains: params.action_contains,
    categories: toArray(params.category),
    modules: toArray(params.module),
  };

  return (
    <>
      <BackLink />
      <PageHeader
        title="New rule"
        subtitle="Tweak the recipe and pick which channels should receive it."
      />
      <DataPanel className="overflow-hidden">
        <RuleForm channels={channels} prefill={prefill} />
      </DataPanel>
    </>
  );
}

function toArray(v: string | string[] | undefined): string[] {
  if (!v) return [];
  return Array.isArray(v) ? v : [v];
}

function BackLink() {
  return (
    <div className="mb-4">
      <Link
        href="/notifications"
        className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
      >
        <ArrowLeft size={12} /> back to notifications
      </Link>
    </div>
  );
}
