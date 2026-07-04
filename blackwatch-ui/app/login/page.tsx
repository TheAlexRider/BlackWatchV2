import Link from "next/link";
import { Lock, ShieldAlert } from "lucide-react";

import { Input } from "@/components/ui/Input";
import { PendingButton } from "@/components/ui/PendingButton";

import { loginAction } from "./actions";

type SearchParams = { next?: string; err?: string };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { next = "/", err } = await searchParams;

  return (
    <div className="grid min-h-dvh place-items-center px-4 py-12">
      <div className="w-full max-w-sm">
        {/* Brand */}
        <div className="mb-8 flex items-center gap-2.5">
          <span
            aria-hidden
            className="grid h-6 w-6 place-items-center border border-signal text-signal"
          >
            <span className="font-mono text-[10px] font-medium leading-none">
              BW
            </span>
          </span>
          <span className="font-mono text-xs uppercase tracking-[0.18em] text-fg-muted">
            blackwatch
          </span>
        </div>

        <h1 className="text-xl text-fg">Sign in</h1>
        <p className="mt-1 text-xs text-fg-muted">
          Enter your credentials to access the dashboard.
        </p>

        {err && (
          <div
            role="alert"
            className="mt-4 flex items-start gap-2 border border-sev-critical/40 bg-sev-critical/10 px-3 py-2 text-xs"
          >
            <ShieldAlert
              size={13}
              className="mt-0.5 shrink-0 text-sev-critical"
              aria-hidden
            />
            <span className="text-fg">{err}</span>
          </div>
        )}

        <form action={loginAction} className="mt-6 space-y-4">
          <input type="hidden" name="next" value={next} />

          <div className="space-y-1.5">
            <label
              htmlFor="username"
              className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle"
            >
              Username
            </label>
            <Input
              id="username"
              name="username"
              type="text"
              autoComplete="username"
              required
              autoFocus
              defaultValue=""
              className="w-full"
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="password"
              className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle"
            >
              Password
            </label>
            <Input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              defaultValue=""
              className="w-full"
            />
          </div>

          <PendingButton
            size="md"
            variant="primary"
            pendingLabel="Signing in…"
            className="w-full justify-center"
          >
            <Lock size={12} /> Sign in
          </PendingButton>
        </form>

        <p className="mt-8 text-[11px] text-fg-subtle">
          First-time setup? The default account is <code className="text-fg-muted">admin</code>{" "}
          / <code className="text-fg-muted">password</code>.{" "}
          <Link href="/settings" className="text-signal hover:underline">
            Change it in Settings
          </Link>{" "}
          right after you sign in.
        </p>
      </div>
    </div>
  );
}
