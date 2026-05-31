import { useMemo, useRef } from "react";

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

  // Synchronous double-click guard. The button's disabled prop tracks
  // mutation.isPending after react renders — but two synchronous clicks
  // within one frame both see isPending=false in the closure and both
  // dispatch a mutation. The ref flips IN the handler (before the
  // mutation queues) so the second click bails immediately, even
  // before react has rendered the disabled state.
  const submittingRef = useRef(false);

  const fire = (action: "buy" | "sell") => {
    if (submittingRef.current || !canFire || !selection) return;
    submittingRef.current = true;
    const onSettled = () => {
      submittingRef.current = false;
    };
    if (selection.kind === "straddle") {
      straddleMutation.mutate(
        {
          symbol: selection.symbol,
          action,
          contracts,
        },
        {
          onSuccess: () => clear(),
          onSettled,
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
        onSettled,
      },
    );
  };

  // Compressed empty state: no selection → skip Summary's big block,
  // skip QTY entirely, render small disabled buttons. ~half the
  // vertical footprint of the full ticket.
  if (!selection) {
    return (
      <section
        className="flex flex-col bg-tier-0"
        aria-label="Trade ticket"
      >
        <Header />
        <CompactEmpty marketOpen={marketOpen} />
      </section>
    );
  }
  return (
    <section
      className="flex flex-col bg-tier-0"
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

function CompactEmpty({ marketOpen }: { marketOpen: boolean }) {
  const label = marketOpen ? "Click a strike in the chain ↑" : "market closed";
  return (
    <div className="flex flex-col gap-1.5 px-3 pt-1 pb-2">
      <span className="text-tiny text-fg-tertiary-2 tabular-nums">
        {label}
      </span>
      <div className="grid grid-cols-2 gap-2" style={{ height: 32 }}>
        <button
          type="button"
          disabled
          className="rounded-btn bg-tier-1 text-fg-disabled font-semibold cursor-not-allowed"
          style={{ fontSize: 12 }}
        >
          BUY
        </button>
        <button
          type="button"
          disabled
          className="rounded-btn bg-tier-1 text-fg-disabled font-semibold cursor-not-allowed"
          style={{ fontSize: 12 }}
        >
          SELL
        </button>
      </div>
    </div>
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
  // Topstep preset ladder: − [VALUE] +  |  [1] [3] [5] [10] [15]
  const presets = [1, 3, 5, 10, 15];
  return (
    <div className="flex items-center gap-3 px-3 pb-1 tabular-nums shrink-0">
      <div className="flex items-center" style={{ gap: 4 }}>
        <StepperButton
          aria-label="Decrease quantity"
          disabled={contracts <= 1}
          onClick={() => setContracts(contracts - 1)}
        >
          −
        </StepperButton>
        <div
          aria-live="polite"
          className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums flex items-center justify-center"
          style={{ width: 60, height: 32, fontSize: 16, fontWeight: 500 }}
        >
          {contracts}
        </div>
        <StepperButton
          aria-label="Increase quantity"
          onClick={() => setContracts(contracts + 1)}
        >
          +
        </StepperButton>
      </div>
      <div className="flex" style={{ gap: 4 }}>
        {presets.map((n) => {
          const active = contracts === n;
          return (
            <button
              key={n}
              type="button"
              onClick={() => setContracts(n)}
              aria-pressed={active}
              className={[
                "tabular-nums transition-colors duration-100 font-medium",
                "flex items-center justify-center select-none",
                active
                  ? "bg-tier-3 border border-amber text-amber"
                  : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
              ].join(" ")}
              style={{
                width: 32,
                height: 32,
                borderRadius: "50%",
                fontSize: 12,
              }}
            >
              {n}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StepperButton({
  children,
  disabled,
  onClick,
  "aria-label": ariaLabel,
}: {
  children: React.ReactNode;
  disabled?: boolean;
  onClick: () => void;
  "aria-label": string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      className={[
        "rounded-btn flex items-center justify-center select-none",
        "transition-colors duration-100",
        disabled
          ? "bg-tier-1 text-fg-disabled cursor-not-allowed border border-tier-2"
          : "bg-tier-2 border border-tier-3 text-fg-primary hover:bg-tier-3",
      ].join(" ")}
      style={{ width: 32, height: 32, fontSize: 16, lineHeight: 1 }}
    >
      {children}
    </button>
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
  // Topstep idiom: "BUY +N" / "SELL -N" main label, small action sub
  // line below.
  const cost = selection ? selection.price * 100 * contracts : 0;
  const sideLabel = selection
    ? selection.kind === "straddle"
      ? "straddle"
      : (selection.side ?? "call")
    : "—";
  const buySub = selection
    ? `long ${sideLabel} · $${cost.toFixed(2)} debit`
    : marketOpen
      ? "pick a strike ↑"
      : "market closed";
  const sellSub = selection
    ? `short ${sideLabel} · $${cost.toFixed(2)} credit`
    : marketOpen
      ? "pick a strike ↑"
      : "market closed";
  return (
    <div className="grid grid-cols-2 gap-2 px-3 pb-2 mt-auto" style={{ height: 56 }}>
      <ActionButton
        intent="buy"
        label={`BUY +${contracts}`}
        sub={buySub}
        disabled={disabled}
        onClick={onBuy}
      />
      <ActionButton
        intent="sell"
        label={`SELL -${contracts}`}
        sub={sellSub}
        disabled={disabled}
        onClick={onSell}
      />
    </div>
  );
}

function ActionButton({
  intent,
  label,
  sub,
  disabled,
  onClick,
}: {
  intent: "buy" | "sell";
  label: string;
  sub: string;
  disabled: boolean;
  onClick: () => void;
}) {
  // Topstep aesthetic: solid action color fill, white-ish text, no
  // border, slight rounded corners. NOT bullish/bearish (those are
  // P&L colors); these are the action-affordance hues from
  // palette.actionBuy / palette.actionSell.
  const bg = disabled
    ? "bg-tier-1"
    : intent === "buy"
      ? "bg-action-buy hover:bg-action-buy-hover active:bg-action-buy-active"
      : "bg-action-sell hover:bg-action-sell-hover active:bg-action-sell-active";
  const textColor = disabled ? "text-fg-disabled" : "text-white";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={[
        "rounded-btn flex flex-col items-center justify-center px-2 leading-tight",
        "transition-colors duration-100",
        bg,
        textColor,
        disabled ? "cursor-not-allowed" : "",
      ].join(" ")}
    >
      <span className="font-semibold tracking-wide" style={{ fontSize: 14 }}>
        {label}
      </span>
      <span
        className="tabular-nums"
        style={{
          fontSize: 10,
          opacity: disabled ? 1 : 0.78,
          marginTop: 2,
        }}
      >
        {sub}
      </span>
    </button>
  );
}
