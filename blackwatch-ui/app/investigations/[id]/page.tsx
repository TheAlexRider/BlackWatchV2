import { notFound } from "next/navigation";
import { fetchInvestigation } from "@/lib/api";
import { InvestigationNotebook } from "../InvestigationNotebook";

export default async function InvestigationDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const investigation = await fetchInvestigation(id);
  if (!investigation) notFound();
  return <InvestigationNotebook initial={investigation} />;
}
