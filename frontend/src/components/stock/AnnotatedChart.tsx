import { lazy, Suspense, useEffect, useRef, useState } from "react";
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

import { useTickerAnnotations, useTickerChart } from "@/hooks/useTickerChart";
import { useTickerIndicators } from "@/hooks/useTickerIndicators";
import { useMarketStatus } from "@/hooks/useMarket";
import { useTickerDetail } from "@/hooks/useTickerDetail";
import { colors } from "@/lib/design";
import { useChartPrefs } from "@/stores/chartPrefs";
import { enabledSetParam, useIndicators } from "@/stores/indicators";
import { useUserSettings } from "@/stores/userSettings";
import {
  CHART_TIMEFRAMES,
  DEFAULT_CHART_TIMEFRAME,
  type BarPoint,
  type ChartAnnotations,
  type ChartTimeframe,
} from "@/types/chart";
import type { IndicatorSeries } from "@/types/indicators";

import { PositionBracketsLayer, type BracketOverlay } from "./PositionBracketsLayer";
import { ChartLegend } from "./ChartLegend";

// The drawing-tools engine (~44 KB gzip) is code-split so it loads only with
// the chart, not on every page. Rendered behind Suspense with a null fallback —
// the chart paints immediately and the toolbar appears a beat later.
const ChartDrawingLayer = lazy(() =>
  import("./ChartDrawingLayer").then((m) => ({ default: m.ChartDrawingLayer })),
);

const TIMEFRAMES: readonly ChartTimeframe[] = CHART_TIMEFRAMES;

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
  /** Pre-formatted unrealized P&L string (e.g. "+$42.18" or "−$104.50").
   *  When present, gets appended to each BE line's title so the right-
   *  axis pill becomes "BE +$42.18" — the line IS the live P&L readout. */
  uplLabel?: string;
  /** Sign of the position's unrealized P&L — colors the breakeven line
   *  green when ≥ 0, red when < 0. Defaults to green when omitted. */
  uplPositive?: boolean;
}

