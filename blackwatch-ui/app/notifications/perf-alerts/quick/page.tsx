import { redirect } from "next/navigation";

// The perf-alert quick cards have been folded into /notifications as
// the "metrics" sub-track. This URL is kept only so bookmarks resolve.
export default function LegacyPerfQuickRedirect() {
  redirect("/notifications");
}
