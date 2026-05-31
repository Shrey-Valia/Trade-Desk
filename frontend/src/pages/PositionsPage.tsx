import { useEffect, useMemo, useState } from "react";

import { AnnotatedChart, type PositionOverlay } from "@/components/stock/AnnotatedChart";
import { BottomStrip } from "@/components/positions/BottomStrip";
import { RightChain } from "@/components/positions/chain/RightChain";
import { ChartToolbar } from "@/components/positions/ChartToolbar";
import { TradeDeskHeader } from "@/components/positions/TradeDeskHeader";
import { TradeTicket } from "@/components/positions/TradeTicket";
import { useTradeTicket } from "@/stores/tradeTicket";
import { useTradeAnalytics } from "@/hooks/useTradeAnalytics";
import { useTrades } from "@/hooks/useTrades";
import { useActivePosition } from "@/stores/activePosition";
import {
  useSelectedTicker,
  useSelectedTickerHasHydrated,
} from "@/stores/selectedTicker";
import { useUserSettings } from "@/stores/userSettings";
import { isZeroDteTrade, STRATEGY_LABELS } from "@/types/journal";
import type { ChartTimeframe } from "@/types/chart";

/**
 * Trade Desk POSITIONS mode — the chart-first product home.
 *
 * The page wires three concerns to the same activePosition store:
 *   1. The chart pulls analytics for the active position and renders
 *      the entry marker + theta-adjusted BE lines.
 *   2. JournalPanel renders the same analytics as a payoff curve and
 *      exposes the theta scrubber.
 *   3. TradeList click handlers + the 0DTE STRADDLE quick-entry button
 *      both write to the activePosition store.
 *
 * 0DTE positions go through the SAME analytics endpoint as multi-day
 * positions; backend detects nearest-leg expiry == today and routes to
 * the intraday-T math. Frontend just passes `intraday=true` to enable
 * live polling + sub-day scrubbing.
 */
