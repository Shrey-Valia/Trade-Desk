import { useEffect, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";

import { colors } from "@/lib/design";
import type { EquityPoint } from "@/types/analytics";

interface Props {
  points: EquityPoint[];
}

/**
 * Equity curve — cumulative realized P&L over time. Same library as the
 * price chart for visual consistency. Series color is the live P&L
 * semantic: gain-line in fg-primary (we're agnostic to win/loss until
 * the cursor lands somewhere specific), with a zero baseline in
 * fg-tertiary so the eye can compare against break-even.
 */
export function EquityChart({ points }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

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
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: colors.fgTertiary, labelBackgroundColor: colors.bgTier1 },
        horzLine: { color: colors.fgTertiary, labelBackgroundColor: colors.bgTier1 },
      },
      timeScale: {
        borderColor: colors.borderHairline,
        timeVisible: false,
        secondsVisible: false,
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
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (!seriesRef.current) {
      seriesRef.current = chart.addSeries(LineSeries, {
        color: colors.fgPrimary,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      seriesRef.current.createPriceLine({
        price: 0,
        color: colors.fgTertiary,
        lineStyle: LineStyle.Solid,
        lineWidth: 1,
        axisLabelVisible: false,
        title: "",
      });
    }

    // Multiple trades can close on the same calendar day. The equity
    // curve treats each trade as its own discrete step, but
    // lightweight-charts rejects duplicate time values on a line
    // series. Add the row index as seconds so every point gets a unique
    // timestamp; visually-imperceptible offset, real ordering preserved.
    seriesRef.current.setData(
      points.map((p, i) => ({
        time: toTime(p.date, i),
        value: p.cumulative_pnl,
      })),
    );

    chart.timeScale().fitContent();
  }, [points]);

  if (points.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-tiny text-fg-tertiary">
        No closed trades yet — equity curve appears once trades close.
      </div>
    );
  }

  return <div ref={containerRef} className="h-full w-full" />;
}

function toTime(iso: string, offset: number = 0): UTCTimestamp {
  // Equity points carry a date string like "2026-05-21"; convert to a
  // mid-day UTC timestamp so the lightweight-charts time axis treats
  // each entry as a distinct day. `offset` (seconds) tie-breaks rows
  // that fall on the same calendar day so the series stays monotonic.
  const ts = Math.floor(new Date(`${iso}T12:00:00Z`).getTime() / 1000) + offset;
  return ts as UTCTimestamp;
}
