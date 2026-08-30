import { redirect } from "next/navigation";

export default async function EditRulePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  // Compatibility route for saved links. The /edit route is the only rule
  // editor so every entry point gets the same kind-aware form.
  redirect(`/notifications/rules/${encodeURIComponent(id)}/edit`);
}
