"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";

import { fetchHostMetrics } from "@/lib/api";
import type { HostMetricsHourlyRow } from "@/lib/types";
import { DataPanel } from "@/components/layout/DataPanel";
import { SectionLabel } from "@/components/layout/SectionLabel";

// Chart of hourly memory / CPU / disk % for one host over the last N hours.
// Layout matches CloudWatch: shaded min-max band with a solid average line on
// top. Three tabs (Memory / CPU / Disk) let the operator flip metrics without
// three separate charts stacked vertically.

type Metric = "mem" | "cpu";
type Range = 24 | 48 | 168 | 216;  // last-day / 2-day / week / 9-day max

const METRICS: Array<{ key: Metric; label: string }> = [
  { key: "mem", label: "Memory %" },
  { key: "cpu", label: "CPU load %" },
];

const RANGES: Array<{ hours: Range; label: string }> = [
  { hours: 24,  label: "24h" },
  { hours: 48,  label: "48h" },
  { hours: 168, label: "7d" },
  { hours: 216, label: "9d" },
];

// One entry per hour, shaped for recharts. `range` is the 2-tuple
// [min, max] used for the shaded band, `avg` for the overlaid line.
type ChartPoint = {
  ts: number;                          // epoch seconds for X axis
  label: string;                       // pre-formatted for the axis tick
  range: [number, number] | undefined;
  avg: number | null;
  min: number | null;
  max: number | null;
};

function pointsFor(rows: HostMetricsHourlyRow[], metric: Metric): ChartPoint[] {
  const minKey = `${metric}_min` as const;
  const avgKey = `${metric}_avg` as const;
  const maxKey = `${metric}_max` as const;
  return rows.map((r) => {
    const min = r[minKey];
    const avg = r[avgKey];
    const max = r[maxKey];
    const ts = new Date(r.hour_start).getTime() / 1000;
    return {
      ts,
      label: formatHour(r.hour_start),
      range: min !== null && max !== null ? [min, max] : undefined,
      avg: avg,
      min,
      max,
    };
  });
}

// Compact axis tick — "14:00" for same-day hours, "Mon 14:00" beyond that.
function formatHour(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const sameDay =
    d.getUTCFullYear() === now.getUTCFullYear() &&
    d.getUTCMonth() === now.getUTCMonth() &&
    d.getUTCDate() === now.getUTCDate();
  const hh = d.getUTCHours().toString().padStart(2, "0");
  if (sameDay) return `${hh}:00`;
  const day = d.toLocaleDateString(undefined, { weekday: "short", timeZone: "UTC" });
  return `${day} ${hh}:00`;
}

