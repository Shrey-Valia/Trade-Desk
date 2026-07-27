import { useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useQueries } from "@tanstack/react-query";

import { fetchTradeAnalytics } from "@/lib/api";
import { isActiveCombineTrade } from "@/lib/combineScope";
import { AnnotatedChart, type PositionOverlay } from "@/components/stock/AnnotatedChart";
import type { BracketOverlay } from "@/components/stock/PositionBracketsLayer";
import { BottomStrip } from "@/components/positions/BottomStrip";
import { CalendarStrip } from "@/components/positions/CalendarStrip";
import { ContractDetailPanel } from "@/components/positions/ContractDetailPanel";
import { RightChain } from "@/components/positions/chain/RightChain";
import { ChartToolbar } from "@/components/positions/ChartToolbar";
import { PositionRiskStrip } from "@/components/positions/PositionRiskStrip";
import { TradeDeskHeader } from "@/components/positions/TradeDeskHeader";
import { TradeTicket } from "@/components/positions/TradeTicket";
import { WorkingOrders } from "@/components/positions/WorkingOrders";
import { useTradeTicket } from "@/stores/tradeTicket";
import { useAccountState } from "@/hooks/useAccountState";
import { useTradeAnalytics } from "@/hooks/useTradeAnalytics";
import { useSetBrackets, useTrades } from "@/hooks/useTrades";
import { useActivePosition } from "@/stores/activePosition";
import {
  useSelectedTicker,
  useSelectedTickerHasHydrated,
} from "@/stores/selectedTicker";
import { useUserSettings } from "@/stores/userSettings";
import { isZeroDteTrade, STRATEGY_LABELS } from "@/types/journal";
import { CHART_TIMEFRAMES, type ChartTimeframe } from "@/types/chart";

