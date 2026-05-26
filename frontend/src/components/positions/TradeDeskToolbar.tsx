import { TradeDeskLogo } from "@/components/branding/TradeDeskLogo";
import { useChainTable } from "@/hooks/useChainTable";
import { useMarketStatus } from "@/hooks/useMarket";
import { useOpenZeroDteStraddle } from "@/hooks/useOpenZeroDteStraddle";
import { useTickerDetail } from "@/hooks/useTickerDetail";
import { formatPercent, formatPrice } from "@/lib/formatters";
import { useTradeIntent } from "@/stores/tradeIntent";
import type { ChartTimeframe } from "@/types/chart";

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
 *   right:  timeframe selector
 *
 * Owns the timeframe state (lifted up from AnnotatedChart). The chart in
 * the center pane consumes it via the controlledTimeframe prop — so the
 * single timeframe input lives here, not duplicated inside the chart.
 *
 * Mode toggle was retired in the navigation revamp (step 1) — major-
 * section switching now lives in the persistent left rail.
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
      <div className="ml-auto flex items-center gap-3">
        <OpenZeroDteButton symbol={symbol} />
        <TimeframeSelector value={timeframe} onChange={onTimeframeChange} />
      </div>
    </header>
  );
}

function OpenZeroDteButton({ symbol }: { symbol: string | null }) {
  const mutation = useOpenZeroDteStraddle();
  const action = useTradeIntent((s) => s.action);
  const { data: marketStatus } = useMarketStatus();
  const marketOpen = marketStatus?.status === "open";
  // Reuse the same chain query the bottom panel uses — react-query
  // dedupes so this is free. We only check for the strict-0DTE error
  // to disable the button; price data isn't needed here.
  const chainQuery = useChainTable(symbol);
  const chainErrMsg =
    chainQuery.isError ? (chainQuery.error as Error)?.message ?? "" : "";
  const noZeroDteToday = chainErrMsg.startsWith("No 0DTE for");

  const disabled =
    !symbol || !marketOpen || noZeroDteToday || mutation.isPending;
  const verb = action === "buy" ? "BUY" : "SELL";
  const label = mutation.isPending ? "Opening…" : `${verb} STRADDLE`;
  const title = !symbol
    ? "Select a ticker first"
    : !marketOpen
      ? "Market closed — 0DTE trading opens 9:30 AM ET, Mon-Fri"
      : noZeroDteToday
        ? chainErrMsg
        : action === "buy"
          ? `Open ATM long straddle on ${symbol} expiring today (paper).`
          : `Open ATM short straddle on ${symbol} expiring today (paper, credit).`;
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() =>
          symbol && marketOpen && !noZeroDteToday && mutation.mutate({ symbol, action })
        }
        disabled={disabled}
        className={[
          "h-6 px-2 text-tiny uppercase tracking-label-up border",
          disabled
            ? "border-hairline text-fg-tertiary"
            : "border-amber text-amber bg-tier-1 hover:bg-tier-2",
        ].join(" ")}
        style={{ borderRadius: 0 }}
        title={title}
      >
        + {label}
      </button>
      {mutation.isError && (
        <span
          className="text-tiny text-bearish"
          title={(mutation.error as Error).message}
        >
          {String((mutation.error as Error).message).slice(0, 30)}
        </span>
      )}
    </div>
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
