import { useEffect, useMemo, useRef, useState } from "react";

import { UIButton } from "@/components/ui/UIButton";
import { VolRegimeStrip } from "@/components/stock/VolRegimeStrip";
import { useMarketStatus } from "@/hooks/useMarket";
import { useTickerChart } from "@/hooks/useTickerChart";
import { useChartPrefs } from "@/stores/chartPrefs";
import { useIndicators } from "@/stores/indicators";
import { clampPeriod, useIndicatorPeriods } from "@/stores/indicatorPeriods";
import { CHART_TIMEFRAMES, type ChartTimeframe } from "@/types/chart";
import {
  INDICATOR_CATALOG,
  MAX_INDICATOR_PERIOD,
  MIN_INDICATOR_PERIOD,
} from "@/types/indicators";

// Seconds per candle interval — mirrors AnnotatedChart's private
// INTERVAL_SECONDS (the synthetic-candle slot width). "1D" is absent:
// no synthetic candle there, so the countdown hides for it too. These
// interval lengths are canonical and never change, so the small
// duplication is safe and avoids coupling to the chart-engine file.
const TF_INTERVAL_SECONDS: Partial<Record<ChartTimeframe, number>> = {
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "1h": 3600,
  "4h": 14400,
};

/**
 * TradingView-style chart chrome — toolbar (36px) + OHLC strip (20px).
 *
 * Toolbar: timeframes (1m / 5m / 15m / 1h / 4h / 1D) — all wired to
 * real backend timeframes (the backend's _TIMEFRAME_CONFIG maps each
 * to its candle interval + lookback). Digit keys 1-6 switch them too
 * (handler lives in PositionsPage). Candle-type / drawing / indicator
 * stubs are block-commented below until those features are real.
 *
 * OHLC strip reads the most-recent bar from useTickerChart to populate
 * O/H/L/C and computes change vs prior close. Right-edge change number
 * is color-coded.
 *
 * The legend toggle (formerly an on-chart overlay) is retired from the
 * chart and surfaced compactly on the right side of the toolbar.
 */
interface Props {
  symbol: string | null;
  timeframe: ChartTimeframe;
  onTimeframeChange: (tf: ChartTimeframe) => void;
}

// Standard TradingView/Topstep timeframe ladder. Each button is the
// candle interval; backend's _TIMEFRAME_CONFIG handles the lookback
// window auto-scaling. Single source of truth lives in types/chart.ts
// so the toolbar, Settings picker, and persisted-store normalize off
// the same list.
const TF_OPTIONS: readonly ChartTimeframe[] = CHART_TIMEFRAMES;

export function ChartToolbar({ symbol, timeframe, onTimeframeChange }: Props) {
  return (
    <div className="shrink-0 bg-tier-1 border-b border-hairline">
      <Toolbar timeframe={timeframe} onTimeframeChange={onTimeframeChange} />
      <OhlcStrip symbol={symbol} timeframe={timeframe} />
      {/* WS1: compact vol-regime readout — surfaces IVR / skew / VRP from
          the existing /metrics endpoint right under the OHLC strip. */}
      <VolRegimeStrip symbol={symbol} />
    </div>
  );
}

function Toolbar({
  timeframe,
  onTimeframeChange,
}: {
  timeframe: ChartTimeframe;
  onTimeframeChange: (tf: ChartTimeframe) => void;
}) {
  return (
    <div
      className="flex items-center px-3 overflow-x-auto"
      style={{ height: 36, gap: 0 }}
      role="toolbar"
      aria-label="Chart toolbar"
    >
      {/* Timeframes — tight group, no internal separator. */}
      <div className="flex" style={{ gap: 4 }}>
        {TF_OPTIONS.map((tf, i) => {
          const active = timeframe === tf;
          return (
            <UIButton
              key={tf}
              size="sm"
              active={active}
              aria-pressed={active}
              onClick={() => onTimeframeChange(tf)}
              title={`${tf} bars · press ${i + 1}`}
              className="min-w-[36px]"
            >
              {tf}
            </UIButton>
          );
        })}
      </div>
      <ToolbarSeparator />
      <IndicatorChips />
      <div className="ml-auto flex items-center" style={{ gap: 6 }}>
        <LegendToggle />
        <MarketStructToggleHint />
      </div>
      <span className="sr-only">{timeframe}</span>
    </div>
  );
}

/** Thin vertical rule separating toolbar groups. */
function ToolbarSeparator() {
  return (
    <span
      aria-hidden
      className="self-center"
      style={{ width: 1, height: 16, background: "#2B2F37", marginInline: 8 }}
    />
  );
}

