import { useEffect, useRef } from "react";
import {
  AreaSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";

import { colors } from "@/lib/design";
import type { TradeAnalytics } from "@/types/journal";

const POSITION_COLOR = "#D4537E";

interface Props {
  analytics: TradeAnalytics | null | undefined;
  loading?: boolean;
}

/**
 * Payoff curve — solid expiration P&L + dashed today P&L.
 *
 * Built on lightweight-charts for consistency with the price chart.
 * X axis is underlying price (we map to integer "time" units inside
 * the library since lightweight-charts is fundamentally time-indexed —
 * for a payoff curve the X axis values are arbitrary as long as they're
 * monotonically increasing and unique).
 *
 * The gap between today and expiration curves IS the remaining time
 * value. Scrubber-driven analytics shrinks that gap, which is what
 * makes the theta-decay demo work.
 */
export function PayoffPanel({ analytics, loading }: Props) {
  return (
    <div className="flex flex-col h-full min-h-0">
      <Header analytics={analytics} loading={loading} />
      <div className="flex-1 min-h-0 relative">
        {!analytics ? (
          <EmptyState loading={!!loading} />
        ) : (
          <PayoffChart analytics={analytics} />
        )}
      </div>
      {analytics && <Readouts analytics={analytics} />}
    </div>
  );
}

function Header({
  analytics,
  loading,
}: {
  analytics: TradeAnalytics | null | undefined;
  loading?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between px-3 py-1.5 border-b border-hairline shrink-0">
      <div className="flex items-baseline gap-3">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Payoff
        </span>
        {analytics && (
          <span className="text-tiny text-fg-tertiary tabular-nums">
            T+{analytics.current_dte_days - analytics.scrubber_dte_days}d ·
            {" "}DTE {analytics.scrubber_dte_days}/{analytics.current_dte_days}
          </span>
        )}
      </div>
      {loading && (
        <span className="text-tiny text-fg-tertiary">computing…</span>
      )}
    </div>
  );
}

function EmptyState({ loading }: { loading: boolean }) {
  return (
    <div className="absolute inset-0 flex items-center justify-center text-tiny text-fg-tertiary">
      {loading ? "Loading analytics…" : "Select a trade to render its payoff curve."}
    </div>
  );
}

function Readouts({ analytics }: { analytics: TradeAnalytics }) {
  const a = analytics;
  return (
    <div className="grid grid-cols-4 gap-2 px-3 py-1.5 border-t border-hairline bg-tier-0 text-tiny tabular-nums shrink-0">
      <Cell label="Unrealized">
        <span className={pnlClass(a.unrealized_pnl)}>{formatDollar(a.unrealized_pnl)}</span>
      </Cell>
      <Cell label="Max gain">
        <span className="text-fg-primary">
          {a.unlimited_gain ? "∞" : formatDollar(a.max_profit ?? 0)}
        </span>
      </Cell>
      <Cell label="Max loss">
        <span className="text-bearish">
          {a.unlimited_loss ? "−∞" : formatDollar(a.max_loss ?? 0)}
        </span>
      </Cell>
      <Cell label="Breakevens">
        <span className="text-fg-primary">{formatBEs(a.breakevens_expiration)}</span>
      </Cell>
    </div>
  );
}

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col">
      <span className="text-fg-secondary uppercase tracking-label-up" style={{ fontSize: 9 }}>
        {label}
      </span>
      <span>{children}</span>
    </div>
  );
}

