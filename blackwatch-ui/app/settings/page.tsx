import Link from "next/link";

import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { KeyValueRow } from "@/components/layout/KeyValueRow";

export default function SettingsPage() {
  // Most settings live in the env / mounted files, not the database. So this
  // page is intentionally thin — connectors moved to /connectors. As the tool
  // grows we'll surface schema version, queue lag, ingest rate, etc. here.
  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="System configuration · most of this is in env / mounted files, not the database."
      />

      <section className="space-y-2">
        <SectionLabel>where things live</SectionLabel>
        <DataPanel>
          <dl>
            <KeyValueRow label="Connectors">
              <Link href="/connectors" className="text-signal hover:underline">
                /connectors
              </Link>
            </KeyValueRow>
            <KeyValueRow label="Rules">
              <Link href="/rules" className="text-signal hover:underline">
                /rules
              </Link>
              <span className="ml-2 text-fg-subtle">
                · YAML in <code className="text-fg">rules/</code>, restart to reload
              </span>
            </KeyValueRow>
            <KeyValueRow label="Notifications">
              <code className="text-fg">notifications.yaml</code> in the repo root
            </KeyValueRow>
            <KeyValueRow label="Ingest tokens">
              <code className="text-fg">BLACKWATCH_TOKENS</code> env var on the
              FastAPI service
            </KeyValueRow>
            <KeyValueRow label="AWS credentials">
              Mounted <code className="text-fg">~/.aws</code> directory · profile
              names are referenced from each connector
            </KeyValueRow>
            <KeyValueRow label="Database">
              Postgres in the <code className="text-fg">db</code> compose
              service · migrations in <code className="text-fg">blackwatch/sql/</code>
            </KeyValueRow>
          </dl>
        </DataPanel>
      </section>

      <section className="mt-6 space-y-2">
        <SectionLabel>operator notes</SectionLabel>
        <DataPanel className="p-4 text-xs text-fg-muted">
          <p>
            BlackWatch keeps secrets out of the database by design. References
            to env vars and mounted files only — see{" "}
            <code className="text-fg">docs/ui-design.md</code> and{" "}
            <code className="text-fg">memory/feedback_custom_tools_over_managed.md</code>.
          </p>
          <p className="mt-2">
            If you need to change an ingest token, edit{" "}
            <code className="text-fg">docker-compose.yml</code> and{" "}
            <code className="text-fg">docker compose up -d app</code>. Agents must
            be re-configured with the new token afterwards.
          </p>
        </DataPanel>
      </section>
    </>
  );
}