export function HostMetricsChart({ instanceId }: { instanceId: string }) {
  const [range, setRange] = useState<Range>(48);
  const [metric, setMetric] = useState<Metric>("mem");
  const [rows, setRows] = useState<HostMetricsHourlyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchHostMetrics(instanceId, range)
      .then((res) => {
        if (!cancelled) setRows(res.series);
      })
      .catch((exc) => {
        if (!cancelled) setError(String(exc));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [instanceId, range]);

  const points = useMemo(() => pointsFor(rows, metric), [rows, metric]);

  // Precompute quick stats for the header — average of the averages,
  // overall peak from the max column. Cheap on ≤216 points.
  const summary = useMemo(() => {
    const avgs = points.map((p) => p.avg).filter((v): v is number => v !== null);
    const maxes = points.map((p) => p.max).filter((v): v is number => v !== null);
    if (avgs.length === 0) return null;
    const avg = avgs.reduce((s, x) => s + x, 0) / avgs.length;
    const peak = maxes.length > 0 ? Math.max(...maxes) : null;
    return { avg, peak, samples: rows.reduce((s, r) => s + r.sample_count, 0) };
  }, [points, rows]);

  return (
    <section className="mt-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <SectionLabel>resource metrics · hourly rollup</SectionLabel>
        <div className="flex items-center gap-1">
          {RANGES.map((r) => (
            <button
              key={r.hours}
              type="button"
              onClick={() => setRange(r.hours)}
              className={
                r.hours === range
                  ? "border border-signal bg-signal/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-fg"
                  : "border border-line-soft bg-canvas px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-fg-subtle hover:text-fg"
              }
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <DataPanel scrollX={false}>
        {/* Metric tab strip */}
        <div className="flex items-center gap-1 border-b border-line-soft px-4 pb-2 pt-3">
          {METRICS.map((m) => (
            <button
              key={m.key}
              type="button"
              onClick={() => setMetric(m.key)}
              className={
                m.key === metric
                  ? "border border-signal bg-signal/10 px-2.5 py-1 text-[11px] text-fg"
                  : "border border-line-soft bg-canvas px-2.5 py-1 text-[11px] text-fg-muted hover:text-fg"
              }
            >
              {m.label}
            </button>
          ))}

          {summary && (
            <div className="ml-auto flex items-baseline gap-4 text-[11px] text-fg-subtle">
              <span>
                avg{" "}
                <span className="font-mono text-fg">{summary.avg.toFixed(1)}%</span>
              </span>
              {summary.peak !== null && (
                <span>
                  peak{" "}
                  <span className="font-mono text-fg">{summary.peak.toFixed(1)}%</span>
                </span>
              )}
              <span>
                <span className="font-mono text-fg-muted">{summary.samples}</span>{" "}
                samples
              </span>
            </div>
          )}
        </div>

        {/* Chart body */}
        <div className="h-[280px] w-full px-2 py-3">
          {loading ? (
            <ChartEmpty label="loading…" />
          ) : error ? (
            <ChartEmpty label={`failed: ${error}`} />
          ) : points.length === 0 ? (
            <ChartEmpty label="no data yet — wait for the next hourly rollup to accumulate" />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={points}
                margin={{ top: 8, right: 16, left: 0, bottom: 4 }}
              >
                <CartesianGrid
                  stroke="var(--color-line-soft)"
                  strokeDasharray="3 3"
                  vertical={false}
                />
                <XAxis
                  dataKey="label"
                  stroke="var(--color-fg-subtle)"
                  tick={{ fontSize: 10, fill: "var(--color-fg-subtle)" }}
                  tickLine={false}
                  minTickGap={30}
                />
                <YAxis
                  domain={[0, 100]}
                  stroke="var(--color-fg-subtle)"
                  tick={{ fontSize: 10, fill: "var(--color-fg-subtle)" }}
                  tickLine={false}
                  tickFormatter={(v) => `${v}%`}
                  width={40}
                />
                <Tooltip content={<MetricTooltip />} />
                {/* Shaded min-max band — the "range" area. */}
                <Area
                  dataKey="range"
                  stroke="none"
                  fill="var(--color-signal)"
                  fillOpacity={0.14}
                  isAnimationActive={false}
                />
                {/* Solid avg line on top of the band. */}
                <Line
                  type="monotone"
                  dataKey="avg"
                  stroke="var(--color-signal)"
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="border-t border-line-soft px-4 py-2 text-[10px] text-fg-subtle">
          Shaded band = hourly min→max · line = hourly avg · retained for 9
          days · timestamps UTC
        </div>
      </DataPanel>
    </section>
  );
}

function ChartEmpty({ label }: { label: string }) {
  return (
    <div className="flex h-full items-center justify-center text-xs text-fg-subtle">
      {label}
    </div>
  );
}

// Custom tooltip — shows min / avg / max stacked, matches BW's typography.
function MetricTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.payload as ChartPoint | undefined;
  if (!p) return null;
  const fmt = (v: number | null) => (v === null ? "—" : `${v.toFixed(1)}%`);
  return (
    <div className="border border-line-soft bg-surface-1 px-3 py-2 font-mono text-xs shadow-lg">
      <div className="mb-1.5 text-[10px] uppercase tracking-[0.08em] text-fg-subtle">
        {label}
      </div>
      <div className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5">
        <span className="text-fg-subtle">min</span>
        <span className="text-fg">{fmt(p.min)}</span>
        <span className="text-fg-subtle">avg</span>
        <span className="text-fg">{fmt(p.avg)}</span>
        <span className="text-fg-subtle">max</span>
        <span className="text-fg">{fmt(p.max)}</span>
      </div>
    </div>
  );
}
