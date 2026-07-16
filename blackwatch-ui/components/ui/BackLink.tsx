import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export function BackLink({
  href,
  label,
}: {
  href: string;
  label: string;
}) {
  return (
    <div className="mb-4">
      <Link
        href={href}
        className="inline-flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
      >
        <ArrowLeft size={12} /> {label}
      </Link>
    </div>
  );
}