/**
 * Indicator toggle chips — one per family in INDICATOR_CATALOG. Toggling a
 * chip flips the persisted indicators store; AnnotatedChart reads the same
 * store, builds `family:period` tokens, fetches the set, and attaches a
 * LineSeries per enabled indicator (SMA/EMA/VWAP on the price pane; RSI/ATR
 * in their own real panes). Active chips use the amber ACTIVE/SELECTED token.
 *
 * Parameterizable families (everything but VWAP) carry a tiny period badge
 * that opens an inline numeric input — changing the window writes the
 * persisted indicatorPeriods store, which re-keys the query and refetches
 * just that series. The badge shows the live period so "SMA · 20" reads at a
 * glance.
 */
function IndicatorChips() {
  const enabled = useIndicators((s) => s.enabled);
  const toggle = useIndicators((s) => s.toggle);
  const periodFor = useIndicatorPeriods((s) => s.periodFor);
  // Subscribe to the periods map so the badge re-renders on a window change.
  useIndicatorPeriods((s) => s.periods);
  return (
    <div className="flex" style={{ gap: 4 }} role="group" aria-label="Indicators">
      {INDICATOR_CATALOG.map((ind) => {
        const active = enabled.includes(ind.key);
        const period = ind.parameterizable ? periodFor(ind.key) : null;
        return (
          <div key={ind.key} className="flex items-stretch" style={{ gap: 0 }}>
            <UIButton
              size="sm"
              active={active}
              aria-pressed={active}
              onClick={() => toggle(ind.key)}
              title={
                active
                  ? `Hide ${ind.label}`
                  : `Show ${ind.label}${ind.pane !== "price" ? " (separate pane)" : ""}`
              }
              className="uppercase tracking-label-up"
            >
              <span style={{ fontSize: 11 }}>
                {ind.label}
                {period != null && (
                  <span className="text-fg-tertiary-2"> {period}</span>
                )}
              </span>
            </UIButton>
            {period != null && (
              <PeriodPopover indicatorKey={ind.key} label={ind.label} period={period} />
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Tiny period editor anchored to a parameterizable indicator chip. A "▾"
 * trigger opens a popover with a clamped numeric input + a reset-to-default
 * action. Writes flow straight to the persisted indicatorPeriods store; the
 * chart re-keys its query on the next render and refetches just this series.
 * Closes on Escape, Enter, or an outside click.
 */
function PeriodPopover({
  indicatorKey,
  label,
  period,
}: {
  indicatorKey: string;
  label: string;
  period: number;
}) {
  const setPeriod = useIndicatorPeriods((s) => s.setPeriod);
  const resetPeriod = useIndicatorPeriods((s) => s.resetPeriod);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(String(period));
  const wrapRef = useRef<HTMLDivElement>(null);

  // Re-seed the draft when the popover opens or the stored period changes
  // out from under it (e.g. reset), so the input always shows the truth.
  useEffect(() => {
    if (open) setDraft(String(period));
  }, [open, period]);

  // Close on outside click while open.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const commit = (raw: string) => {
    const n = Number(raw);
    if (Number.isFinite(n)) setPeriod(indicatorKey, clampPeriod(n));
  };

  return (
    <div ref={wrapRef} className="relative flex">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={`Edit ${label} period`}
        aria-expanded={open}
        title={`Edit ${label} period`}
        className="px-1 border border-hairline border-l-0 text-fg-tertiary hover:text-fg-primary hover:bg-tier-2 transition-colors duration-100"
        style={{ fontSize: 9, borderRadius: 0 }}
      >
        ▾
      </button>
      {open && (
        <div
          className="absolute left-0 top-full mt-1 z-20 bg-tier-1 border border-hairline px-2 py-1.5 flex flex-col gap-1"
          style={{ borderRadius: 0, minWidth: 124 }}
          role="dialog"
          aria-label={`${label} period`}
        >
          <span
            className="text-tiny uppercase tracking-label-up text-fg-tertiary"
            style={{ fontSize: 9 }}
          >
            {label} period
          </span>
          <div className="flex items-center" style={{ gap: 4 }}>
            <input
              type="number"
              inputMode="numeric"
              min={MIN_INDICATOR_PERIOD}
              max={MAX_INDICATOR_PERIOD}
              value={draft}
              autoFocus
              onChange={(e) => setDraft(e.target.value)}
              onBlur={() => commit(draft)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  commit(draft);
                  setOpen(false);
                } else if (e.key === "Escape") {
                  setOpen(false);
                }
              }}
              className="w-14 bg-tier-0 border border-hairline px-1 py-0.5 text-fg-primary tabular-nums focus:border-amber outline-none"
              style={{ fontSize: 12, borderRadius: 0 }}
            />
            <button
              type="button"
              onClick={() => {
                resetPeriod(indicatorKey);
                setOpen(false);
              }}
              title="Reset to default"
              className="text-tiny uppercase tracking-label-up text-fg-tertiary hover:text-fg-primary px-1 border border-hairline"
              style={{ fontSize: 9, borderRadius: 0 }}
            >
              reset
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Stubs retired from the toolbar before YC submission. Kept on disk
// (block-commented to satisfy tsc noUnusedLocals) so they can be
// restored intact once the underlying features are real:
//   - candle-type selector (line/area chart-type menu)
//   - drawing tool icons (trend line / horizontal / rectangle)
//   - indicators dropdown (RSI / MACD / EMA / ...)
// Re-mount inside the Toolbar component above to restore.
/*
function Separator() {
  return (
    <span
      aria-hidden
      className="self-center"
      style={{ width: 1, height: 16, background: "#2B2F37", marginInline: 8 }}
    />
  );
}

function CandleTypeStub() {
  return (
    <UIButton size="sm" title="Chart type — candles (line/area types coming later)" className="min-w-[80px]">
      candles <span style={{ fontSize: 11 }}>▾</span>
    </UIButton>
  );
}

function DrawingToolStubs() {
  return (
    <div className="flex items-center" style={{ gap: 4 }}>
      <DrawIcon glyph="／" label="Trend line (stub)" />
      <DrawIcon glyph="—" label="Horizontal line (stub)" />
      <DrawIcon glyph="▭" label="Rectangle (stub)" />
    </div>
  );
}

function DrawIcon({ glyph, label }: { glyph: string; label: string }) {
  return (
    <UIButton size="sm" title={label} aria-label={label} className="w-[28px] px-0">
      <span style={{ fontSize: 11 }}>{glyph}</span>
    </UIButton>
  );
}

function IndicatorsStub() {
  return (
    <UIButton size="sm" title="Indicators — RSI/MACD/EMA coming later" className="min-w-[90px]">
      indicators <span style={{ fontSize: 11 }}>▾</span>
    </UIButton>
  );
}
*/

/**
 * Compact legend toggle. The chart legend was an on-chart overlay; the
 * redesign keeps the toggle but hides it on the chart by default. This
 * exposes the on/off state in the toolbar instead.
 */
function LegendToggle() {
  const show = useChartPrefs((s) => s.showLegend);
  const toggle = useChartPrefs((s) => s.toggleLegend);
  return (
    <UIButton
      size="sm"
      variant="ghost"
      active={show}
      onClick={toggle}
      title={show ? "Hide chart legend" : "Show chart legend"}
      aria-pressed={show}
      className="uppercase tracking-label-up"
    >
      <span style={{ fontSize: 12 }}>legend</span>
    </UIButton>
  );
}

/**
 * A tiny right-edge hint pointing to KEY LEVELS for users who used to
 * find the "structure" toggle here. KEY LEVELS toggle is in the bottom
 * strip after the redesign; this is just a breadcrumb.
 */
function MarketStructToggleHint() {
  return (
    <span
      className="text-fg-tertiary uppercase tracking-label-up"
      style={{ fontSize: 11 }}
      title="Market-structure overlays moved to KEY LEVELS in the bottom strip"
    >
      levels ↓
    </span>
  );
}

function OhlcStrip({
  symbol,
  timeframe,
}: {
  symbol: string | null;
  timeframe: ChartTimeframe;
}) {
  const { data } = useTickerChart(symbol, timeframe);
  const { data: market } = useMarketStatus();
  const marketOpen = market?.status === "open";
  const intervalSec = TF_INTERVAL_SECONDS[timeframe];
  // Leading-edge real bar — the SAME reference AnnotatedChart's
  // synthetic-candle effect pins to (bars[last]). Its timestamp changes
  // exactly when a new candle rolls in on this chart, so it's the
  // countdown's reset key.
  const leadingBarKey =
    data && data.bars.length > 0 ? data.bars[data.bars.length - 1].t : null;
  // Show only when a candle is actually forming/rolling: intraday grain
  // (1D excluded), market open, and a bar exists to anchor on.
  const showCountdown =
    intervalSec != null && marketOpen && leadingBarKey != null;
  const ohlc = useMemo(() => {
    if (!data || data.bars.length === 0) return null;
    const last = data.bars[data.bars.length - 1];
    const prev = data.bars[data.bars.length - 2];
    const change = prev ? last.c - prev.c : 0;
    const pct = prev && prev.c !== 0 ? (change / prev.c) * 100 : 0;
    return {
      o: last.o,
      h: last.h,
      l: last.l,
      c: last.c,
      change,
      pct,
    };
  }, [data]);

  return (
    <div
      className="flex items-center gap-3 px-3 border-t border-hairline tabular-nums"
      style={{ height: 20, fontSize: 12 }}
    >
      <span className="uppercase tracking-label-up text-fg-tertiary-2">
        {symbol ?? "—"} · {timeframe}
        {showCountdown && (
          <NextCandleCountdown
            barKey={leadingBarKey as string}
            intervalSec={intervalSec as number}
          />
        )}
      </span>
      {ohlc ? (
        <>
          <OhlcCell label="O" value={ohlc.o} />
          <OhlcCell label="H" value={ohlc.h} />
          <OhlcCell label="L" value={ohlc.l} />
          <OhlcCell label="C" value={ohlc.c} accent />
          <span
            className={`ml-2 ${
              ohlc.change > 0
                ? "text-bullish"
                : ohlc.change < 0
                  ? "text-bearish"
                  : "text-fg-secondary"
            }`}
          >
            {ohlc.change > 0 ? "+" : ohlc.change < 0 ? "−" : ""}
            {Math.abs(ohlc.change).toFixed(2)} ({ohlc.pct.toFixed(2)}%)
          </span>
        </>
      ) : (
        <span className="text-fg-tertiary">—</span>
      )}
    </div>
  );
}

function OhlcCell({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: boolean;
}) {
  return (
    <span className="inline-flex items-baseline gap-1">
      <span className="text-fg-tertiary-2">{label}</span>
      <span className={accent ? "text-fg-primary" : "text-fg-secondary"}>
        {value.toFixed(2)}
      </span>
    </span>
  );
}

/**
 * "Time until the next candle on this chart" — anchored to the CURRENT
 * candle's BOUNDARY, derived from the leading-edge bar's timestamp
 * (`barKey`, the same bar the synthetic candle pins to). NOT a wall-clock
 * :00 timer, and NOT "now at mount/switch": the current bar's timestamp is
 * the start of the current interval and its close is one interval later, so
 *     remaining = (barStart + intervalSec) - now
 * is correct IMMEDIATELY on mount and on every timeframe switch — switching
 * 5m→1m mid-candle instantly shows the true 1m remaining, not 1:00. Bars are
 * interval-spaced, so the phase stays locked to the candle grid and the
 * countdown is continuous across rolls.
 *
 * Honest about the delay: the feed is ~15min delayed and bars refresh
 * ~every 60s, so the next real bar may not have arrived yet and `remaining`
 * can compute ≤ 0 — we forward-wrap by whole intervals so it never parks at
 * 0:00. This is "time left in the current candle on THIS chart" relative to
 * the bar's timestamp, NOT the live market wall clock; never labeled "live".
 *
 * Pure client-side: one 1s setInterval, cleaned up on unmount. No network —
 * reads the already-fetched bars + market-status queries.
 */
function NextCandleCountdown({
  barKey,
  intervalSec,
}: {
  barKey: string;
  intervalSec: number;
}) {
  const [nowMs, setNowMs] = useState(() => Date.now());

  // Single 1s ticker, cleaned up on unmount.
  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // Current candle start = the leading-edge bar's timestamp (seconds).
  const barStartSec = Math.floor(new Date(barKey).getTime() / 1000);
  if (!Number.isFinite(barStartSec)) return null;

  // Remaining = time from now until this candle's boundary (start + one
  // interval). Correct on mount + timeframe switch with no roll needed.
  let remaining = barStartSec + intervalSec - nowMs / 1000;
  // Delayed feed: the next real bar may not have landed yet, so this can be
  // ≤ 0. Wrap forward by whole intervals (bars are interval-spaced) so it
  // stays phase-aligned and never parks at/below 0:00.
  while (remaining <= 0) remaining += intervalSec;
  const total = Math.ceil(remaining);
  const mm = Math.floor(total / 60);
  const ss = total % 60;

  return (
    <span title="Seconds until the next candle on this chart (delayed feed)">
      <span aria-hidden className="text-fg-tertiary mx-1.5">
        ·
      </span>
      next{" "}
      <span className="text-fg-secondary tabular-nums">
        {mm}:{String(ss).padStart(2, "0")}
      </span>
    </span>
  );
}
