import { redirect } from "next/navigation";

// The old per-module cards page has been folded into /notifications as
// the "by module" sub-track. This URL is kept only so bookmarks resolve.
export default function LegacyRoutingRedirect() {
  redirect("/notifications");
}
