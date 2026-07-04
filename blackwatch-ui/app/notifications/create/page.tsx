import { fetchNotificationRoutes } from "@/lib/api";
import { AlertWizard } from "../AlertWizard";

export default async function CreateAlertPage() {
  const data = await fetchNotificationRoutes();
  return (
    <AlertWizard catalog={data.catalog} channels={data.channels} />
  );
}