function PayoffChart({ analytics }: { analytics: TradeAnalytics }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const expirySeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const todaySeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const profitFillRef = useRef<ISeriesApi<"Area"> | null>(null);
  const lossFillRef = useRef<ISeriesApi<"Area"> | null>(null);
  const spotLineRef = useRef<IPriceLine[]>([]);

  // Create chart once.
  useEffect(() => {
    const host = containerRef.current;
    if (!host) return;
    const chart = createChart(host, {
      width: host.clientWidth,
      height: host.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: colors.bgTier0 },
        textColor: colors.fgSecondary,
        fontFamily:
          '"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
        fontSize: 10,
      },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      crosshair: {
        mode: CrosshairMode.Magnet,
        vertLine: { color: colors.fgTertiary, labelBackgroundColor: colors.bgTier1 },
        horzLine: { color: colors.fgTertiary, labelBackgroundColor: colors.bgTier1 },
      },
      timeScale: {
        borderColor: colors.borderHairline,
        // Payoff X axis is price, not time — turn off time-style ticks.
        timeVisible: false,
        secondsVisible: false,
        tickMarkFormatter: () => "",
      },
      rightPriceScale: {
        borderColor: colors.borderHairline,
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      handleScroll: false,
      handleScale: false,
    });
    chartRef.current = chart;

    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    });
    ro.observe(host);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      expirySeriesRef.current = null;
      todaySeriesRef.current = null;
      profitFillRef.current = null;
      lossFillRef.current = null;
      spotLineRef.current = [];
    };
  }, []);

  // Update curves whenever analytics changes (data refresh or scrubber).
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    // Map underlying prices to integer "time" units. lightweight-charts
    // is time-indexed; for a price axis we just need monotonic increasing
    // unique values. Index 0..N-1 works fine since the visible value
    // labels are formatted out (see timeScale.tickMarkFormatter). Cast
    // through UTCTimestamp because that's the only Time variant the
    // library's types accept for raw numeric values.
    const asTime = (i: number) => i as UTCTimestamp;
    const expData = analytics.prices.map((_p, i) => ({
      time: asTime(i),
      value: analytics.payoff_expiration[i],
    }));
    const todayData = analytics.prices.map((_p, i) => ({
      time: asTime(i),
      value: analytics.payoff_today[i],
    }));

    // Profit / loss faint fills under the expiration curve — readable at
    // a glance without yelling at the user.
    const profitFill = expData.map((d) => ({
      time: d.time,
      value: Math.max(d.value, 0),
    }));
    const lossFill = expData.map((d) => ({
      time: d.time,
      value: Math.min(d.value, 0),
    }));

    if (!profitFillRef.current) {
      profitFillRef.current = chart.addSeries(AreaSeries, {
        topColor: `${colors.bullish}26`,
        bottomColor: `${colors.bullish}00`,
        lineColor: "transparent",
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
    }
    profitFillRef.current.setData(profitFill);

    if (!lossFillRef.current) {
      lossFillRef.current = chart.addSeries(AreaSeries, {
        topColor: `${colors.bearish}00`,
        bottomColor: `${colors.bearish}26`,
        lineColor: "transparent",
        lineWidth: 1,
        invertFilledArea: true,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
    }
    lossFillRef.current.setData(lossFill);

    if (!expirySeriesRef.current) {
      expirySeriesRef.current = chart.addSeries(LineSeries, {
        color: colors.fgPrimary,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
    }
    expirySeriesRef.current.setData(expData);

    if (!todaySeriesRef.current) {
      todaySeriesRef.current = chart.addSeries(LineSeries, {
        color: POSITION_COLOR,
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
      });
    }
    todaySeriesRef.current.setData(todayData);

    // Spot price as a vertical reference. lightweight-charts only does
    // horizontal price lines natively, so we emulate the vertical by
    // adding a horizontal marker at $0 and rely on the user's eye to
    // pair price ↔ index from the value labels — UNLESS we add a
    // dedicated marker. Simpler: just label the spot in the readouts.

    // Horizontal zero line.
    for (const l of spotLineRef.current) {
      try {
        expirySeriesRef.current?.removePriceLine(l);
      } catch {
        /* ignore */
      }
    }
    spotLineRef.current = [];
    if (expirySeriesRef.current) {
      spotLineRef.current.push(
        expirySeriesRef.current.createPriceLine({
          price: 0,
          color: colors.fgTertiary,
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: false,
          title: "",
        }),
      );
    }

    chart.timeScale().fitContent();
  }, [analytics]);

  return <div ref={containerRef} className="h-full w-full" />;
}

function formatDollar(value: number): string {
  const sign = value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

function formatBEs(bes: number[]): string {
  if (bes.length === 0) return "—";
  return bes.map((b) => b.toFixed(2)).join(" / ");
}

function pnlClass(pnl: number): string {
  if (pnl > 0) return "text-bullish";
  if (pnl < 0) return "text-bearish";
  return "text-fg-secondary";
}
