export function FormRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-[200px_1fr] items-start gap-4 border-b border-line-soft px-4 py-3 last:border-0">
      <label className="pt-1 text-xs uppercase tracking-[0.08em] text-fg-subtle">
        {label}
        {hint && (
          <span className="ml-2 normal-case tracking-normal text-fg-disabled">
            {hint}
          </span>
        )}
      </label>
      <div>{children}</div>
    </div>
  );
}