export function PositionsPage() {
  const hasHydrated = useSelectedTickerHasHydrated();
  const symbol = useSelectedTicker((s) => s.symbol);
  const setSymbol = useSelectedTicker((s) => s.setSymbol);
  const defaultTimeframe = useUserSettings((s) => s.defaultTimeframe);
  const defaultTicker = useUserSettings((s) => s.defaultTicker);
  const defaultContracts = useUserSettings((s) => s.defaultContracts);
  const setTicketContracts = useTradeTicket((s) => s.setContracts);
  const [timeframe, setTimeframe] = useState<ChartTimeframe>(defaultTimeframe);

  // Seed the trade ticket's contract count from the user's Settings
  // default the first time we mount; preserves the click-and-fire
  // ergonomics from the retired toolbar 0DTE button.
  useEffect(() => {
    setTicketContracts(defaultContracts);
  }, [defaultContracts, setTicketContracts]);

  const activeTradeId = useActivePosition((s) => s.tradeId);
  const scrubberDte = useActivePosition((s) => s.scrubberDte);
  const elapsedHours = useActivePosition((s) => s.elapsedHours);
  const { data: tradesData } = useTrades();
  const trades = tradesData?.trades ?? [];
  const activeTrade = useMemo(
    () => trades.find((t) => t.id === activeTradeId) ?? null,
    [trades, activeTradeId],
  );
  const isIntraday = useMemo(() => isZeroDteTrade(activeTrade), [activeTrade]);

  // 1D auto-switch retired alongside the toolbar's 1D button — the
  // backend's 1D minute-bar route 404s off-hours, and routing an
  // intraday active trade into a 404 was worse than leaving the chart
  // on the user's chosen timeframe. 5D / 1M / 3M still render fine for
  // the same intraday position; the entry marker is clamped into the
  // visible band regardless.

  // When the user opens a position on a symbol that isn't the currently
  // selected ticker (e.g. they searched AAPL but clicked 0DTE on SPY by
  // accident), keep the chart in sync with the trade's symbol. This
  // mirrors what TradeList does on row clicks.
  useEffect(() => {
    if (activeTrade && activeTrade.symbol !== symbol) {
      setSymbol(activeTrade.symbol);
    }
  }, [activeTrade, symbol, setSymbol]);

  const analyticsQuery = useTradeAnalytics(activeTradeId, scrubberDte, {
    intraday: isIntraday,
    elapsedHours,
  });

  // Cold-open default — the user's Settings default ticker (defaults to
  // SPY). Honors the persisted symbol if there is one; only fires when
  // nothing was selected. No localStorage flag needed: the persisted
  // symbol IS the signal that the user has been here before.
  useEffect(() => {
    if (!hasHydrated) return;
    if (symbol) return;
    setSymbol(defaultTicker || "SPY");
  }, [hasHydrated, symbol, setSymbol, defaultTicker]);

  // Build the chart overlay from the analytics payload. The overlay
  // only renders when the active trade's symbol matches the chart's
  // selected symbol — TradeList auto-switches the chart on row click,
  // so this is the steady state after a click.
  const chartOverlay: PositionOverlay | null = useMemo(() => {
    if (!activeTrade || !analyticsQuery.data) return null;
    if (activeTrade.symbol !== symbol) return null;
    const a = analyticsQuery.data;
    // Scrubber label: days for multi-day; hours for 0DTE.
    let scrubberLabel: string | undefined;
    if (isIntraday) {
      const eff = elapsedHours ?? estimateLiveElapsedHours(activeTrade);
      if (eff > 0.01) scrubberLabel = `+${eff.toFixed(1)}h`;
    } else {
      const tPlus = a.current_dte_days - a.scrubber_dte_days;
      if (tPlus > 0) scrubberLabel = `T+${tPlus}d`;
    }
    const upl = a.unrealized_pnl;
    const uplLabel = formatSignedDollar(upl);
    return {
      tradeId: activeTrade.id,
      entryDate: activeTrade.entry_date,
      entryPrice: activeTrade.entry_underlying_price,
      strategyLabel: STRATEGY_LABELS[activeTrade.strategy] ?? activeTrade.strategy,
      breakevensToday: a.breakevens_today,
      breakevensExpiration: a.breakevens_expiration,
      scrubberLabel,
      uplLabel,
    };
  }, [activeTrade, analyticsQuery.data, symbol, isIntraday, elapsedHours]);

  return (
    <div className="flex flex-col h-full min-h-0">
      <TradeDeskHeader symbol={symbol} onSymbolChange={setSymbol} />
      <div className="flex flex-1 min-h-0">
        <main className="flex-1 min-w-0 flex flex-col">
          <ChartToolbar
            symbol={symbol}
            timeframe={timeframe}
            onTimeframeChange={setTimeframe}
          />
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
              Pick a ticker from the header.
            </div>
          )}
        </main>
        <div
          className="border-l border-hairline shrink-0 flex flex-col min-h-0 bg-tier-0"
          style={{ width: 452, minWidth: 452 }}
        >
          {/* Upper-right: option chain (natural height, no flex-grow). */}
          <RightChain symbol={symbol} />
          {/* Lower-right: trade ticket sits flush under the chain. */}
          <div className="border-t border-hairline bg-tier-0 shrink-0">
            <TradeTicket />
          </div>
          {/* Spacer absorbs any leftover vertical space below the ticket. */}
          <div className="flex-1 bg-tier-0" />
        </div>
      </div>
      <BottomStrip />
    </div>
  );
}

/** Hours since the trade's entry_date — used when no scrubber is set,
 * so the chart's scrubberLabel still shows the live "+Xh" position. */
function estimateLiveElapsedHours(trade: { entry_date: string }): number {
  const entry = new Date(trade.entry_date).getTime();
  if (!Number.isFinite(entry)) return 0;
  return Math.max(0, (Date.now() - entry) / 3_600_000);
}

function formatSignedDollar(v: number): string {
  if (!Number.isFinite(v)) return "$0.00";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}
