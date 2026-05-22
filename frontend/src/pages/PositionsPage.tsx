import { useEffect, useMemo, useState } from "react";

import { AnnotatedChart, type PositionOverlay } from "@/components/stock/AnnotatedChart";
import { JournalPanel } from "@/components/positions/journal/JournalPanel";
import { TradeDeskToolbar } from "@/components/positions/TradeDeskToolbar";
import { WatchlistColumn } from "@/components/watchlist/WatchlistColumn";
import { useTradeAnalytics } from "@/hooks/useTradeAnalytics";
import { useTrades } from "@/hooks/useTrades";
import { useActivePosition } from "@/stores/activePosition";
import {
  useSelectedTicker,
  useSelectedTickerHasHydrated,
} from "@/stores/selectedTicker";
import { STRATEGY_LABELS } from "@/types/journal";
import type { ChartTimeframe } from "@/types/chart";

const COLD_SELECT_FLAG = "td:cold-position-selected";

/**
 * Trade Desk POSITIONS mode — Phase 2.
 *
 * The page wires three concerns to the same activePosition store:
 *   1. The chart pulls analytics for the active position and renders
 *      the entry marker + theta-adjusted BE lines.
 *   2. JournalPanel renders the same analytics as a payoff curve and
 *      exposes the theta scrubber.
 *   3. TradeList click handlers write to the activePosition store.
 *
 * Single fetcher (`useTradeAnalytics`) is reused — react-query dedupes
 * the requests across these two consumers using the same query key.
 */
export function PositionsPage() {
  const hasHydrated = useSelectedTickerHasHydrated();
  const symbol = useSelectedTicker((s) => s.symbol);
  const setSymbol = useSelectedTicker((s) => s.setSymbol);
  const [timeframe, setTimeframe] = useState<ChartTimeframe>("5D");

  const activeTradeId = useActivePosition((s) => s.tradeId);
  const scrubberDte = useActivePosition((s) => s.scrubberDte);
  const setActiveTradeId = useActivePosition((s) => s.setTradeId);
  const { data: tradesData } = useTrades();
  const trades = tradesData?.trades ?? [];
  const activeTrade = useMemo(
    () => trades.find((t) => t.id === activeTradeId) ?? null,
    [trades, activeTradeId],
  );
  const analyticsQuery = useTradeAnalytics(activeTradeId, scrubberDte);

  // Cold-open staging — on a fresh visit, pre-select the seeded NVDA
  // long straddle so the chart overlay + payoff curve are visible
  // without any clicks. localStorage flag means the auto-select only
  // fires once; if the user has navigated/deselected since, we respect
  // their state.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.localStorage.getItem(COLD_SELECT_FLAG)) return;
    if (activeTradeId !== null) return;
    if (trades.length === 0) return;
    const candidate = trades.find(
      (t) =>
        t.symbol === "NVDA" &&
        t.strategy === "long_straddle" &&
        t.status === "open",
    );
    if (!candidate) return;
    setActiveTradeId(candidate.id);
    setSymbol("NVDA");
    window.localStorage.setItem(COLD_SELECT_FLAG, "1");
  }, [trades, activeTradeId, setActiveTradeId, setSymbol]);

  // Build the chart overlay from the analytics payload. The overlay
  // only renders when the active trade's symbol matches the chart's
  // selected symbol — TradeList auto-switches the chart on row click,
  // so this is the steady state after a click.
  const chartOverlay: PositionOverlay | null = useMemo(() => {
    if (!activeTrade || !analyticsQuery.data) return null;
    if (activeTrade.symbol !== symbol) return null;
    const a = analyticsQuery.data;
    const tPlus = a.current_dte_days - a.scrubber_dte_days;
    return {
      tradeId: activeTrade.id,
      entryDate: activeTrade.entry_date,
      entryPrice: activeTrade.entry_underlying_price,
      strategyLabel: STRATEGY_LABELS[activeTrade.strategy] ?? activeTrade.strategy,
      breakevensToday: a.breakevens_today,
      breakevensExpiration: a.breakevens_expiration,
      scrubberLabel: tPlus > 0 ? `T+${tPlus}d` : undefined,
    };
  }, [activeTrade, analyticsQuery.data, symbol]);

  return (
    <div className="flex flex-col h-full min-h-0">
      <TradeDeskToolbar
        symbol={symbol}
        timeframe={timeframe}
        onTimeframeChange={setTimeframe}
      />
      <div className="flex flex-1 min-h-0">
        <main className="flex-1 min-w-0 flex flex-col">
          {!hasHydrated ? (
            <div className="flex-1" />
          ) : symbol ? (
            <AnnotatedChart
              symbol={symbol}
              controlledTimeframe={{ value: timeframe, onChange: setTimeframe }}
              hideHeader
              position={chartOverlay}
            />
          ) : (
            <div className="flex-1 flex items-center justify-center text-fg-tertiary text-xs2">
              Search a ticker or pick one from the watchlist.
            </div>
          )}
        </main>
        <div
          className="border-l border-hairline shrink-0"
          style={{ width: 240, minWidth: 240 }}
        >
          <WatchlistColumn />
        </div>
      </div>
      <JournalPanel />
    </div>
  );
}