interface Props {
  symbol: string;
  controlledTimeframe?: {
    value: ChartTimeframe;
    onChange: (tf: ChartTimeframe) => void;
  };
  hideHeader?: boolean;
  /** All open positions on the charted symbol — each renders an entry
   *  marker + theta-adjusted breakeven lines (BE colored by its own P&L
   *  sign). The header/store track which one is "selected" for brackets. */
  positions?: PositionOverlay[];
  /** Draggable SL/TP brackets for the SELECTED open position (null = none). */
  brackets?: BracketOverlay | null;
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
export function AnnotatedChart({ symbol, controlledTimeframe, hideHeader, positions, brackets }: Props) {
  const [internalTimeframe, setInternalTimeframe] = useState<ChartTimeframe>(
    DEFAULT_CHART_TIMEFRAME,
  );
  const timeframe = controlledTimeframe?.value ?? internalTimeframe;
  const setTimeframe = controlledTimeframe?.onChange ?? setInternalTimeframe;
  const showInternalSelector = controlledTimeframe === undefined;
  // Bars query — fast. Drives the candle render.
  const bars = useTickerChart(symbol, timeframe);
  // Annotations query — slower (options-chain dependency). Drawn as
  // overlay lines when it resolves. The chart does NOT wait for this.
  const annotations = useTickerAnnotations(symbol, timeframe);

  // --- WS1: technical indicators -----------------------------------------
  // Enabled indicator set (persisted store) -> query -> per-bar series.
  // Drawn as LineSeries by a dedicated effect inside LightweightChart.
  const enabledIndicators = useIndicators((s) => s.enabled);
  const indicatorSet = enabledSetParam(enabledIndicators);
  const indicators = useTickerIndicators(symbol, timeframe, indicatorSet);
  const indicatorSeries = indicators.data?.series ?? EMPTY_INDICATOR_SERIES;
  // --- end WS1 -----------------------------------------------------------

  // Synthetic in-progress candle inputs — REUSE the existing quote
  // (header price, 5s poll) and market-status (60s poll) queries; both
  // share their react-query keys so this adds NO request volume. The
  // quote is still ~15-min delayed on the free feed — this only makes
  // the last candle tick between bar boundaries, it does not relabel
  // delayed data as real-time.
  const quote = useTickerDetail(symbol);
  const market = useMarketStatus();
  const quotePrice = quote.data?.price ?? null;
  const marketOpen = market.data?.status === "open";

  const data = bars.data;
  const annotationData = annotations.data?.annotations;

  return (
    <div className="px-3 py-1.5 border-b border-hairline flex-1 min-h-0 flex flex-col">
      {!hideHeader && (
        <div className="flex items-center justify-between mb-1.5 shrink-0">
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

      <div className="flex-1 min-h-0 relative">
        {bars.isLoading && !data && <ChartSkeleton symbol={symbol} />}
        {bars.isError && (
          <div className="text-tiny text-bearish px-2 py-2">
            {(bars.error as Error)?.message ?? "Failed to load chart"}
          </div>
        )}
        {data && data.bars.length === 0 && !bars.isLoading && !bars.isError && (
          <div className="h-full flex items-center justify-center text-tiny text-fg-tertiary px-4 text-center">
            No {timeframe} bars for {symbol} right now — try another timeframe.
          </div>
        )}
        {data && data.bars.length > 0 && (
          <>
            <LightweightChart
              symbol={symbol}
              bars={data.bars}
              annotations={annotationData ?? EMPTY_ANNOTATIONS}
              timeframe={timeframe}
              positions={positions ?? EMPTY_POSITIONS}
              brackets={brackets ?? null}
              quotePrice={quotePrice}
              marketOpen={marketOpen}
              indicatorSeries={indicatorSeries}
            />
            <ChartLegend hasActivePosition={(positions?.length ?? 0) > 0} />
          </>
        )}
      </div>

      {annotations.data && annotations.data.oi_source === "volume_proxy" && (
        <div className="text-tiny text-fg-tertiary mt-1 shrink-0">
          OI unavailable on free feed — walls / max-pain use today's volume as proxy
        </div>
      )}
    </div>
  );
}

// Empty annotations placeholder so the chart can render bars before the
// slower annotations query resolves. Once annotations arrive, the
// overlay effect adds the price lines without redrawing candles.
const EMPTY_ANNOTATIONS: ChartAnnotations = {
  expected_move_upper: null,
  expected_move_lower: null,
  call_wall: null,
  put_wall: null,
  max_pain: null,
  gamma_flip: null,
  earnings_date: null,
};

// Stable empty array so a no-position render doesn't churn the overlay effect.
const EMPTY_POSITIONS: PositionOverlay[] = [];

// WS1: stable empty default so the indicators effect has a no-op input
// before the (or when no) indicator query resolves. A shared constant
// keeps the prop reference stable across renders (no needless effect runs).
const EMPTY_INDICATOR_SERIES: IndicatorSeries[] = [];

interface ChartProps {
  symbol: string;
  bars: BarPoint[];
  annotations: ChartAnnotations;
  timeframe: ChartTimeframe;
  positions: PositionOverlay[];
  brackets: BracketOverlay | null;
  /** Latest (delayed) quote from the shared header price query. */
  quotePrice?: number | null;
  /** Whether the market is open — gates the synthetic in-progress candle. */
  marketOpen?: boolean;
  /** WS1: enabled technical-indicator series, aligned to `bars`. */
  indicatorSeries?: IndicatorSeries[];
}

function LightweightChart({
  symbol,
  bars,
  annotations,
  timeframe,
  positions,
  brackets,
  quotePrice = null,
  marketOpen = false,
  indicatorSeries = EMPTY_INDICATOR_SERIES,
}: ChartProps) {
  const showMarketAnnotations = useChartPrefs((s) => s.showMarketAnnotations);
  const userBullish = useUserSettings((s) => s.bullishColor);
  const userBearish = useUserSettings((s) => s.bearishColor);
  const gridOpacity = useUserSettings((s) => s.gridOpacity);
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const annotationLinesRef = useRef<IPriceLine[]>([]);
  const positionLinesRef = useRef<IPriceLine[]>([]);
  // WS1: one LineSeries per enabled indicator, keyed by indicator key so
  // the effect can diff add/remove without rebuilding everything.
  const indicatorSeriesRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  // Synthetic in-progress candle: the current slot timestamp + running
  // open/high/low so quote ticks update one bar in place (close = quote).
  const syntheticRef = useRef<{
    time: UTCTimestamp;
    o: number;
    h: number;
    l: number;
  } | null>(null);
  // Resets the synthetic candle when the symbol changes.
  const syntheticSymbolRef = useRef<string>(symbol);

  // The bars effect tears down + recreates the candle series whenever
  // bars / timeframe / candle colors change. The position effect alone
  // can't re-attach the BE overlay across those rebuilds because its
  // deps are `[position]`, which doesn't change on a timeframe click.
  // We fix the gap by giving the bars effect an inline attach using
  // refs that hold the latest position + bars from the most recent
  // render. The refs avoid putting position/bars in the bars-effect
  // deps, which would otherwise tear down the candle series on every
  // scrubber tick.
  const positionsRef = useRef<PositionOverlay[]>(positions);
  positionsRef.current = positions;
  const barsRef = useRef<BarPoint[]>(bars);
  barsRef.current = bars;

  function attachPositionOverlay(
    series: ISeriesApi<"Candlestick">,
    list: PositionOverlay[],
    barsList: BarPoint[],
  ): void {
    // Tear down any prior overlay attached to this series. After a
    // bars-effect rebuild the refs may already be empty (the old
    // series was removed, taking its priceLines with it) — the loop
    // is a defensive no-op in that case.
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
    if (!list.length) return;

    // Visible range for clamping old entry markers to the left edge.
    const firstBarT = barsList.length > 0 ? (toTime(barsList[0].t) as number) : null;
    const lastBarT =
      barsList.length > 0 ? (toTime(barsList[barsList.length - 1].t) as number) : null;

    const markers: SeriesMarker<Time>[] = [];
    for (const p of list) {
      // Entry marker (magenta = "my position") — clamped into the visible
      // range so a weeks-old entry still shows at the left edge.
      const entryT = toTime(p.entryDate) as number;
      const clampedT = (
        firstBarT != null && lastBarT != null
          ? Math.min(Math.max(entryT, firstBarT), lastBarT)
          : entryT
      ) as unknown as UTCTimestamp;
      markers.push({
        time: clampedT,
        position: "belowBar",
        color: POSITION_COLOR,
        shape: "arrowUp",
        text: `ENTRY · ${p.strategyLabel}`,
        size: 1,
      });

      // Breakeven lines — colored by THIS position's P&L sign so the line
      // itself reads green (in profit) / red (in loss).
      const beColor = p.uplPositive === false ? userBearish : userBullish;
      const beTitle = p.uplLabel ? `BE ${p.uplLabel}` : "BE";
      for (const be of p.breakevensToday) {
        positionLinesRef.current.push(
          series.createPriceLine({
            price: be,
            color: beColor,
            lineStyle: LineStyle.Solid,
            lineWidth: 2,
            axisLabelVisible: true,
            title: beTitle,
          }),
        );
      }
    }

    // The markers plugin requires ascending time order across all positions.
    markers.sort((a, b) => (a.time as number) - (b.time as number));
    if (markersRef.current == null) {
      markersRef.current = createSeriesMarkers(series, markers);
    } else {
      markersRef.current.setMarkers(markers);
    }
  }

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
        // Apache-2.0 license requires attribution; we satisfy it in
        // README + on-screen "OPTIONS · FUTURES · TERMINAL" tagline
        // rather than the corner watermark, which competes visually
        // with our position annotations.
        attributionLogo: false,
      },
      grid: {
        vertLines: {
          visible: gridOpacity > 0,
          color: alphaHex(colors.borderHairline, gridOpacity / 100),
        },
        horzLines: {
          visible: gridOpacity > 0,
          color: alphaHex(colors.borderHairline, gridOpacity / 100),
        },
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
      // WS1: chart.remove() drops all series including indicator lines;
      // just clear the bookkeeping map so the next chart starts clean.
      indicatorSeriesRef.current.clear();
      markersRef.current = null;
      seriesRef.current = null;
      volumeRef.current = null;
      chart.remove();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Live grid opacity updates without recreating the chart.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const c = alphaHex(colors.borderHairline, gridOpacity / 100);
    chart.applyOptions({
      grid: {
        vertLines: { visible: gridOpacity > 0, color: c },
        horzLines: { visible: gridOpacity > 0, color: c },
      },
    });
  }, [gridOpacity]);

  // Bars + market-level annotations. Recreates series when bars,
  // timeframe, or candle colors change. The position overlay is
  // re-attached INLINE at the end of this effect so the BE survives
  // a timeframe click — see attachPositionOverlay() above for the
  // race this fixes. The position effect below handles the
  // independent scrubber path (position changes without a series
  // rebuild).
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
        color: b.c >= b.o ? `${userBullish}80` : `${userBearish}80`,
      })),
    );
    volumeRef.current = volume;

    // Candles for every timeframe. The legacy code rendered the "1D"
    // backend timeframe as a LineSeries (intended for 1-minute intraday
    // bars). The Trade-Desk redesign routes every toolbar button — 1m
    // through 1D — to the backend's daily bars via TF_REAL_MAP, so the
    // line-mode branch turned every click into a line chart. The chart
    // type stub in the toolbar will own line / area later.
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: userBullish,
      downColor: userBearish,
      wickUpColor: userBullish,
      wickDownColor: userBearish,
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

    // Market-structure annotations are managed by a separate effect
    // below so the toggle doesn't rebuild the candle series.
    annotationLinesRef.current = [];

    chart.timeScale().fitContent();

    // Re-attach the position overlay (entry marker + BE lines) to
    // the freshly-created series. Reads from refs so changes to
    // position / bars during a scrubber tick don't add deps that
    // would tear down the candle series on every move. Without this
    // call the BE disappears on every timeframe click — see
    // VERIFY_BE_REPORT.md's condition 5.
    attachPositionOverlay(candles, positionsRef.current, barsRef.current);
    // attachPositionOverlay is an in-component helper closing over the candle
    // colors (already in deps); the overlay is re-attached from refs here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, annotations, timeframe, userBullish, userBearish]);

  // ======================================================================
  // WS1 — technical indicator overlays
  //
  // Self-contained block (placed AFTER the candles/volume effect, BEFORE
  // the position-overlay effects) so it merges cleanly with WS3's
  // loading/error-state edits elsewhere in this file.
  //
  // SMA/EMA/VWAP share the main RIGHT price scale (overlaid on candles).
  // RSI gets its own pane via priceScaleId "rsi" pinned to a 0–100 axis;
  // ATR gets its own pane via priceScaleId "atr". The panes are squeezed
  // into the bottom of the chart with scaleMargins so they don't fight
  // the candles for vertical space.
  //
  // Indicator values are aligned 1:1 with `bars` (same timestamps), with
  // `null` warm-up gaps that lightweight-charts simply skips. We diff the
  // enabled set against the live series map so toggling one indicator
  // doesn't rebuild the others — and crucially does NOT touch the candle
  // series, markers, or BE price lines.
  // ======================================================================
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const live = indicatorSeriesRef.current;
    const wanted = new Set(indicatorSeries.map((s) => s.key));

    // Remove series that are no longer enabled.
    for (const [key, series] of live) {
      if (!wanted.has(key)) {
        try {
          chart.removeSeries(series);
        } catch {
          /* series already detached (chart rebuild) */
        }
        live.delete(key);
      }
    }

    // Add / update the enabled series.
    for (const s of indicatorSeries) {
      const color = INDICATOR_COLORS[s.key] ?? colors.accentCyan;
      let series = live.get(s.key);
      if (!series) {
        series = chart.addSeries(LineSeries, {
          color,
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: s.pane !== "price",
          // RSI/ATR live in their own pane via a dedicated price scale;
          // price-pane indicators ride the main right scale.
          priceScaleId: PANE_SCALE_ID[s.pane] ?? "right",
          ...(s.pane === "oscillator"
            ? { priceFormat: { type: "price" as const, precision: 0, minMove: 1 } }
            : {}),
        });
        // Squeeze the oscillator/volatility panes into the lower band so
        // they don't overlap the candles; pin RSI to a fixed 0–100 range.
        if (s.pane === "oscillator") {
          series.priceScale().applyOptions({
            scaleMargins: { top: 0.78, bottom: 0.0 },
            autoScale: false,
          });
          series.applyOptions({
            autoscaleInfoProvider: () => ({
              priceRange: { minValue: 0, maxValue: 100 },
            }),
          });
        } else if (s.pane === "volatility") {
          series.priceScale().applyOptions({
            scaleMargins: { top: 0.85, bottom: 0.0 },
          });
        }
        live.set(s.key, series);
      } else {
        series.applyOptions({ color });
      }

      series.setData(
        bars
          .map((b, i) => {
            const v = s.values[i];
            return v == null ? null : { time: toTime(b.t), value: v };
          })
          .filter((p): p is { time: UTCTimestamp; value: number } => p !== null),
      );
    }
    // Depend on `bars` so a timeframe switch / bars refetch re-aligns the
    // overlay data; `indicatorSeries` covers toggle changes.
  }, [indicatorSeries, bars]);
  // ===================== end WS1 indicator overlays =====================

  // Market-structure annotation overlay — toggle-aware.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    for (const line of annotationLinesRef.current) {
      try {
        series.removePriceLine(line);
      } catch {
        /* line already detached */
      }
    }
    annotationLinesRef.current = showMarketAnnotations
      ? buildPriceLines(series, annotations)
      : [];
  }, [annotations, showMarketAnnotations]);

  // Position overlay — handles the scrubber path (position changes
  // while the candle series is stable). Bars-change re-attach is done
  // inline in the bars effect above so the BE survives timeframe
  // clicks; we deliberately omit `bars` from this dep array to avoid
  // a double-attach race when bars + position both update in the same
  // commit.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    attachPositionOverlay(series, positions, barsRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [positions]);

  // Synthetic in-progress candle — REUSES the 5s header quote so the
  // last candle ticks between bar boundaries. Declared AFTER the bars
  // effect so on a bars change it runs once the series has been rebuilt.
  //
  // Pinned to the data's LEADING EDGE (lastRealBar.time + one interval),
  // NOT wall-clock: this keeps it honest about the ~15-min feed delay and
  // makes reconciliation automatic. The 60s bars refetch rebuilds the
  // series via setData (wiping this candle); this effect re-runs and
  // re-appends exactly ONE trailing candle. So when the authoritative
  // real bar for a slot finally arrives in `bars`, setData places it and
  // the synthetic advances one slot — the real bar REPLACES the synthetic
  // with no duplicate and no drift.
  //
  // Touches ONLY the candle's last bar via series.update() — never
  // setData, and never the marker / BE price lines, so attachPositionOverlay
  // and its ref lifecycle are completely untouched. Gated to intraday
  // timeframes and market-open so we don't draw a fake candle when nothing
  // is in progress.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    if (syntheticSymbolRef.current !== symbol) {
      syntheticSymbolRef.current = symbol;
      syntheticRef.current = null;
    }

    const intervalSec = INTERVAL_SECONDS[timeframe];
    if (
      intervalSec == null ||
      !marketOpen ||
      quotePrice == null ||
      !Number.isFinite(quotePrice) ||
      bars.length === 0
    ) {
      syntheticRef.current = null;
      return;
    }

    const lastReal = bars[bars.length - 1];
    const lastRealT = toTime(lastReal.t);
    const slotT = (lastRealT + intervalSec) as UTCTimestamp;

    const prev = syntheticRef.current;
    const next =
      prev && prev.time === slotT
        ? {
            time: slotT,
            o: prev.o,
            h: Math.max(prev.h, quotePrice),
            l: Math.min(prev.l, quotePrice),
          }
        : {
            // Fresh slot / boundary rollover: carry the open from the
            // last real bar's close; seed high/low from open + quote.
            time: slotT,
            o: lastReal.c,
            h: Math.max(lastReal.c, quotePrice),
            l: Math.min(lastReal.c, quotePrice),
          };
    syntheticRef.current = next;

    series.update({
      time: slotT,
      open: next.o,
      high: next.h,
      low: next.l,
      close: quotePrice,
    });
  }, [quotePrice, bars, timeframe, marketOpen, symbol]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />
      <Suspense fallback={null}>
        <ChartDrawingLayer chartRef={chartRef} seriesRef={seriesRef} symbol={symbol} />
      </Suspense>
      {brackets && (
        <PositionBracketsLayer chartRef={chartRef} seriesRef={seriesRef} brackets={brackets} />
      )}
    </div>
  );
}

