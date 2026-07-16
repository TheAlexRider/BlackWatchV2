import Link from "next/link";
import { ArrowRight, Bell, GaugeCircle } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { BackLink } from "@/components/ui/BackLink";

// Landing chooser for the two mechanically-different notification types.
// Event-based routes match on existing event fields (module/severity);
// performance-based rules evaluate continuous host metrics against a
// threshold + window. Different mechanics → different forms; this page
// makes the choice explicit instead of pretending they're the same thing.
export default function CreateAlertChooser() {
  return (
    <div className="mx-auto max-w-3xl">
      <BackLink href="/notifications" label="back to notifications" />

      <PageHeader
        title="Create alert"
        subtitle="Pick the shape that fits — event-based for anything BW already emits, performance-based for host metric thresholds."
      />

      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        <ChoiceCard
          href="/notifications/create/event"
          icon={<Bell size={18} strokeWidth={1.5} />}
          title="Event-based route"
          blurb="Fire when BW ingests an event matching a source + severity. Works for every module: auth, IAM, RDS, API Gateway, ECS probes, etc."
          examples={[
            "IAM: root-user activity → Slack #security",
            "API GW: auth burst → Slack + PagerDuty",
            "VPN: brute-force → Slack #ops",
          ]}
        />
        <ChoiceCard
          href="/notifications/perf-alerts/new"
          icon={<GaugeCircle size={18} strokeWidth={1.5} />}
          title="Performance-based rule"
          blurb="Fire when a host metric breaches a threshold for a configurable duration. Scope by instance or by tag. Fully customizable — metric, comparison, threshold, window, breach ratio."
          examples={[
            "CPU load > 80% for 15 min on any prod host",
            "Memory used > 90% for 5 min on i-08ba…",
            "Disk (worst mount) > 85% for 30 min on env=prod",
          ]}
        />
      </div>
    </div>
  );
}

function ChoiceCard({
  href,
  icon,
  title,
  blurb,
  examples,
}: {
  href: string;
  icon: React.ReactNode;
  title: string;
  blurb: string;
  examples: string[];
}) {
  return (
    <Link href={href} className="group block focus:outline-none">
      <DataPanel className="flex h-full flex-col p-5 transition-colors group-hover:border-sig-teal group-focus-visible:border-sig-teal">
        <div className="flex items-center gap-2 text-fg">
          <span className="text-sig-teal">{icon}</span>
          <h2 className="text-base">{title}</h2>
          <ArrowRight
            size={14}
            className="ml-auto text-fg-subtle transition-colors group-hover:text-sig-teal"
          />
        </div>
        <p className="mt-2 text-sm leading-snug text-fg-muted">{blurb}</p>
        <ul className="mt-4 space-y-1 text-[11px] text-fg-subtle">
          {examples.map((e) => (
            <li key={e} className="font-mono">
              · {e}
            </li>
          ))}
        </ul>
      </DataPanel>
    </Link>
  );
}
