import {
  Children,
  cloneElement,
  isValidElement,
  useId,
  type ReactElement,
} from "react";

export function FormRow({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  const generatedId = useId();
  const child =
    Children.count(children) === 1 && isValidElement(children)
      ? (children as ReactElement<{
          id?: string;
          "aria-invalid"?: boolean;
          "aria-describedby"?: string;
        }>)
      : undefined;
  const controlId = child?.props.id ?? generatedId;
  const control =
    child
      ? cloneElement(child, {
          id: controlId,
          "aria-invalid": error ? true : undefined,
          "aria-describedby": error ? `${controlId}-error` : undefined,
        })
      : children;

  return (
    <div className="grid grid-cols-[200px_1fr] items-start gap-4 border-b border-line-soft px-4 py-3 last:border-0">
      <label
        htmlFor={Children.count(children) === 1 ? controlId : undefined}
        className="pt-1 text-xs uppercase tracking-[0.08em] text-fg-subtle"
      >
        {label}
        {hint && (
          <span className="ml-2 normal-case tracking-normal text-fg-disabled">
            {hint}
          </span>
        )}
      </label>
      <div>
        {control}
        {error && (
          <p id={`${controlId}-error`} role="alert" className="mt-1 text-xs text-sev-critical">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
