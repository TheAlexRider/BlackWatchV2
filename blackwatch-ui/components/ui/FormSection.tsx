import { SectionLabel } from "@/components/layout/SectionLabel";

export function FormSection({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div>
        <SectionLabel>{label}</SectionLabel>
        {hint && (
          <p className="mt-0.5 text-[11px] leading-snug text-fg-subtle">
            {hint}
          </p>
        )}
      </div>
      {children}
    </section>
  );
}

export function FieldStack({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-[11px] uppercase tracking-[0.08em] text-fg-subtle">
        {label}
      </span>
      {children}
      {hint && (
        <span className="block text-[10px] leading-tight text-fg-subtle">
          {hint}
        </span>
      )}
    </label>
  );
}