// Market-structure annotations are SECONDARY to the user's position.
// Lines + their right-edge axis pills are drawn with reduced alpha so
// candles dominate visually and the magenta position lines remain the
// loudest overlay. Hex+alpha keeps the DESIGN.md semantic palette but
// dims it to ~33% on the line and ~25% on the label background.
const ANNOT_LINE_ALPHA = "55";   // ~33% — dotted thin line, calm in the gutter
const ANNOT_LABEL_BG_ALPHA = "40"; // ~25% — pill background; text reads via fgPrimary

function buildPriceLines(
  series: ISeriesApi<"Candlestick">,
  a: ChartAnnotations,
): IPriceLine[] {
  const lines: IPriceLine[] = [];
  const addLine = (
    price: number | null | undefined,
    color: string,
    label: string,
  ) => {
    if (price == null) return;
    lines.push(
      series.createPriceLine({
        price,
        color: `${color}${ANNOT_LINE_ALPHA}`,
        lineStyle: LineStyle.Dotted,
        lineWidth: 1,
        axisLabelVisible: true,
        axisLabelColor: `${color}${ANNOT_LABEL_BG_ALPHA}`,
        axisLabelTextColor: colors.fgPrimary,
        title: label,
      }),
    );
  };

  addLine(a.expected_move_upper, colors.accentAmber, "EM+");
  addLine(a.expected_move_lower, colors.accentAmber, "EM-");
  if (a.call_wall) {
    addLine(a.call_wall.strike, colors.bearish, "CW");
  }
  if (a.put_wall) {
    addLine(a.put_wall.strike, colors.bullish, "PW");
  }
  addLine(a.max_pain, colors.accentCyan, "MP");
  addLine(a.gamma_flip, colors.accentCyan, "GF");

  return lines;
}

