"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Pencil, Check, X } from "lucide-react";

import { setHostDisplayName } from "@/lib/api";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

// Inline editor for a host's user-editable display name. Sits next to the
// host id in the detail page header. The row on the hosts list is read-only;
// only the detail page can edit — one canonical place, less accidental clicks.
export function HostDisplayNameEditor({
  instanceId,
  initial,
}: {
  instanceId: string;
  initial: string | null;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState<string>(initial ?? "");
  const [saved, setSaved] = useState<string | null>(initial);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function begin() {
    setValue(saved ?? "");
    setEditing(true);
    setError(null);
  }

  function cancel() {
    setValue(saved ?? "");
    setEditing(false);
    setError(null);
  }

  async function commit() {
    const next = value.trim();
    setError(null);
    try {
      const res = await setHostDisplayName(instanceId, next || null);
      setSaved(res.display_name);
      setEditing(false);
      startTransition(() => router.refresh());
    } catch (exc) {
      setError(String(exc));
    }
  }

  if (!editing) {
    return (
      <div className="flex items-center gap-2">
        <span className={saved ? "text-fg" : "text-fg-disabled"}>
          {saved ?? "(no name set)"}
        </span>
        <button
          type="button"
          onClick={begin}
          className="inline-flex items-center gap-1 border border-line-soft px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-fg-subtle transition-colors hover:border-line hover:text-fg"
          aria-label="Edit display name"
        >
          <Pencil size={10} strokeWidth={1.5} />
          Edit
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") cancel();
        }}
        placeholder="e.g. Prod-NAT"
        className="w-56"
        autoFocus
        aria-label="Display name"
      />
      <Button
        type="button"
        size="sm"
        variant="primary"
        onClick={commit}
        disabled={pending}
      >
        <Check size={12} /> Save
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={cancel}>
        <X size={12} /> Cancel
      </Button>
      {error && (
        <span className="text-[11px] text-sev-critical">{error}</span>
      )}
    </div>
  );
}
