import { useMemo, useState } from "react";

import { useTradeAnalytics } from "@/hooks/useTradeAnalytics";
import { useTrades } from "@/hooks/useTrades";
import { useActivePosition } from "@/stores/activePosition";
import { useSelectedTicker } from "@/stores/selectedTicker";

import { isZeroDteTrade, STRATEGY_LABELS } from "@/types/journal";

import { PayoffPanel } from "./PayoffPanel";
import { ThetaScrubber } from "./ThetaScrubber";
import { TradeEntryModal } from "./TradeEntryModal";
import { TradeList } from "./TradeList";

/**
 * Trade Desk — journal + payoff + scrubber, all wired to the active
 * position.
 *
 *   left  ~60%: TradeList (row click = active position, drives overlays)
 *   right ~40%: PayoffPanel + ThetaScrubber
 *
 * The scrubber's state flows out to BOTH this panel's payoff curve AND
 * the price chart's breakeven overlay via the activePosition store.
 * Same source of truth, single fetcher, debounced through react-query.
 *
 * For 0DTE positions the scrubber switches from "integer days" mode to
 * "fractional hours" mode — same component, different prop set.
 */
export function JournalPanel() {
  const selectedSymbol = useSelectedTicker((s) => s.symbol);
  const [expanded, setExpanded] = useState(true);
  const [scope, setScope] = useState<"current" | "all">(
    selectedSymbol ? "current" : "all",
  );
  const [modalOpen, setModalOpen] = useState(false);

  const activeTradeId = useActivePosition((s) => s.tradeId);
  const scrubberDte = useActivePosition((s) => s.scrubberDte);
  const elapsedHoursStore = useActivePosition((s) => s.elapsedHours);
  const setScrubberDte = useActivePosition((s) => s.setScrubberDte);
  const setElapsedHours = useActivePosition((s) => s.setElapsedHours);

  const { data } = useTrades();
  const trades = data?.trades ?? [];
  const filtered = useMemo(() => {
    if (scope === "all" || !selectedSymbol) return trades;
    return trades.filter((t) => t.symbol === selectedSymbol);
  }, [trades, scope, selectedSymbol]);

  const activeTrade = useMemo(
    () => trades.find((t) => t.id === activeTradeId) ?? null,
    [trades, activeTradeId],
  );
  const isIntraday = useMemo(() => isZeroDteTrade(activeTrade), [activeTrade]);

  const analyticsQuery = useTradeAnalytics(activeTradeId, scrubberDte, {
    intraday: isIntraday,
    elapsedHours: elapsedHoursStore,
  });
  const analytics = analyticsQuery.data ?? null;

  // Hours-mode scrubber range: entry → 4pm ET on the position's expiry.
  const intradayBand = useMemo(() => {
    if (!isIntraday || !activeTrade) return null;
    const entry = new Date(activeTrade.entry_date).getTime();
    const expiryDate = activeTrade.legs[0]?.expiry;
    if (!expiryDate) return null;
    const close = new Date(`${expiryDate}T16:00:00-04:00`).getTime();
    const totalHours = Math.max(0, (close - entry) / 3_600_000);
    const liveElapsed = Math.max(
      0,
      Math.min(totalHours, (Date.now() - entry) / 3_600_000),
    );
    return { totalHours, liveElapsed };
  }, [isIntraday, activeTrade]);

  return (
    <section className="border-t border-hairline bg-tier-0 shrink-0">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-tier-1"
      >
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Journal &amp; Payoff
        </span>
        <span className="flex items-center gap-3">
          {activeTradeId && analytics && activeTrade && (
            <span className="text-tiny text-fg-tertiary normal-case tabular-nums">
              {analytics.symbol} {STRATEGY_LABELS[activeTrade.strategy] ?? activeTrade.strategy}
              {" · "}P&amp;L{" "}
              <span className={pnlSpanClass(analytics.unrealized_pnl)}>
                {formatDollar(analytics.unrealized_pnl)}
              </span>
            </span>
          )}
          <span className="text-tiny text-fg-tertiary normal-case">
            {trades.length} trade{trades.length === 1 ? "" : "s"}
          </span>
          <span aria-hidden className="text-tiny text-fg-tertiary">
            {expanded ? "▾" : "▴"}
          </span>
        </span>
      </button>
      {expanded && (
        <>
          <div
            className="grid border-t border-hairline"
            style={{ gridTemplateColumns: "3fr 2fr", height: 220 }}
          >
            <div className="min-w-0 min-h-0 border-r border-hairline">
              <TradeList
                trades={filtered}
                scope={scope}
                onScopeChange={setScope}
                selectedSymbol={selectedSymbol}
                onAddTrade={() => setModalOpen(true)}
              />
            </div>
            <PayoffPanel analytics={analytics} loading={analyticsQuery.isFetching} />
          </div>
          {analytics && isIntraday && intradayBand && (
            <ThetaScrubber
              mode="hours"
              totalHours={intradayBand.totalHours}
              liveElapsedHours={intradayBand.liveElapsed}
              scrubberHours={elapsedHoursStore}
              onChangeHours={setElapsedHours}
            />
          )}
          {analytics && !isIntraday && (
            <ThetaScrubber
              currentDte={analytics.current_dte_days}
              scrubberDte={analytics.scrubber_dte_days}
              onChange={(dte) => setScrubberDte(dte)}
              onReset={() => setScrubberDte(null)}
            />
          )}
        </>
      )}
      <TradeEntryModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </section>
  );
}

function formatDollar(value: number): string {
  const sign = value < 0 ? "−" : "+";
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

function pnlSpanClass(value: number): string {
  if (value > 0) return "text-bullish";
  if (value < 0) return "text-bearish";
  return "text-fg-secondary";
}
