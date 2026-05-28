import { useMemo } from "react";

import { useMarketStatus } from "@/hooks/useMarket";
import { useOpenZeroDteLeg } from "@/hooks/useOpenZeroDteLeg";
import { useOpenZeroDteStraddle } from "@/hooks/useOpenZeroDteStraddle";
import { useTradeTicket, type TicketSelection } from "@/stores/tradeTicket";

/**
 * Lower-right TRADE TICKET (184px tall).
 *
 *   - Header row: "TRADE TICKET" left, hint right.
 *   - Summary: STRIKE X CALL · EST. $... debit · BE $... (BE magenta)
 *   - Quantity row: stepper (−/value/+) + preset chips (1 / 3 / 5 / 10)
 *   - Two large buttons (~56px tall):
 *       LEFT  : BUY  (bull-green outlined, two-line label)
 *       RIGHT : SELL (bear-red outlined, two-line label)
 *
 * Direction = which button you press. There is NO toggle anywhere.
 *
 * Disabled state — buttons dimmed, click is a no-op:
 *   - no selection from chain yet
 *   - market closed
 *   - chain returned "no 0DTE for symbol today" (selection.expiry "")
 *   - mutation in flight
 *
 * BUY  → fires useOpenZeroDte{Leg|Straddle}.mutate({ ..., action: "buy"  })
 * SELL → fires useOpenZeroDte{Leg|Straddle}.mutate({ ..., action: "sell" })
 *
 * On success the parent mutation hook sets the new trade as the active
 * position (existing behavior). The ticket clears its selection after
 * a successful fire so the user doesn't accidentally double-trade.
 */
export function TradeTicket() {
  const selection = useTradeTicket((s) => s.selection);
  const contracts = useTradeTicket((s) => s.contracts);
  const setContracts = useTradeTicket((s) => s.setContracts);
  const clear = useTradeTicket((s) => s.clear);

  const legMutation = useOpenZeroDteLeg();
  const straddleMutation = useOpenZeroDteStraddle();
  const { data: marketStatus } = useMarketStatus();
  const marketOpen = marketStatus?.status === "open";

  const pending = legMutation.isPending || straddleMutation.isPending;
  const lastError = useMemo(() => {
    if (legMutation.isError) return (legMutation.error as Error)?.message;
    if (straddleMutation.isError) return (straddleMutation.error as Error)?.message;
    return null;
  }, [legMutation.isError, legMutation.error, straddleMutation.isError, straddleMutation.error]);

  const hasSelection = !!selection;
  const canFire = hasSelection && marketOpen && !pending;

  const fire = (action: "buy" | "sell") => {
    if (!canFire || !selection) return;
    if (selection.kind === "straddle") {
      straddleMutation.mutate(
        {
          symbol: selection.symbol,
          action,
          contracts,
        },
        {
          onSuccess: () => clear(),
        },
      );
      return;
    }
    legMutation.mutate(
      {
        symbol: selection.symbol,
        side: selection.side ?? "call",
        action,
        strike: selection.strike,
        entry_price: selection.price,
        contracts,
      },
      {
        onSuccess: () => clear(),
      },
    );
  };

  return (
    <section
      className="flex flex-col bg-tier-0"
      style={{ height: 184 }}
      aria-label="Trade ticket"
    >
      <Header />
      <Summary selection={selection} contracts={contracts} />
      <QuantityRow contracts={contracts} setContracts={setContracts} />
      <Actions
        selection={selection}
        contracts={contracts}
        disabled={!canFire}
        marketOpen={marketOpen}
        onBuy={() => fire("buy")}
        onSell={() => fire("sell")}
      />
      {lastError && (
        <div className="px-3 pb-1 text-tiny text-bearish truncate" title={lastError}>
          {lastError}
        </div>
      )}
    </section>
  );
}

function Header() {
  return (
    <div className="flex items-baseline justify-between px-3 pt-1.5 shrink-0">
      <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
        Trade ticket
      </span>
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 9 }}
      >
        selected from chain ↑
      </span>
    </div>
  );
}

function Summary({
  selection,
  contracts,
}: {
  selection: TicketSelection | null;
  contracts: number;
}) {
  if (!selection) {
    return (
      <div className="px-3 py-2 text-tiny text-fg-tertiary-2 tabular-nums">
        Click a strike in the chain ↑
      </div>
    );
  }
  const kindLabel =
    selection.kind === "straddle"
      ? "STRADDLE"
      : (selection.side ?? "call").toUpperCase();
  // Cost in dollars per contract = price × 100, then × contracts.
  const totalCost = selection.price * 100 * contracts;
  const beRange = computeBreakevens(selection);
  return (
    <div className="px-3 py-1.5 tabular-nums flex items-baseline gap-3 flex-wrap">
      <span className="text-medium font-medium text-fg-primary">
        {selection.strike} {kindLabel}
      </span>
      <span className="text-tiny text-fg-tertiary-2 uppercase">est.</span>
      <span className="text-tiny text-fg-secondary">
        ${totalCost.toFixed(2)} debit
      </span>
      {beRange && (
        <>
          <span className="text-tiny text-fg-tertiary-2 uppercase">be</span>
          <span className="text-tiny text-position">{beRange}</span>
        </>
      )}
    </div>
  );
}