/**
 * Trade Desk POSITIONS mode — the chart-first product home.
 *
 * The page wires three concerns to the same activePosition store:
 *   1. The chart pulls analytics for the active position and renders
 *      the entry marker + theta-adjusted BE lines.
 *   2. BottomStrip renders the same analytics — open-position panel,
 *      theta scrubber, key levels.
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

  // Keyboard timeframe switching: plain digits 1-6 map onto the toolbar
  // ladder (1m…1D). Skipped while focus is in any form field so typing
  // in symbol search / trade forms never flips the chart. The header
  // owns "/" and Cmd+K; digits were free.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']"))
        return;
      const idx = Number(e.key) - 1;
      if (!Number.isInteger(idx) || idx < 0 || idx >= CHART_TIMEFRAMES.length)
        return;
      setTimeframe(CHART_TIMEFRAMES[idx]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const activeTradeId = useActivePosition((s) => s.tradeId);
  const setActiveTradeId = useActivePosition((s) => s.setTradeId);
  const scrubberDte = useActivePosition((s) => s.scrubberDte);
  const elapsedHours = useActivePosition((s) => s.elapsedHours);
  const { data: account } = useAccountState();
  const activeTier = account?.active_tier ?? "50K";
  const combineId = account?.combine_id;
  // Poll the shared trades cache on the terminal (12s) so server-booked closes
  // — stop-loss / take-profit / trailing / OCO / premium exits, DLL
  // liquidations, and limit fills the order monitor books autonomously — reach
  // the UI instead of a stopped-out position lingering as a live "ghost". The
  // ["journal","trades",{}] key is shared, so header / risk hooks refresh too.
  const { data: tradesData } = useTrades(undefined, { refetchInterval: 12_000 });
  const setBracketsMutation = useSetBrackets();
  const trades = useMemo(() => tradesData?.trades ?? [], [tradesData]);
  // Filter active-trade resolution by the current COMBINE — a trade opened on
  // combine A must not surface as the active position on combine B's screen.
  // Scoping by combine id (not tier) keeps two same-tier combines distinct.
  // Paired with useActivateCombine clearing the activePosition store, this
  // gives a clean combine boundary.
  const activeTrade = useMemo(
    () =>
      trades.find(
        (t) => t.id === activeTradeId && isActiveCombineTrade(t, combineId, activeTier),
      ) ?? null,
    [trades, activeTradeId, activeTier, combineId],
  );
  const isIntraday = useMemo(() => isZeroDteTrade(activeTrade), [activeTrade]);

  // 1D auto-switch retired alongside the toolbar's 1D button — the
  // backend's 1D minute-bar route 404s off-hours, and routing an
  // intraday active trade into a 404 was worse than leaving the chart
  // on the user's chosen timeframe. 5D / 1M / 3M still render fine for
  // the same intraday position; the entry marker is clamped into the
  // visible band regardless.

  // Follow the chart to a trade's symbol ONLY when the selection identity
  // changes — i.e. the user selected a different position (TradeList /
  // OpenPositions click) or opened a new one (the open mutation sets
  // activeTradeId). We must NOT re-fire when the user manually changes the
  // symbol while the SAME position stays selected — that was the "dead
  // terminal" trap (pick SPY with a TSLA position active → snapped back).
  const lastSyncedTradeIdRef = useRef<number | null>(null);
  useEffect(() => {
    if (!activeTrade) {
      // Deselected → reset so re-selecting the SAME trade later re-syncs.
      lastSyncedTradeIdRef.current = null;
      return;
    }
    if (lastSyncedTradeIdRef.current === activeTrade.id) return;
    lastSyncedTradeIdRef.current = activeTrade.id;
    if (activeTrade.symbol !== symbol) {
      setSymbol(activeTrade.symbol);
    }
  }, [activeTrade, symbol, setSymbol]);

  // Re-hydrate the active position after a page reload. The
  // activePosition store is in-memory only (session-scoped), so a
  // refresh strands the user with no selection — the entry marker,
  // breakeven lines, and position panel all blank out. Once trades +
  // tier are known, if nothing is selected we auto-select the
  // most-recent open trade on the active tier. Setting the store's
  // tradeId re-attaches the overlay exactly as a manual TradeList click
  // would (the symbol-sync effect above moves the chart to its symbol,
  // and chartOverlay rebuilds from the analytics payload). This runs at
  // most once per mount, so a deliberate manual deselect is respected.
  const didAutoSelectRef = useRef(false);
  useEffect(() => {
    if (didAutoSelectRef.current) return;
    // A selection already exists (in-SPA nav, not a cold reload) — leave
    // it alone and stop trying.
    if (activeTradeId != null) {
      didAutoSelectRef.current = true;
      return;
    }
    // Wait for both the trade list and the account (which determines the
    // active tier) before deciding — picking too early could match the
    // wrong tier's trade.
    if (!tradesData || !account) return;
    const mostRecentOpen = trades
      .filter((t) => t.status === "open" && isActiveCombineTrade(t, combineId, activeTier))
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
    if (mostRecentOpen) {
      setActiveTradeId(mostRecentOpen.id);
    }
    didAutoSelectRef.current = true;
  }, [tradesData, account, trades, activeTier, combineId, activeTradeId, setActiveTradeId]);

  // Orphan-leg recovery. Closing the active position (BottomStrip CLOSE)
  // sets activeTradeId = null. The once-per-mount auto-select above won't
  // re-fire, so without this the OPEN POSITION panel vanishes even when a
  // sibling leg of a straddle is still live — the user thinks the position
  // is gone while it keeps bleeding. We re-select a survivor ONLY when the
  // selection went null because its trade was CLOSED/removed, never on a
  // deliberate toggle-deselect (the store's toggle() clears tradeId when you
  // click the active row again).
  //
  // The trade is told apart from the deselect by asking whether the
  // previously-active id is still an OPEN trade: if it is, the user toggled
  // it off on purpose (or it merely moved behind a combine switch) — respect
  // that. If it's gone/closed, it was a close → re-point to the most-recent
  // surviving open trade on the active tier.
  //
  // Race note: the close flow (BottomStrip onSuccess) clears the selection
  // SYNCHRONOUSLY but refetches the trade list ASYNCHRONOUSLY, so there is a
  // render where activeTradeId is null while `trades` still shows the closed
  // trade as open. We therefore advance prevActiveIdRef ONLY while a trade is
  // actually selected — never on the null transition — so the previous id
  // survives that intermediate render and is still known once the refetch
  // lands and reveals the trade as closed.
  const prevActiveIdRef = useRef<number | null>(null);
  useEffect(() => {
    if (activeTradeId != null) {
      prevActiveIdRef.current = activeTradeId; // track the live selection
      return;
    }
    if (!tradesData || !account) return;
    const prev = prevActiveIdRef.current;
    if (prev == null) return; // nothing was selected
    const prevTrade = trades.find((t) => t.id === prev);
    if (prevTrade && prevTrade.status === "open") return; // deselect/off-tier — respect it
    // Previously-active trade is closed/removed → orphan-leg recovery. Clear
    // the ref first so a "no survivor" close doesn't keep re-evaluating.
    prevActiveIdRef.current = null;
    const survivor = trades
      .filter((t) => t.status === "open" && isActiveCombineTrade(t, combineId, activeTier))
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
    if (survivor) setActiveTradeId(survivor.id);
  }, [tradesData, account, trades, activeTier, combineId, activeTradeId, setActiveTradeId]);

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

  // All open positions on the charted symbol + active tier. Each draws its
  // own entry marker + sign-colored breakeven lines, so the chart shows
  // EVERY open contract (not just the selected one) and the header's URPL
  // reconciles with what's on screen. One live analytics query per position;
  // the query key matches useTradeAnalytics so the selected position's query
  // is shared from cache, not duplicated.
  const openOnSymbol = useMemo(
    () =>
      trades.filter(
        (t) =>
          t.status === "open" &&
          (t.tier ?? "50K") === activeTier &&
          t.symbol === symbol,
      ),
    [trades, activeTier, symbol],
  );
  const openAnalytics = useQueries({
    queries: openOnSymbol.map((t) => {
      const intraday = isZeroDteTrade(t);
      return {
        queryKey: ["trade-analytics", t.id, null, intraday ? "intraday" : "day", null],
        queryFn: () => fetchTradeAnalytics(t.id, { dteOverride: null, elapsedHours: null }),
        staleTime: intraday ? 3_000 : 10_000,
        refetchInterval: intraday ? 5_000 : (false as const),
        placeholderData: keepPreviousData,
      };
    }),
  });
  const chartOverlays: PositionOverlay[] = useMemo(() => {
    const out: PositionOverlay[] = [];
    openOnSymbol.forEach((t, i) => {
      // The SELECTED position uses scrubber-aware analytics so its BE follows
      // the theta scrubber; the others use their own live analytics.
      const a =
        t.id === activeTradeId && analyticsQuery.data
          ? analyticsQuery.data
          : openAnalytics[i]?.data;
      if (!a) return;
      let scrubberLabel: string | undefined;
      if (t.id === activeTradeId) {
        if (isIntraday) {
          const eff = elapsedHours ?? estimateLiveElapsedHours(t);
          if (eff > 0.01) scrubberLabel = `+${eff.toFixed(1)}h`;
        } else {
          const tPlus = a.current_dte_days - a.scrubber_dte_days;
          if (tPlus > 0) scrubberLabel = `T+${tPlus}d`;
        }
      }
      const upl = a.unrealized_pnl;
      out.push({
        tradeId: t.id,
        entryDate: t.entry_date,
        entryPrice: t.entry_underlying_price,
        strategyLabel: STRATEGY_LABELS[t.strategy] ?? t.strategy,
        breakevensToday: a.breakevens_today,
        breakevensExpiration: a.breakevens_expiration,
        scrubberLabel,
        uplLabel: formatSignedDollar(upl),
        uplPositive: upl >= 0,
      });
    });
    return out;
  }, [openOnSymbol, openAnalytics, activeTradeId, analyticsQuery.data, isIntraday, elapsedHours]);

  // Draggable SL/TP brackets — only for an OPEN position on the charted
  // symbol. Reads the committed levels off the trade row; drag-release /
  // add / clear persists via the brackets endpoint.
  const bracketsOverlay: BracketOverlay | null = useMemo(() => {
    if (!activeTrade || activeTrade.status !== "open") return null;
    if (activeTrade.symbol !== symbol || !analyticsQuery.data) return null;
    const a = analyticsQuery.data;
    return {
      tradeId: activeTrade.id,
      stopLoss: activeTrade.stop_loss ?? null,
      takeProfit: activeTrade.take_profit ?? null,
      entryUnderlying: activeTrade.entry_underlying_price,
      spot: a.spot,
      prices: a.prices,
      payoffToday: a.payoff_today,
      onChange: (b) => setBracketsMutation.mutate({ id: activeTrade.id, ...b }),
    };
  }, [activeTrade, analyticsQuery.data, symbol, setBracketsMutation]);

  return (
    <div className="flex flex-col h-full min-h-0 overflow-y-auto xl:overflow-hidden">
      {/* a11y (WS6): a visually-hidden <h1> gives this dense chart terminal a
          heading landmark — the visible header is pills/search, not a title. */}
      <h1 className="sr-only">Trade Desk — positions terminal{symbol ? ` (${symbol})` : ""}</h1>
      <TradeDeskHeader symbol={symbol} onSymbolChange={setSymbol} />
      {/* Wide (≥xl / 1280px): chart | rail side-by-side. Narrower — including
          tablets and small laptops — stacks chart over the chain/ticket rail,
          the whole page scrolling vertically. The rail is a hard 452px (the
          option chain can't shrink below it), so splitting any earlier squeezed
          the chart to an unusable sliver between ~768–1200px. */}
      <div className="flex flex-col xl:flex-row flex-1 min-h-0">
        <main className="flex-1 min-w-0 flex flex-col min-h-[60vh] xl:min-h-0">
          {/* Econ-calendar strip — macro tape above the chart (FOMC / CPI /
              OPEX / earnings / ISM). Wires the previously-orphaned
              useCalendar() feed. */}
          <CalendarStrip />
          <ChartToolbar
            symbol={symbol}
            timeframe={timeframe}
            onTimeframeChange={setTimeframe}
          />
          {/* In-trade risk band — greeks/UPL/max-loss for the ACTIVE position
              pinned above the chart, so P&L visibility doesn't require
              looking down at the bottom strip. Renders nothing when flat. */}
          <PositionRiskStrip
            analytics={activeTrade ? (analyticsQuery.data ?? null) : null}
            contextLabel={
              activeTrade ? `${activeTrade.symbol} · ${activeTrade.strategy}` : undefined
            }
          />
          {!hasHydrated ? (
            <div className="flex-1" />
          ) : symbol ? (
            <AnnotatedChart
              symbol={symbol}
              controlledTimeframe={{ value: timeframe, onChange: setTimeframe }}
              hideHeader
              positions={chartOverlays}
              brackets={bracketsOverlay}
            />
          ) : (
            <div className="flex-1 flex items-center justify-center text-fg-tertiary text-xs2">
              Pick a ticker from the header.
            </div>
          )}
        </main>
        <div
          className="border-t xl:border-t-0 xl:border-l border-hairline shrink-0 flex flex-col min-h-0 bg-tier-0 w-full xl:w-[452px] xl:min-w-[452px]"
        >
          {/* Upper-right: option chain (natural height, no flex-grow). */}
          <RightChain symbol={symbol} onPickSymbol={setSymbol} />
          {/* Lower-right: trade ticket sits flush under the chain. */}
          <div className="border-t border-hairline bg-tier-0 shrink-0">
            <TradeTicket />
          </div>
          {/* Resting limit/stop orders (hidden when none). */}
          <WorkingOrders />
          {/* Below the ticket: the selected contract's detail (payoff +
              greeks); falls back to an empty spacer when nothing's picked. */}
          <ContractDetailPanel />
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
