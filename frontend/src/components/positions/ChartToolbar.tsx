import { useMemo } from "react";

import { UIButton } from "@/components/ui/UIButton";
import { useTickerChart } from "@/hooks/useTickerChart";
import { useChartPrefs } from "@/stores/chartPrefs";
import { CHART_TIMEFRAMES, type ChartTimeframe } from "@/types/chart";

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
      className="flex items-center px-3"
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
      <div className="ml-auto flex items-center" style={{ gap: 6 }}>
        <LegendToggle />
        <MarketStructToggleHint />
      </div>
      <span className="sr-only">{timeframe}</span>
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
      style={{ width: 1, height: 16, background: "#2F3545", marginInline: 8 }}
    />
  );
}

function CandleTypeStub() {
  return (
    <UIButton size="sm" title="Chart type — candles (line/area types coming later)" className="min-w-[80px]">
      candles <span style={{ fontSize: 9 }}>▾</span>
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
      indicators <span style={{ fontSize: 9 }}>▾</span>
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
      <span style={{ fontSize: 10 }}>legend</span>
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
      style={{ fontSize: 9 }}
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
      style={{ height: 20, fontSize: 10 }}
    >
      <span className="uppercase tracking-label-up text-fg-tertiary-2">
        {symbol ?? "—"} · {timeframe}
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