function computeBreakevens(sel: TicketSelection): string | null {
  if (sel.kind === "leg") {
    if (sel.side === "call") {
      return `$${(sel.strike + sel.price).toFixed(2)}`;
    }
    return `$${(sel.strike - sel.price).toFixed(2)}`;
  }
  // Straddle — price = call + put premium.
  const lower = sel.strike - sel.price;
  const upper = sel.strike + sel.price;
  return `$${lower.toFixed(2)} ↔ $${upper.toFixed(2)}`;
}

function QuantityRow({
  contracts,
  setContracts,
}: {
  contracts: number;
  setContracts: (n: number) => void;
}) {
  const presets = [1, 3, 5, 10];
  return (
    <div className="flex items-center gap-2 px-3 pb-1 tabular-nums shrink-0">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 9 }}
      >
        QTY
      </span>
      <div className="flex items-stretch border border-hairline" style={{ height: 22 }}>
        <button
          type="button"
          onClick={() => setContracts(contracts - 1)}
          disabled={contracts <= 1}
          className="px-2 text-tiny text-fg-secondary hover:bg-tier-2 disabled:text-fg-disabled disabled:cursor-not-allowed"
          style={{ borderRadius: 0 }}
          aria-label="Decrease quantity"
        >
          −
        </button>
        <span
          className="px-3 text-tiny tabular-nums text-fg-primary border-l border-r border-hairline flex items-center"
          style={{ minWidth: 32, justifyContent: "center" }}
          aria-live="polite"
        >
          {contracts}
        </span>
        <button
          type="button"
          onClick={() => setContracts(contracts + 1)}
          className="px-2 text-tiny text-fg-secondary hover:bg-tier-2"
          style={{ borderRadius: 0 }}
          aria-label="Increase quantity"
        >
          +
        </button>
      </div>
      <div className="flex" style={{ gap: 1 }}>
        {presets.map((n) => {
          const active = contracts === n;
          return (
            <button
              key={n}
              type="button"
              onClick={() => setContracts(n)}
              className={[
                "px-2 text-tiny tabular-nums border",
                active
                  ? "border-amber text-amber bg-tier-3"
                  : "border-hairline text-fg-tertiary-2 hover:bg-tier-2 hover:text-fg-primary",
              ].join(" ")}
              style={{ height: 22, borderRadius: 0 }}
              aria-pressed={active}
            >
              {n}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Actions({
  selection,
  contracts,
  disabled,
  marketOpen,
  onBuy,
  onSell,
}: {
  selection: TicketSelection | null;
  contracts: number;
  disabled: boolean;
  marketOpen: boolean;
  onBuy: () => void;
  onSell: () => void;
}) {
  // Two-line button labels (BUY/SELL on line 1, side+cost on line 2).
  const cost = selection ? selection.price * 100 * contracts : 0;
  const sideLabel = selection
    ? selection.kind === "straddle"
      ? "straddle"
      : (selection.side ?? "call")
    : "—";
  const buyLine2 = selection
    ? `long ${sideLabel} · $${cost.toFixed(2)} debit`
    : marketOpen
      ? "pick a strike ↑"
      : "market closed";
  const sellLine2 = selection
    ? `short ${sideLabel} · $${cost.toFixed(2)} credit`
    : marketOpen
      ? "pick a strike ↑"
      : "market closed";
  return (
    <div className="grid grid-cols-2 gap-2 px-3 pb-2 mt-auto" style={{ height: 56 }}>
      <ActionButton
        intent="buy"
        line1="BUY"
        line2={buyLine2}
        disabled={disabled}
        onClick={onBuy}
      />
      <ActionButton
        intent="sell"
        line1="SELL"
        line2={sellLine2}
        disabled={disabled}
        onClick={onSell}
      />
    </div>
  );
}

function ActionButton({
  intent,
  line1,
  line2,
  disabled,
  onClick,
}: {
  intent: "buy" | "sell";
  line1: string;
  line2: string;
  disabled: boolean;
  onClick: () => void;
}) {
  const palette =
    intent === "buy"
      ? disabled
        ? "border-hairline text-fg-disabled cursor-not-allowed"
        : "border-bullish text-bullish hover:bg-tier-2"
      : disabled
        ? "border-hairline text-fg-disabled cursor-not-allowed"
        : "border-bearish text-bearish hover:bg-tier-2";
  // Subtle background tint when enabled — uses the existing color via
  // alpha overlay so we don't need a new palette token.
  const bg = disabled
    ? "bg-tier-0"
    : intent === "buy"
      ? "bg-bullish/[0.06]"
      : "bg-bearish/[0.06]";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={[
        "border flex flex-col items-center justify-center px-2 leading-tight",
        palette,
        bg,
      ].join(" ")}
      style={{ borderRadius: 0 }}
    >
      <span className="uppercase tracking-label-up font-medium" style={{ fontSize: 14 }}>
        {line1}
      </span>
      <span className="text-tiny tabular-nums text-fg-tertiary-2" style={{ fontSize: 9 }}>
        {line2}
      </span>
    </button>
  );
}