function toTime(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

// Seconds per candle interval, by timeframe — drives the synthetic
// in-progress candle's slot width. "1D" is intentionally absent: a
// quote-driven intraday tick on a daily candle would misrepresent the
// time axis, so the synthetic candle only applies to intraday grains.
const INTERVAL_SECONDS: Partial<Record<ChartTimeframe, number>> = {
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "1h": 3600,
  "4h": 14400,
};

// WS1: per-indicator line colors. Chosen from the design palette so the
// overlays read as distinct from the magenta POSITION line and the
// candle bullish/bearish hues. Single source of truth for the hex lives
// here, next to the chart that draws it.
const INDICATOR_COLORS: Record<string, string> = {
  sma20: colors.accentAmber,
  ema50: colors.accentCyan,
  vwap: colors.fgSecondary,
  rsi14: colors.accentCyan,
  atr14: colors.warning,
};

// WS1: which price scale each pane binds to. "price" rides the main
// right scale (overlaid on candles); the oscillator/volatility panes get
// their own hidden scales so RSI's 0–100 range and ATR's absolute range
// don't distort the price axis.
const PANE_SCALE_ID: Record<string, string> = {
  price: "right",
  oscillator: "rsi",
  volatility: "atr",
};

/** Compose a #RRGGBBAA from #RRGGBB + 0..1 opacity. Falls back to the
 *  base hex if input doesn't parse. */
function alphaHex(hex: string, opacity: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return hex;
  const a = Math.max(0, Math.min(1, opacity));
  const aa = Math.round(a * 255)
    .toString(16)
    .padStart(2, "0");
  return `#${m[1]}${aa}`;
}

function ChartSkeleton({ symbol }: { symbol: string }) {
  return (
    <div
      className="h-full w-full bg-tier-1 border border-hairline flex items-center justify-center"
      role="status"
      aria-live="polite"
    >
      <div className="flex flex-col items-center gap-2 text-fg-secondary">
        <div className="flex gap-1">
          <span className="w-1.5 h-1.5 bg-fg-tertiary animate-pulse" />
          <span
            className="w-1.5 h-1.5 bg-fg-tertiary animate-pulse"
            style={{ animationDelay: "120ms" }}
          />
          <span
            className="w-1.5 h-1.5 bg-fg-tertiary animate-pulse"
            style={{ animationDelay: "240ms" }}
          />
        </div>
        <span
          className="text-tiny uppercase tracking-label-up"
          style={{ fontSize: 11, letterSpacing: "0.08em" }}
        >
          Loading {symbol} chart…
        </span>
      </div>
    </div>
  );
}
