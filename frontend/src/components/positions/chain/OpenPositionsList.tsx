import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useTradeAnalytics } from "@/hooks/useTradeAnalytics";
import { useTrades } from "@/hooks/useTrades";
import { updateTrade } from "@/lib/api";
import { useActivePosition } from "@/stores/activePosition";
import { useSelectedTicker } from "@/stores/selectedTicker";
import { isZeroDteTrade, STRATEGY_LABELS, type Trade } from "@/types/journal";

/**
 * Right-side compact list of OPEN paper positions for the CHART view.
 *
 * Closed trades have moved to the JOURNAL page; this list shows only
 * what's live. Click a row to set it active (draws on the chart);
 * click × to close at the current mark.
 *
 * Each row pulls its own analytics query for the live UPL; react-query
 * dedupes against the chart's active query so the active row reuses
 * that result.
 */
export function OpenPositionsList() {
  const { data } = useTrades();
  const setActiveTradeId = useActivePosition((s) => s.setTradeId);
  const activeTradeId = useActivePosition((s) => s.tradeId);
  const open = (data?.trades ?? []).filter((t) => t.status === "open");

  return (
    <div className="flex flex-col h-full min-h-0 border-l border-hairline bg-tier-0">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-hairline bg-tier-1 shrink-0">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Open positions
        </span>
        <span className="text-tiny text-fg-tertiary tabular-nums">
          {open.length}
        </span>
      </div>
      {open.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-tiny text-fg-tertiary px-3 text-center">
          No open positions.<br />
          Click a strike in the chain →
        </div>
      ) : (
        <ul className="flex-1 min-h-0 overflow-y-auto">
          {open.map((trade) => (
            <OpenRow
              key={trade.id}
              trade={trade}
              active={trade.id === activeTradeId}
              onSelect={() => setActiveTradeId(trade.id)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function OpenRow({
  trade,
  active,
  onSelect,
}: {
  trade: Trade;
  active: boolean;
  onSelect: () => void;
}) {
  const intraday = isZeroDteTrade(trade);
  const setSymbol = useSelectedTicker((s) => s.setSymbol);
  const queryClient = useQueryClient();
  // Pull live analytics for the UPL. react-query dedupes against the
  // chart's own query for whichever row is active.
  const analytics = useTradeAnalytics(trade.id, null, { intraday });
  const upl = analytics.data?.unrealized_pnl ?? null;

  const close = useMutation({
    mutationFn: async () => {
      const live = analytics.data;
      const realized = live?.unrealized_pnl ?? 0;
      return updateTrade(trade.id, {
        status: "closed",
        exit_date: new Date().toISOString(),
        exit_underlying_price: live?.spot ?? trade.entry_underlying_price,
        realized_pnl: realized,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
    },
  });

  const rowCls = active
    ? "bg-tier-2 border-l-2 border-amber"
    : "border-l-2 border-transparent hover:bg-tier-1";

  return (
    <li className={`border-b border-hairline ${rowCls}`}>
      <div className="flex items-center gap-2 px-3 py-1.5 text-tiny tabular-nums">
        <button
          type="button"
          onClick={() => {
            onSelect();
            setSymbol(trade.symbol);
          }}
          className="flex-1 min-w-0 text-left"
          title={`Select ${trade.symbol} ${trade.strategy} on chart`}
        >
          <div className="flex items-baseline gap-2">
            <span className="text-fg-primary">{trade.symbol}</span>
            <span className="text-fg-tertiary truncate">
              {STRATEGY_LABELS[trade.strategy] ?? trade.strategy}
            </span>
          </div>
          <div className="flex items-baseline gap-2 mt-0.5">
            <span className="text-fg-tertiary" style={{ fontSize: 11 }}>
              entry ${trade.entry_underlying_price.toFixed(2)}
            </span>
            <span className={uplClass(upl)} style={{ fontSize: 12 }}>
              {upl === null ? "—" : formatSignedDollar(upl)}
            </span>
            {intraday && (
              <span
                className="ml-auto text-fg-tertiary uppercase tracking-label-up"
                style={{ fontSize: 11 }}
              >
                0DTE
              </span>
            )}
          </div>
        </button>
        <button
          type="button"
          onClick={() => close.mutate()}
          disabled={close.isPending}
          className="text-tiny text-fg-tertiary hover:text-bearish px-1"
          title="Close at current mark"
          aria-label="Close position"
        >
          {close.isPending ? "…" : "×"}
        </button>
      </div>
    </li>
  );
}

function formatSignedDollar(v: number): string {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}

function uplClass(v: number | null): string {
  if (v === null) return "text-fg-tertiary";
  if (v > 0) return "text-bullish";
  if (v < 0) return "text-bearish";
  return "text-fg-secondary";
}
