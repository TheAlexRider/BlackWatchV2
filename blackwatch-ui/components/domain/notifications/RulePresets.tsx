import Link from "next/link";
import { AlertTriangle, Bell, Shield, KeyRound, FileWarning, Network, Plus } from "lucide-react";

// Preset rule recipes — common configurations expressed as one-click templates.
// Each preset encodes the wizard inputs as query params so the form on the next
// page is pre-filled. The user can tweak before saving. Nothing magical — just
// the same simple-form fields the RuleForm already understands.
//
// Why this lives separate from the form: most users don't want to think in
// {severity, category, module, action_contains}. They want to think in tasks
// ("page me only on emergencies"). Picking a preset is one decision instead of
// four.

type Preset = {
  id: string;
  title: string;
  blurb: string;
  icon: typeof Bell;
  // Encoded as RuleForm's URL params. The form reads these as defaults.
  params: Record<string, string | string[]>;
};

export const PRESETS: Preset[] = [
  {
    id: "emergencies",
    title: "Wake me up — emergencies only",
    blurb: "Only critical severity. Use for your phone / PagerDuty channel.",
    icon: AlertTriangle,
    params: {
      name: "Emergencies",
      severity_at_least: "critical",
    },
  },
  {
    id: "important",
    title: "Important security stuff",
    blurb:
      "High or critical severity across the board. Good general-purpose Slack channel.",
    icon: Bell,
    params: {
      name: "Important",
      severity_at_least: "high",
    },
  },
  {
    id: "failed-auth",
    title: "Failed logins (SSH + VPN)",
    blurb:
      "Anyone failing to authenticate on a host or the VPN. Quick brute-force signal.",
    icon: KeyRound,
    params: {
      name: "Failed logins",
      action_contains: "auth.failure",
    },
  },
  {
    id: "iam-changes",
    title: "IAM changes",
    blurb:
      "Anything touching IAM users, roles, policies, or access keys.",
    icon: Shield,
    params: {
      name: "IAM changes",
      category: ["iam"],
    },
  },
  {
    id: "public-exposure",
    title: "Public exposure (S3, SG, snapshots)",
    blurb:
      "Storage buckets, security groups, or snapshots opened to the world.",
    icon: Network,
    params: {
      name: "Public exposure",
      action_contains: "public",
    },
  },
  {
    id: "posture-findings",
    title: "New posture findings",
    blurb:
      "Whenever the AWS posture scanner flags a new problem.",
    icon: FileWarning,
    params: {
      name: "Posture findings",
      category: ["finding", "posture"],
    },
  },
];

function encodeParams(params: Record<string, string | string[]>): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) {
      for (const item of v) usp.append(k, item);
    } else {
      usp.set(k, v);
    }
  }
  return usp.toString();
}

export function RulePresets() {
  return (
    <section className="space-y-3">
      <p className="text-sm text-fg-muted">
        Pick a recipe — or{" "}
        <Link
          href="/notifications/rules/new?blank=1"
          className="text-signal hover:underline"
        >
          start from a blank rule
        </Link>
        .
      </p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {PRESETS.map((p) => (
          <Link
            key={p.id}
            href={`/notifications/rules/new?${encodeParams({ ...p.params, preset: p.id })}`}
            className="group flex flex-col gap-2 border border-line-soft bg-surface-1 px-4 py-4 transition-colors hover:border-line hover:bg-surface-2"
          >
            <div className="flex items-center gap-2">
              <p.icon
                size={14}
                strokeWidth={1.5}
                className="text-fg-subtle group-hover:text-signal"
              />
              <span className="text-sm text-fg">{p.title}</span>
            </div>
            <p className="text-xs text-fg-muted">{p.blurb}</p>
          </Link>
        ))}
        <Link
          href="/notifications/rules/new?blank=1"
          className="group flex flex-col gap-2 border border-dashed border-line-soft px-4 py-4 transition-colors hover:border-line hover:bg-surface-2"
        >
          <div className="flex items-center gap-2">
            <Plus
              size={14}
              strokeWidth={1.5}
              className="text-fg-subtle group-hover:text-signal"
            />
            <span className="text-sm text-fg">Blank rule</span>
          </div>
          <p className="text-xs text-fg-muted">
            Build a custom rule from scratch. Same form, no presets applied.
          </p>
        </Link>
      </div>
    </section>
  );
}
