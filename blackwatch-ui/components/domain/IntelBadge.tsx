import clsx from "clsx";

export type IntelData = {
  country?: string | null;
  asn?: number | null;
  asn_org?: string | null;
  feeds?: string[] | null;
  is_tor?: boolean | null;
  is_bogon?: boolean | null;
};

const FEED_LABEL: Record<string, string> = {
  spamhaus_drop: "Spamhaus DROP",
  spamhaus_edrop: "Spamhaus EDROP",
  firehol_level1: "FireHOL L1",
  tor_exit: "Tor exit",
};

export function IntelBadge({ intel }: { intel?: IntelData | null }) {
  if (!intel) return null;
  const feeds = intel.feeds ?? [];
  const flagged = feeds.length > 0 || intel.is_tor;
  const chips: { key: string; text: string; danger?: boolean }[] = [];
  if (intel.country) chips.push({ key: "cc", text: intel.country });
  if (intel.asn) {
    const asnText = intel.asn_org
      ? `AS${intel.asn} ${intel.asn_org}`
      : `AS${intel.asn}`;
    chips.push({ key: "asn", text: asnText });
  }
  for (const f of feeds) {
    chips.push({ key: `feed-${f}`, text: FEED_LABEL[f] ?? f, danger: true });
  }
  if (intel.is_tor && !feeds.includes("tor_exit")) {
    chips.push({ key: "tor", text: "Tor exit", danger: true });
  }
  if (intel.is_bogon) chips.push({ key: "bogon", text: "bogon" });
  if (chips.length === 0) return null;

  return (
    <div
      className={clsx(
        "inline-flex flex-wrap items-center gap-1.5 rounded border px-2 py-1",
        flagged
          ? "border-sev-critical/40 bg-sev-critical/5"
          : "border-border bg-bg-subtle",
      )}
      aria-label={flagged ? "threat intel: flagged" : "threat intel"}
    >
      {chips.map((c) => (
        <span
          key={c.key}
          className={clsx(
            "inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide",
            c.danger
              ? "bg-sev-critical/15 text-sev-critical"
              : "bg-bg-emphasis text-fg-muted",
          )}
        >
          {c.text}
        </span>
      ))}
    </div>
  );
}
