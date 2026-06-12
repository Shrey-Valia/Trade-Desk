import { useMemo } from "react";
import { Link } from "react-router-dom";

import { useTickerChart } from "@/hooks/useTickerChart";
import { useTickerDetail } from "@/hooks/useTickerDetail";
import { useTickerMetrics } from "@/hooks/useTickerMetrics";
import { TOOLTIPS } from "@/lib/tooltips";
import { useSelectedTicker } from "@/stores/selectedTicker";
import type { BarPoint } from "@/types/chart";

/**
 * Watchlist right panel — symbol preview for the row the user clicked.
 *
 * The left column's row click already sets the shared selectedTicker
 * store (that's how the CHART view follows the watchlist); this panel
 * subscribes to the same store, so it previews whatever was clicked
 * without new wiring: price + change, a daily-closes sparkline, range/
 * volume/earnings facts, and the options vitals (IV rank, VRP, P/C,
 * skew). "OPEN ON CHART" jumps to the terminal, which is already on
 * this symbol.
 */
export function WatchlistPreview() {
  const symbol = useSelectedTicker((s) => s.symbol);

  if (!symbol) {
    return (
      <Shell>
        <div className="flex-1 flex items-center justify-center text-tiny text-fg-tertiary px-4 text-center">
          Select a symbol on the left to preview it here.
        </div>
      </Shell>
    );
  }
  return <PreviewBody key={symbol} symbol={symbol} />;
}

