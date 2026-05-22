import { TradeDeskLogo } from "@/components/branding/TradeDeskLogo";
import { useTickerDetail } from "@/hooks/useTickerDetail";
import { formatPercent, formatPrice } from "@/lib/formatters";
import type { ChartTimeframe } from "@/types/chart";

import { ModeToggle } from "./ModeToggle";
import { SymbolSearch } from "./SymbolSearch";

const TIMEFRAMES: ChartTimeframe[] = ["1D", "5D", "1M", "3M"];

interface Props {
  symbol: string | null;
  timeframe: ChartTimeframe;
  onTimeframeChange: (tf: ChartTimeframe) => void;
}

/**
 * Trade Desk top toolbar — ~36px. Bloomberg-style hairline strip.
 *
 *   left:   TRADE DESK wordmark + symbol search
 *   center: selected symbol + price + change ($/%)
 *   right:  timeframe selector + mode toggle
 *
 * Owns the timeframe state (lifted up from AnnotatedChart). The chart in
 * the center pane consumes it via the controlledTimeframe prop — so the
 * single timeframe input lives here, not duplicated inside the chart.
 */
export function TradeDeskToolbar({ symbol, timeframe, onTimeframeChange }: Props) {
  const { data: detail } = useTickerDetail(symbol);

  return (
    <header
      className="flex items-center gap-6 border-b border-hairline bg-tier-0 px-4"
      style={{ height: 36 }}
    >
      <TradeDeskLogo size="compact" />
      <SymbolSearch />
      <SymbolReadout symbol={symbol} detail={detail} />
      <div className="ml-auto flex items-center gap-6">
        <TimeframeSelector value={timeframe} onChange={onTimeframeChange} />
        <ModeToggle />
      </div>
    </header>
  );
}

function SymbolReadout({
  symbol,
  detail,
}: {
  symbol: string | null;
  detail: ReturnType<typeof useTickerDetail>["data"];
}) {
  if (!symbol) {
    return (
      <span className="text-xs2 text-fg-tertiary">No ticker selected</span>
    );
  }
  if (!detail) {
    return (
      <span className="text-xs2 text-fg-tertiary tabular-nums">
        {symbol} —
      </span>
    );
  }
  const positive = detail.change_pct >= 0;
  const changeClass = positive ? "text-bullish" : "text-bearish";
  const sign = positive ? "+" : "";
  return (
    <span className="flex items-baseline gap-2 tabular-nums">
      <span className="text-xs2 text-fg-secondary uppercase tracking-label-up">
        {symbol}
      </span>
      <span className="text-medium font-medium text-fg-primary">
        {formatPrice(detail.price)}
      </span>
      <span className={`text-xs2 ${changeClass}`}>
        {sign}
        {detail.change_dollar.toFixed(2)} ({formatPercent(detail.change_pct)})
      </span>
    </span>
  );
}

function TimeframeSelector({
  value,
  onChange,
}: {
  value: ChartTimeframe;
  onChange: (tf: ChartTimeframe) => void;
}) {
  return (
    <div className="flex gap-1" role="group" aria-label="Chart timeframe">
      {TIMEFRAMES.map((tf) => (
        <button
          key={tf}
          type="button"
          onClick={() => onChange(tf)}
          className={[
            "px-2 py-0.5 text-tiny border",
            tf === value
              ? "border-amber text-amber bg-tier-1"
              : "border-hairline text-fg-tertiary hover:bg-tier-2",
          ].join(" ")}
          style={{ borderRadius: 0 }}
        >
          {tf}
        </button>
      ))}
    </div>
  );
}
