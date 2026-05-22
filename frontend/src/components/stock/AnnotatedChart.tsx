import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

import { useTickerChart } from "@/hooks/useTickerChart";
import { colors } from "@/lib/design";
import type { BarPoint, ChartAnnotations, ChartTimeframe } from "@/types/chart";

const TIMEFRAMES: ChartTimeframe[] = ["1D", "5D", "1M", "3M"];

// Trade Desk position overlay — magenta is reserved for "MY POSITION"
// markers so it can't be confused with the six options-level annotations
// (EM amber, CW red, PW green, MP/GF cyan). One color, one meaning.
const POSITION_COLOR = "#D4537E";

export interface PositionOverlay {
  /** Trade primary key — drives marker text and id so dedupe is clean. */
  tradeId: number;
  entryDate: string;              // ISO datetime of the trade open
  entryPrice: number;             // underlying price at entry
  strategyLabel: string;          // human label, e.g. "Long straddle"
  /** Breakevens at the scrubber's DTE (today by default, scrubbed otherwise). */
  breakevensToday: number[];
  /** Breakevens at expiration — drawn as a fainter ghost so the user
   *  can see how far the live BE has moved due to theta. Optional. */
  breakevensExpiration?: number[];
  /** Label suffix used on the BE price line, e.g. "T+14d". */
  scrubberLabel?: string;
}

interface Props {
  symbol: string;
  controlledTimeframe?: {
    value: ChartTimeframe;
    onChange: (tf: ChartTimeframe) => void;
  };
  hideHeader?: boolean;
  /** Trade Desk Phase 2 — overlay the selected position's entry marker
   *  and theta-adjusted breakeven lines on the chart. */
  position?: PositionOverlay | null;
}

/**
 * Annotated chart — Phase 9f migration to lightweight-charts (v5).
 *
 * Phase-2 add: when `position` is provided, an entry marker drops at
 * the trade's entry (date, price) and one or more magenta breakeven
 * lines render at the scrubber's DTE. The lines move when the scrubber
 * moves because the parent recomputes them from the analytics endpoint
 * and re-passes a fresh `position` object.
 *
 * 1D timeframe renders as a line (intraday price path reads cleaner
 * than 1-min candles); multi-day timeframes render as candles.
 */
