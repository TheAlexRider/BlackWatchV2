import { format, formatDistanceToNowStrict } from "date-fns";

// Renders an ISO timestamp as a compact relative string with the full
// absolute time on hover. Uses a native <time> element for accessibility.
export function TimestampCell({ value }: { value: string | Date }) {
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) {
    return <span className="font-mono text-xs text-fg-disabled">—</span>;
  }
  const relative = formatDistanceToNowStrict(date, { addSuffix: true });
  const absolute = format(date, "yyyy-MM-dd HH:mm:ss");
  return (
    <time
      dateTime={date.toISOString()}
      title={absolute}
      className="font-mono text-xs text-fg-muted"
    >
      {relative}
    </time>
  );
}
