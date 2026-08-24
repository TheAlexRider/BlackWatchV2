import Link from "next/link";
import { KeyRound } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";
import { KeyValueRow } from "@/components/layout/KeyValueRow";
import { Input } from "@/components/ui/Input";
import { PendingButton } from "@/components/ui/PendingButton";
import { FlashToast } from "@/components/ui/FlashToast";
import { TablePageSizeSetting } from "@/components/ui/TablePreferences";

import { changePasswordAction } from "./actions";

type SearchParams = { msg?: string };

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { msg } = await searchParams;

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Account credentials + pointers to where the rest of the config lives."
      />

      {msg && <FlashToast message={msg} />}

      <section className="space-y-2">
        <SectionLabel>table display</SectionLabel>
        <DataPanel className="p-4" scrollX={false}>
          <TablePageSizeSetting />
        </DataPanel>
      </section>

      {/* Account credentials — the one thing on this page that actually
          writes to the DB. Everything else is just documentation. */}
      <section className="space-y-2">
        <SectionLabel>account</SectionLabel>
        <DataPanel className="p-4" scrollX={false}>
          <div className="mb-3 flex items-center gap-2">
            <KeyRound size={13} className="text-signal" aria-hidden />
            <span className="text-sm text-fg">Change password</span>
          </div>
          <p className="mb-4 text-xs text-fg-muted">
            Sessions time out after 30 minutes of inactivity. Changing your
            password does not invalidate this session.
          </p>

          <form
            action={changePasswordAction}
            className="grid gap-3 max-w-md"
            autoComplete="off"
          >
            <div className="space-y-1">
              <label
                htmlFor="current_password"
                className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle"
              >
                Current password
              </label>
              <Input
                id="current_password"
                name="current_password"
                type="password"
                autoComplete="current-password"
                required
                className="w-full"
              />
            </div>
            <div className="space-y-1">
              <label
                htmlFor="new_password"
                className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle"
              >
                New password
              </label>
              <Input
                id="new_password"
                name="new_password"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                className="w-full"
              />
            </div>
            <div className="space-y-1">
              <label
                htmlFor="confirm_password"
                className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle"
              >
                Confirm new password
              </label>
              <Input
                id="confirm_password"
                name="confirm_password"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                className="w-full"
              />
            </div>
            <div className="pt-1">
              <PendingButton size="sm" variant="primary" pendingLabel="Saving…">
                Update password
              </PendingButton>
            </div>
          </form>
        </DataPanel>
      </section>

      {/* --- documentation-only sections below --- */}

      <section className="mt-6 space-y-2">
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
        <DataPanel className="p-4 text-xs text-fg-muted" scrollX={false}>
          <p>
            BlackWatch keeps secrets out of the database by design. References
            to env vars and mounted files only — see{" "}
            <code className="text-fg">docs/ui-design.md</code>.
          </p>
          <p className="mt-2">
            If you need to change an ingest token, edit{" "}
            <code className="text-fg">docker-compose.yml</code> and{" "}
            <code className="text-fg">docker compose up -d app</code>. Agents
            must be re-configured with the new token afterwards.
          </p>
        </DataPanel>
      </section>
    </>
  );
}
