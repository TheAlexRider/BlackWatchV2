import { notFound } from "next/navigation";

import { fetchNotificationRoutes } from "@/lib/api";
import { AlertWizard } from "../../../AlertWizard";

export default async function EditAlertPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const data = await fetchNotificationRoutes();
  const route = data.routes.find((r) => r.id === id);
  if (!route) notFound();
  return (
    <AlertWizard
      catalog={data.catalog}
      channels={data.channels}
      existing={route}
    />
  );
}
