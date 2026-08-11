import { useId, useState } from "react";

export interface BarSeries {
  key: string;
  label: string;
  colorVar: string; // CSS variable name, e.g. "--success" (consumed as hsl(var(--x)))
}

export interface BarDatum {
  label: string; // x-axis category (e.g. "Aug 5")
  values: Record<string, number>; // keyed by series.key
}

// Hand-built inline SVG stacked bar chart — no charting library in this
// project yet, and a handful of small time-series charts didn't justify
// adding one. Follows the house dataviz rules: ≤24px bars, 4px rounded
// data-end at the top segment only, 2px surface-color gaps between stacked
// segments, legend for 2+ series, per-bar hover tooltip, status-token
// colors (no invented palette).
export function StackedBarChart({
  data,
  series,
  height = 200,
  emptyMessage = "No data in this range.",
}: {
  data: BarDatum[];
  series: BarSeries[];
  height?: number;
  emptyMessage?: string;
}) {
  const gradientId = useId();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const totals = data.map((d) => series.reduce((sum, s) => sum + (d.values[s.key] ?? 0), 0));
  const max = Math.max(1, ...totals);
  const hasData = totals.some((t) => t > 0);

  const barWidth = 20;
  const gap = 8;
  const chartWidth = data.length * (barWidth + gap) + gap;
  const topPad = 8;
  const bottomPad = 24;
  const plotHeight = height - topPad - bottomPad;
  const segmentGap = 2;

  return (
    <div>
      {series.length > 1 && (
        <div className="mb-3 flex flex-wrap gap-4 text-xs text-muted-foreground">
          {series.map((s) => (
            <div key={s.key} className="flex items-center gap-1.5">
              <span
                className="h-2.5 w-2.5 rounded-sm"
                style={{ backgroundColor: `hsl(var(${s.colorVar}))` }}
              />
              <span>{s.label}</span>
            </div>
          ))}
        </div>
      )}

      {!hasData ? (
        <p className="py-8 text-center text-sm text-muted-foreground">{emptyMessage}</p>
      ) : (
        <div className="overflow-x-auto">
          <svg
            width={chartWidth}
            height={height}
            role="img"
            aria-label={series.map((s) => s.label).join(", ")}
            className="min-w-full"
          >
            <defs>
              <clipPath id={`${gradientId}-clip`}>
                <rect x={0} y={0} width={chartWidth} height={height} />
              </clipPath>
            </defs>
            {/* baseline */}
            <line
              x1={0}
              y1={topPad + plotHeight}
              x2={chartWidth}
              y2={topPad + plotHeight}
              stroke="hsl(var(--border))"
              strokeWidth={1}
            />
            {data.map((d, i) => {
              const x = gap + i * (barWidth + gap);
              const total = totals[i] ?? 0;
              let yCursor = topPad + plotHeight;
              const segments = series
                .map((s) => ({ key: s.key, colorVar: s.colorVar, value: d.values[s.key] ?? 0 }))
                .filter((s) => s.value > 0);

              return (
                <g
                  key={d.label}
                  onPointerEnter={() => setHoverIndex(i)}
                  onPointerLeave={() => setHoverIndex((cur) => (cur === i ? null : cur))}
                  onFocus={() => setHoverIndex(i)}
                  onBlur={() => setHoverIndex((cur) => (cur === i ? null : cur))}
                  tabIndex={0}
                  style={{ cursor: total > 0 ? "pointer" : "default", outline: "none" }}
                >
                  {/* transparent hit area, taller than the bar itself */}
                  <rect x={x - 2} y={topPad} width={barWidth + 4} height={plotHeight} fill="transparent" />
                  {segments.map((seg, segIndex) => {
                    const segHeight = max > 0 ? (seg.value / max) * plotHeight : 0;
                    const isTop = segIndex === segments.length - 1;
                    const drawHeight = Math.max(0, segHeight - (segIndex > 0 ? segmentGap : 0));
                    yCursor -= segHeight;
                    const segY = segIndex > 0 ? yCursor + segmentGap : yCursor;
                    return (
                      <rect
                        key={seg.key}
                        x={x}
                        y={segY}
                        width={barWidth}
                        height={Math.max(0, drawHeight)}
                        fill={`hsl(var(${seg.colorVar}))`}
                        opacity={hoverIndex === null || hoverIndex === i ? 1 : 0.45}
                        rx={isTop ? 4 : 0}
                        ry={isTop ? 4 : 0}
                      />
                    );
                  })}
                  <text
                    x={x + barWidth / 2}
                    y={height - bottomPad + 14}
                    textAnchor="middle"
                    fontSize={10}
                    fill="hsl(var(--muted-foreground))"
                  >
                    {d.label}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      )}

      {hasData &&
        hoverIndex !== null &&
        (() => {
          const hovered = data[hoverIndex];
          if (!hovered) return null;
          return (
            <div className="mt-2 rounded-md border bg-popover p-2.5 text-xs shadow-sm">
              <p className="mb-1 font-medium text-popover-foreground">{hovered.label}</p>
              <div className="flex flex-col gap-0.5">
                {series.map((s) => (
                  <div key={s.key} className="flex items-center justify-between gap-4">
                    <span className="flex items-center gap-1.5 text-muted-foreground">
                      <span
                        className="h-2 w-2 rounded-sm"
                        style={{ backgroundColor: `hsl(var(${s.colorVar}))` }}
                      />
                      {s.label}
                    </span>
                    <span className="font-medium tabular-nums">{hovered.values[s.key] ?? 0}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })()}
    </div>
  );
}