function PreviewBody({ symbol }: { symbol: string }) {
  const detail = useTickerDetail(symbol);
  const metrics = useTickerMetrics(symbol);
  const chart = useTickerChart(symbol, "1D");
  const d = detail.data;

  return (
    <Shell>
      {/* header row: symbol · price · open-on-chart */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-hairline shrink-0">
        <span className="text-large font-medium text-fg-primary">{symbol}</span>
        {d ? (
          <span className="flex items-baseline gap-2 tabular-nums">
            <span className="text-medium text-fg-primary">
              ${d.price.toFixed(2)}
            </span>
            <span
              className={`text-tiny ${
                d.change_dollar > 0
                  ? "text-bullish"
                  : d.change_dollar < 0
                    ? "text-bearish"
                    : "text-fg-secondary"
              }`}
            >
              {formatSigned(d.change_dollar)} ({formatSigned(d.change_pct, "%")})
            </span>
          </span>
        ) : detail.isError ? (
          <span className="text-tiny text-bearish">quote unavailable</span>
        ) : (
          <span className="text-tiny text-fg-tertiary-2">loading…</span>
        )}
        <Link
          to="/positions"
          className="ml-auto h-6 px-2 inline-flex items-center text-tiny uppercase tracking-label-up border border-amber text-amber bg-tier-1 hover:bg-tier-2"
          style={{ borderRadius: 0 }}
        >
          open on chart →
        </Link>
      </div>

      {/* sparkline */}
      <div className="px-4 pt-3 shrink-0">
        <div
          className="uppercase tracking-label-up text-fg-tertiary-2"
          style={{ fontSize: 9 }}
        >
          daily closes
        </div>
        <div className="border border-hairline mt-1" style={{ height: 140 }}>
          {chart.data && chart.data.bars.length > 1 ? (
            <Sparkline bars={chart.data.bars} />
          ) : (
            <div className="h-full flex items-center justify-center text-tiny text-fg-tertiary-2">
              {chart.isError
                ? "chart unavailable"
                : chart.isLoading
                  ? "loading…"
                  : "no bars"}
            </div>
          )}
        </div>
      </div>

      {/* facts */}
      <div className="px-4 py-3 flex flex-col gap-1.5 tabular-nums">
        {d && (
          <>
            <RangeFact
              label="day range"
              low={d.day_low}
              high={d.day_high}
              value={d.price}
              tooltip={TOOLTIPS.day_range}
            />
            <RangeFact
              label="52w range"
              low={d.fifty_two_week_low}
              high={d.fifty_two_week_high}
              value={d.price}
              tooltip={TOOLTIPS.fiftytwo_week_range}
            />
            <Fact
              label="volume"
              value={`${formatCompact(d.volume)} · avg ${formatCompact(d.avg_volume_20d)}`}
              tooltip={TOOLTIPS.volume}
            />
            <Fact
              label="earnings"
              value={
                d.days_to_earnings != null
                  ? `in ${d.days_to_earnings}d${d.next_earnings_date ? ` · ${d.next_earnings_date}` : ""}`
                  : "—"
              }
              tooltip={TOOLTIPS.er_badge}
            />
          </>
        )}
        <div className="border-t border-hairline my-1" />
        <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
          <Fact
            label="iv rank"
            value={
              metrics.data?.iv_rank != null
                ? `${metrics.data.iv_rank.toFixed(0)}${metrics.data.iv_rank_status ? ` · ${metrics.data.iv_rank_status}` : ""}`
                : "—"
            }
            tooltip={TOOLTIPS.iv_rank}
          />
          <Fact
            label="vrp"
            value={
              metrics.data?.vrp != null ? formatSigned(metrics.data.vrp) : "—"
            }
            tooltip={TOOLTIPS.vrp}
          />
          <Fact
            label="p/c ratio"
            value={
              metrics.data?.pc_ratio != null
                ? metrics.data.pc_ratio.toFixed(2)
                : "—"
            }
            tooltip={TOOLTIPS.pc_ratio}
          />
          <Fact
            label="25Δ skew"
            value={
              metrics.data?.skew_25d != null
                ? formatSigned(metrics.data.skew_25d)
                : "—"
            }
            tooltip={TOOLTIPS.skew_25d}
          />
        </div>
      </div>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-1 min-w-0 flex flex-col bg-tier-0 overflow-y-auto">
      {children}
    </div>
  );
}

/** Daily-close polyline, tinted by net direction over the window. */
function Sparkline({ bars }: { bars: BarPoint[] }) {
  const { path, up } = useMemo(() => {
    const closes = bars.map((b) => b.c);
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const range = Math.max(1e-9, max - min);
    const pts = closes.map((c, i) => {
      const x = (i / (closes.length - 1)) * 100;
      // 4% vertical padding so the line doesn't kiss the border.
      const y = 96 - ((c - min) / range) * 92;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    });
    return { path: pts.join(" "), up: closes[closes.length - 1] >= closes[0] };
  }, [bars]);
  return (
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      className="w-full h-full"
      aria-label="Daily close sparkline"
    >
      <path
        d={path}
        fill="none"
        stroke={up ? "#4DD17C" : "#E85C5C"}
        strokeWidth="1.2"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

function Fact({
  label,
  value,
  tooltip,
}: {
  label: string;
  value: string;
  tooltip?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3" title={tooltip}>
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2 shrink-0"
        style={{ fontSize: 9 }}
      >
        {label}
      </span>
      <span className="text-tiny text-fg-secondary text-right">{value}</span>
    </div>
  );
}

/** Low–high range with a marker showing where the current price sits. */
function RangeFact({
  label,
  low,
  high,
  value,
  tooltip,
}: {
  label: string;
  low: number;
  high: number;
  value: number;
  tooltip?: string;
}) {
  const pct =
    high > low ? Math.min(1, Math.max(0, (value - low) / (high - low))) : 0.5;
  return (
    <div className="flex items-center gap-3" title={tooltip}>
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2 shrink-0"
        style={{ fontSize: 9, width: 64 }}
      >
        {label}
      </span>
      <span className="text-tiny text-fg-secondary shrink-0">
        ${low.toFixed(2)}
      </span>
      <span className="relative flex-1 h-1 bg-tier-2 rounded-sm min-w-[40px]">
        <span
          aria-hidden
          className="absolute top-1/2 w-1.5 h-1.5 rounded-full bg-amber"
          style={{
            left: `calc(${(pct * 100).toFixed(1)}% - 3px)`,
            transform: "translateY(-50%)",
          }}
        />
      </span>
      <span className="text-tiny text-fg-secondary shrink-0">
        ${high.toFixed(2)}
      </span>
    </div>
  );
}

function formatSigned(v: number, suffix = ""): string {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}${Math.abs(v).toFixed(2)}${suffix}`;
}

function formatCompact(v: number): string {
  if (!Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(0);
}