export function AnnotatedChart({ symbol, controlledTimeframe, hideHeader, position }: Props) {
  const [internalTimeframe, setInternalTimeframe] = useState<ChartTimeframe>("5D");
  const timeframe = controlledTimeframe?.value ?? internalTimeframe;
  const setTimeframe = controlledTimeframe?.onChange ?? setInternalTimeframe;
  const showInternalSelector = controlledTimeframe === undefined;
  const { data, isLoading, isError, error } = useTickerChart(symbol, timeframe);

  return (
    <div className="px-4 py-2 border-b border-hairline flex-1 min-h-0 flex flex-col">
      {!hideHeader && (
        <div className="flex items-center justify-between mb-2 shrink-0">
          <span className="text-xs2 uppercase tracking-label-up text-fg-secondary">
            {symbol} · {timeframe}
          </span>
          {showInternalSelector && (
            <div className="flex gap-1">
              {TIMEFRAMES.map((tf) => (
                <button
                  key={tf}
                  type="button"
                  onClick={() => setTimeframe(tf)}
                  className={[
                    "px-2 py-0.5 text-tiny border",
                    tf === timeframe
                      ? "border-amber text-amber bg-tier-1"
                      : "border-hairline text-fg-tertiary hover:bg-tier-2",
                  ].join(" ")}
                  style={{ borderRadius: 0 }}
                >
                  {tf}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex-1 min-h-0">
        {isLoading && <ChartSkeleton />}
        {isError && (
          <div className="text-tiny text-bearish">
            {(error as Error)?.message ?? "Failed to load chart"}
          </div>
        )}
        {data && data.bars.length > 0 && (
          <LightweightChart
            key={`${symbol}:${timeframe}`}
            bars={data.bars}
            annotations={data.annotations}
            timeframe={timeframe}
            position={position ?? null}
          />
        )}
      </div>

      {data && data.oi_source === "volume_proxy" && (
        <div className="text-tiny text-fg-tertiary mt-1 shrink-0">
          OI unavailable on free feed — walls / max-pain use today's volume as proxy
        </div>
      )}
    </div>
  );
}

interface ChartProps {
  bars: BarPoint[];
  annotations: ChartAnnotations;
  timeframe: ChartTimeframe;
  position: PositionOverlay | null;
}

function LightweightChart({ bars, annotations, timeframe, position }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | ISeriesApi<"Line"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const annotationLinesRef = useRef<IPriceLine[]>([]);
  const positionLinesRef = useRef<IPriceLine[]>([]);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

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
        fontSize: 11,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { visible: false },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: colors.fgTertiary,
          labelBackgroundColor: colors.bgTier1,
        },
        horzLine: {
          color: colors.fgTertiary,
          labelBackgroundColor: colors.bgTier1,
        },
      },
      timeScale: {
        borderColor: colors.borderHairline,
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: colors.borderHairline,
        scaleMargins: { top: 0.05, bottom: 0.25 },
      },
      handleScroll: true,
      handleScale: true,
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
      annotationLinesRef.current = [];
      positionLinesRef.current = [];
      markersRef.current = null;
      seriesRef.current = null;
      volumeRef.current = null;
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  // Bars + market-level annotations. Recreates series when bars/tf
  // changes (which is rare — outer key on symbol+tf already remounts
  // this whole component). The position overlay is handled by a
  // SEPARATE effect below so dragging the scrubber doesn't re-tear the
  // candlestick series 60× per second.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    if (seriesRef.current) {
      chart.removeSeries(seriesRef.current);
      seriesRef.current = null;
      annotationLinesRef.current = [];
      positionLinesRef.current = [];
      markersRef.current = null;
    }
    if (volumeRef.current) {
      chart.removeSeries(volumeRef.current);
      volumeRef.current = null;
    }

    const useLine = timeframe === "1D";

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "",
      color: colors.fgTertiary,
    });
    volume.priceScale().applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    volume.setData(
      bars.map((b) => ({
        time: toTime(b.t),
        value: b.v,
        color: b.c >= b.o ? `${colors.bullish}80` : `${colors.bearish}80`,
      })),
    );
    volumeRef.current = volume;

    if (useLine) {
      const line = chart.addSeries(LineSeries, {
        color: colors.fgPrimary,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      line.setData(bars.map((b) => ({ time: toTime(b.t), value: b.c })));
      seriesRef.current = line;
    } else {
      const candles = chart.addSeries(CandlestickSeries, {
        upColor: colors.bullish,
        downColor: colors.bearish,
        wickUpColor: colors.bullish,
        wickDownColor: colors.bearish,
        borderVisible: false,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      candles.setData(
        bars.map((b) => ({
          time: toTime(b.t),
          open: b.o,
          high: b.h,
          low: b.l,
          close: b.c,
        })),
      );
      seriesRef.current = candles;
    }

    annotationLinesRef.current = buildPriceLines(seriesRef.current, annotations);

    chart.timeScale().fitContent();
  }, [bars, annotations, timeframe]);

  // Position overlay — independent of the series lifecycle so the
  // scrubber can stream new BE values without redrawing candles.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    // Tear down any previous position overlay.
    for (const line of positionLinesRef.current) {
      try {
        series.removePriceLine(line);
      } catch {
        /* line already detached */
      }
    }
    positionLinesRef.current = [];
    if (markersRef.current) {
      markersRef.current.setMarkers([]);
    }

    if (!position) return;

    // Entry marker — clamped to the chart's visible time range so a
    // weeks-old entry that falls outside a 5D view still shows at the
    // left edge instead of vanishing off-screen.
    const entryT = toTime(position.entryDate);
    const firstBarT = bars.length > 0 ? toTime(bars[0].t) : entryT;
    const lastBarT = bars.length > 0 ? toTime(bars[bars.length - 1].t) : entryT;
    const clampedT = (Math.min(
      Math.max(entryT as number, firstBarT as number),
      lastBarT as number,
    ) as unknown) as UTCTimestamp;

    const markers: SeriesMarker<Time>[] = [
      {
        time: clampedT,
        position: "belowBar",
        color: POSITION_COLOR,
        shape: "arrowUp",
        text: `ENTRY · ${position.strategyLabel}`,
        size: 1,
      },
    ];
    if (markersRef.current == null) {
      markersRef.current = createSeriesMarkers(series, markers);
    } else {
      markersRef.current.setMarkers(markers);
    }

    // Breakeven price lines at the scrubber's DTE (the live one). Drawn
    // as solid magenta — distinctively NOT in the amber/red/green/cyan
    // palette used for market-structure annotations.
    const beLabel = position.scrubberLabel ? `BE ${position.scrubberLabel}` : "BE";
    for (const be of position.breakevensToday) {
      positionLinesRef.current.push(
        series.createPriceLine({
          price: be,
          color: POSITION_COLOR,
          lineStyle: LineStyle.Solid,
          lineWidth: 2,
          axisLabelVisible: true,
          title: beLabel,
        }),
      );
    }

    // Optional expiration BE — drawn as a faint dotted ghost so the eye
    // can see how far the live BE has moved due to theta. We don't show
    // it if it overlaps the live BE (scrubber == 0 or position has no
    // time value left).
    if (position.breakevensExpiration && position.breakevensExpiration.length > 0) {
      for (const be of position.breakevensExpiration) {
        const closeToLive = position.breakevensToday.some(
          (live) => Math.abs(live - be) < 0.05,
        );
        if (closeToLive) continue;
        positionLinesRef.current.push(
          series.createPriceLine({
            price: be,
            color: POSITION_COLOR,
            lineStyle: LineStyle.Dotted,
            lineWidth: 1,
            axisLabelVisible: true,
            title: "BE expiry",
          }),
        );
      }
    }
  }, [position, bars]);

  return <div ref={containerRef} className="h-full w-full" />;
}

function buildPriceLines(
  series: ISeriesApi<"Candlestick"> | ISeriesApi<"Line">,
  a: ChartAnnotations,
): IPriceLine[] {
  const lines: IPriceLine[] = [];
  const addLine = (
    price: number | null | undefined,
    color: string,
    style: LineStyle,
    label: string,
  ) => {
    if (price == null) return;
    lines.push(
      series.createPriceLine({
        price,
        color,
        lineStyle: style,
        lineWidth: 1,
        axisLabelVisible: true,
        title: label,
      }),
    );
  };

  addLine(a.expected_move_upper, colors.accentAmber, LineStyle.Dashed, "EM+");
  addLine(a.expected_move_lower, colors.accentAmber, LineStyle.Dashed, "EM-");
  if (a.call_wall) {
    addLine(a.call_wall.strike, colors.bearish, LineStyle.Solid, "CW");
  }
  if (a.put_wall) {
    addLine(a.put_wall.strike, colors.bullish, LineStyle.Solid, "PW");
  }
  addLine(a.max_pain, colors.accentCyan, LineStyle.Dashed, "MP");
  addLine(a.gamma_flip, colors.accentCyan, LineStyle.Dashed, "GF");

  return lines;
}

function toTime(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

function ChartSkeleton() {
  return (
    <div
      className="h-full w-full bg-tier-1 border border-hairline"
      aria-hidden
    />
  );
}
