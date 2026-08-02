import { notFound } from "next/navigation";

import { fetchNotificationRoutes, fetchNotificationRules, fetchNotificationChannels } from "@/lib/api";
import { AlertWizard } from "../../../AlertWizard";
import { RuleForm } from "@/components/domain/notifications/RuleForm";
import { PageHeader } from "@/components/layout/PageHeader";
import { BackLink } from "@/components/ui/BackLink";

// Route the edit page based on rule kind:
//   - "simple"  (module + severity) → AlertWizard (5-step form)
//   - "custom"  (action, category, or other conditions) → RuleForm (advanced editor)
//
// Prevents the wizard from being stuck on step 2 ("pick severities") for
// custom rules that don't have any severity clause.
export default async function EditAlertPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const routes = await fetchNotificationRoutes();
  const route = routes.routes.find((r) => r.id === id);
  if (!route) notFound();

  if (route.kind === "simple") {
    return (
      <AlertWizard
        catalog={routes.catalog}
        channels={routes.channels}
        existing={route}
      />
    );
  }

  // Custom rule → use the advanced RuleForm.  Fetch the full rule (needed
  // for throttle/priority — the routes view doesn't include them).
  const { rules } = await fetchNotificationRules();
  const rule = rules.find((r) => r.id === id);
  if (!rule) notFound();
  const { channels } = await fetchNotificationChannels();

  return (
    <>
      <BackLink href="/notifications" label="back to notifications" />
      <PageHeader
        title={`Edit rule: ${rule.name}`}
        subtitle="Custom rule (action / category / advanced match). Edit fields below."
      />
      <RuleForm existing={rule} channels={channels} />
    </>
  );
}
