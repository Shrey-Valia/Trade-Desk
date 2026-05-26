import { useMemo, useState } from "react";

import { TradeEntryModal } from "@/components/positions/journal/TradeEntryModal";
import { ThetaScrubber } from "@/components/positions/journal/ThetaScrubber";
import { useMarketStatus } from "@/hooks/useMarket";
import { useTradeAnalytics } from "@/hooks/useTradeAnalytics";
import { useTrades } from "@/hooks/useTrades";
import { useActivePosition } from "@/stores/activePosition";
import { useSelectedTicker } from "@/stores/selectedTicker";
import { useTradeIntent } from "@/stores/tradeIntent";
import { isZeroDteTrade } from "@/types/journal";

import { ChainTable } from "./ChainTable";
import { OpenPositionsList } from "./OpenPositionsList";

/**
 * CHART-view bottom panel — REPLACES the old journal-on-chart layout.
 *
 * Two columns:
 *   left ~70%: ChainTable — the trading ticket (calls | strikes | puts).
 *              Click a cell to open a paper position.
 *   right ~30%: OpenPositionsList — currently-open paper trades; click
 *              to set active (draws on chart), × to close at mark.
 *
 * Closed trades are no longer here; they live on the Journal page.
 *
 * The theta scrubber for the ACTIVE position lives at the bottom, same
 * UX as before — switches between days mode and hours mode based on
 * whether the active trade is 0DTE. The on-chart breakeven moves with
 * the scrubber; the open-positions list stays put.
 *
 * "+ Log trade" button kept available for manual/historical entry but
 * de-emphasized — it's a secondary path now.
 */
export function ChainPanel() {
  const symbol = useSelectedTicker((s) => s.symbol);
  const activeTradeId = useActivePosition((s) => s.tradeId);
  const scrubberDte = useActivePosition((s) => s.scrubberDte);
  const elapsedHoursStore = useActivePosition((s) => s.elapsedHours);
  const setScrubberDte = useActivePosition((s) => s.setScrubberDte);
  const setElapsedHours = useActivePosition((s) => s.setElapsedHours);

  const [modalOpen, setModalOpen] = useState(false);
  const { data: tradesData } = useTrades();
  const activeTrade = useMemo(
    () =>
      (tradesData?.trades ?? []).find((t) => t.id === activeTradeId) ?? null,
    [tradesData, activeTradeId],
  );
  const isIntraday = useMemo(() => isZeroDteTrade(activeTrade), [activeTrade]);
  const analyticsQuery = useTradeAnalytics(activeTradeId, scrubberDte, {
    intraday: isIntraday,
    elapsedHours: elapsedHoursStore,
  });
  const analytics = analyticsQuery.data ?? null;

  // Hours-mode scrubber range — entry → 4pm ET of the trade's expiry.
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

  const action = useTradeIntent((s) => s.action);
  const setAction = useTradeIntent((s) => s.setAction);
  const { data: marketStatus } = useMarketStatus();
  const marketOpen = marketStatus?.status === "open";

  return (
    <section className="border-t border-hairline bg-tier-0 shrink-0 flex flex-col">
      <div className="flex items-center gap-3 px-3 py-1 border-b border-hairline bg-tier-1 shrink-0">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Trading ticket &amp; open positions
        </span>
        <BuySellToggle action={action} onChange={setAction} />
        {!marketOpen && (
          <span
            className="text-tiny text-amber tabular-nums"
            style={{ fontSize: 10 }}
            title={
              marketStatus?.next_open
                ? `Next open: ${new Date(marketStatus.next_open).toLocaleString()}`
                : undefined
            }
          >
            Market {marketStatus?.label?.toLowerCase() ?? "closed"} — 0DTE opens at 9:30 AM ET
          </span>
        )}
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="ml-auto text-tiny uppercase tracking-label-up text-fg-tertiary border border-hairline px-2 hover:bg-tier-2"
          style={{ borderRadius: 0, fontSize: 9 }}
          title="Manual / historical trade entry"
        >
          + Log trade
        </button>
      </div>
      <div
        className="grid border-b border-hairline"
        style={{ gridTemplateColumns: "1fr 260px", height: 220 }}
      >
        <div className="min-w-0 min-h-0">
          <ChainTable symbol={symbol} />
        </div>
        <OpenPositionsList />
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
      <TradeEntryModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </section>
  );
}

function BuySellToggle({
  action,
  onChange,
}: {
  action: "buy" | "sell";
  onChange: (a: "buy" | "sell") => void;
}) {
  return (
    <div
      className="flex items-stretch border border-hairline"
      role="group"
      aria-label="Trade direction"
      style={{ borderRadius: 0 }}
    >
      {(["buy", "sell"] as const).map((opt, i) => {
        const active = action === opt;
        return (
          <button
            key={opt}
            type="button"
            onClick={() => onChange(opt)}
            className={[
              "h-5 px-2 text-tiny uppercase tracking-label-up tabular-nums",
              active
                ? "text-amber bg-tier-2 border-amber"
                : "text-fg-tertiary hover:bg-tier-2 hover:text-fg-primary",
              i === 1 ? "border-l border-hairline" : "",
            ].join(" ")}
            style={{ fontSize: 9, borderRadius: 0 }}
            aria-pressed={active}
            title={
              opt === "buy"
                ? "Long: pay premium; profit on big move (debit)"
                : "Short: collect premium; profit if it stays put (credit)"
            }
          >
            {opt === "buy" ? "Buy / long" : "Sell / short"}
          </button>
        );
      })}
    </div>
  );
}
