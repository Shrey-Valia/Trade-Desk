import { useMemo, useState } from "react";

import { UIButton } from "@/components/ui/UIButton";
import { useTickerChart } from "@/hooks/useTickerChart";
import { useChartPrefs } from "@/stores/chartPrefs";
import type { ChartTimeframe } from "@/types/chart";

/**
 * TradingView-style chart chrome — toolbar (36px) + OHLC strip (20px).
 *
 * Toolbar:
 *   timeframes (1m / 5m / 15m / 1h / 4h / 1D)  · candles ▾  · | / − / ▭ stubs · indicators ▾
 *
 * Only "1D" maps to a real backend timeframe today (the rest are
 * design-system placeholders for the planned timeframe expansion).
 * Clicking a not-yet-wired timeframe sets local UI state and shows a
 * "soon" tooltip; the underlying chart timeframe stays at "1D" so the
 * candles don't blank out.
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

// Visual-only timeframe ladder. The "intraday" entries (1m..4h) are
// stubs — backend serves 1D/5D/1M/3M today. The map below routes a
// stub click to the closest real timeframe so the chart keeps drawing.
type StubTimeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1D";
const TF_VISUAL: StubTimeframe[] = ["1m", "5m", "15m", "1h", "4h", "1D"];
const TF_REAL_MAP: Record<StubTimeframe, ChartTimeframe> = {
  "1m": "1D",
  "5m": "1D",
  "15m": "1D",
  "1h": "1D",
  "4h": "1D",
  "1D": "1D",
};
// Mapping back so the highlighted visual TF reflects the backend TF
// reasonably (1D backend → "1D" visual default).
const REAL_TO_VISUAL: Record<ChartTimeframe, StubTimeframe> = {
  "1D": "1D",
  "5D": "1D",
  "1M": "1D",
  "3M": "1D",
};

export function ChartToolbar({ symbol, timeframe, onTimeframeChange }: Props) {
  const [visualTf, setVisualTf] = useState<StubTimeframe>(
    REAL_TO_VISUAL[timeframe] ?? "1D",
  );
  return (
    <div className="shrink-0 bg-tier-0 border-b border-hairline">
      <Toolbar
        timeframe={timeframe}
        visualTf={visualTf}
        onVisualChange={setVisualTf}
        onTimeframeChange={onTimeframeChange}
      />
      <OhlcStrip symbol={symbol} timeframe={timeframe} visualTf={visualTf} />
    </div>
  );
}

function Toolbar({
  timeframe,
  visualTf,
  onVisualChange,
  onTimeframeChange,
}: {
  timeframe: ChartTimeframe;
  visualTf: StubTimeframe;
  onVisualChange: (tf: StubTimeframe) => void;
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
        {TF_VISUAL.map((tf) => {
          const active = visualTf === tf;
          return (
            <UIButton
              key={tf}
              size="sm"
              active={active}
              aria-pressed={active}
              onClick={() => {
                onVisualChange(tf);
                onTimeframeChange(TF_REAL_MAP[tf]);
              }}
              title={
                tf === "1D"
                  ? "Daily bars"
                  : `${tf} intraday — falls back to 1D bars until intraday timeframes are wired up`
              }
              className="min-w-[36px]"
            >
              {tf}
            </UIButton>
          );
        })}
      </div>
      <Separator />
      <CandleTypeStub />
      <Separator />
      {/* Drawing tools — tight group. */}
      <DrawingToolStubs />
      <Separator />
      <IndicatorsStub />
      <div className="ml-auto flex items-center" style={{ gap: 6 }}>
        <LegendToggle />
        <MarketStructToggleHint />
      </div>
      <span className="sr-only">{timeframe}</span>
    </div>
  );
}

function Separator() {
  // Single 1px hairline between toolbar groups.
  return (
    <span
      aria-hidden
      className="self-stretch border-l border-hairline"
      style={{ marginInline: 8, width: 0 }}
    />
  );
}

function CandleTypeStub() {
  return (
    <UIButton
      size="sm"
      title="Chart type — candles (line/area types coming later)"
      className="min-w-[80px]"
    >
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
    <UIButton
      size="sm"
      title={label}
      aria-label={label}
      className="w-[28px] px-0"
    >
      <span style={{ fontSize: 11 }}>{glyph}</span>
    </UIButton>
  );
}

function IndicatorsStub() {
  return (
    <UIButton
      size="sm"
      title="Indicators — RSI/MACD/EMA coming later"
      className="min-w-[90px]"
    >
      indicators <span style={{ fontSize: 9 }}>▾</span>
    </UIButton>
  );
}

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
  visualTf,
}: {
  symbol: string | null;
  timeframe: ChartTimeframe;
  visualTf: StubTimeframe;
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
        {symbol ?? "—"} · {visualTf}
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
