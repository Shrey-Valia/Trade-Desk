import { useEffect, useMemo, useRef } from "react";

import { useAccountState } from "@/hooks/useAccountState";
import { useTrades } from "@/hooks/useTrades";
import { useCombineStatus } from "@/hooks/useCombineStatus";
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
  const orderType = useTradeTicket((s) => s.orderType);
  const setOrderType = useTradeTicket((s) => s.setOrderType);
  const limitPrice = useTradeTicket((s) => s.limitPrice);
  const setLimitPrice = useTradeTicket((s) => s.setLimitPrice);
  const clear = useTradeTicket((s) => s.clear);

  const legMutation = useOpenZeroDteLeg();
  const straddleMutation = useOpenZeroDteStraddle();
  const { data: marketStatus } = useMarketStatus();
  const marketOpen = marketStatus?.status === "open";

  // Scaling-plan cap — max contracts per position at the current built
  // equity (server-enforced too). Default high until account state loads so
  // the UI never wrongly blocks; clamp the selection down if it exceeds.
  const { data: accountState } = useAccountState();
  const { data: tradesData } = useTrades();
  const maxContracts = accountState?.max_contracts ?? 99;
  const activeTier = accountState?.active_tier ?? "50K";
  // Contracts already open/working on this tier. The scaling cap limits TOTAL
  // simultaneous size, so the ticket's remaining capacity is the scaling max
  // minus what's already on — otherwise multiple max-size orders stack past
  // the cap (the server now rejects that aggregate too).
  const openContracts = useMemo(() => {
    const ts = tradesData?.trades ?? [];
    return ts
      .filter(
        (t) =>
          (t.status === "open" || t.status === "working") &&
          (t.tier ?? "50K") === activeTier,
      )
      .reduce(
        (sum, t) =>
          sum + (t.legs.length ? Math.max(...t.legs.map((l) => l.contracts ?? 1)) : 1),
        0,
      );
  }, [tradesData, activeTier]);
  const remaining = Math.max(0, maxContracts - openContracts);
  useEffect(() => {
    if (contracts > remaining) setContracts(Math.max(1, remaining));
  }, [contracts, remaining, setContracts]);

  // Combine engine soft-gate: a DAY LOCK (DLL hit today) or a FAILED
  // account blocks further opens — UX only; the backend open path is not
  // touched (opens still 201 server-side, so nothing silently diverges).
  const combine = useCombineStatus();
  const passed = combine.passed;
  // A PASSED combine is done (not locked) — passing isn't a trading lock.
  const locked = !passed && (combine.dayLocked || combine.status === "failed");
  const lockReason =
    combine.status === "failed"
      ? "Account FAILED — MLL floor breached."
      : "DAY LOCK — daily loss limit hit; no further trading today.";

  const pending = legMutation.isPending || straddleMutation.isPending;
  const lastError = useMemo(() => {
    if (legMutation.isError) return (legMutation.error as Error)?.message;
    if (straddleMutation.isError) return (straddleMutation.error as Error)?.message;
    return null;
  }, [legMutation.isError, legMutation.error, straddleMutation.isError, straddleMutation.error]);

  const hasSelection = !!selection;
  // Order type only applies to single legs; the straddle quick-entry is
  // always a market fill.
  const isLeg = selection?.kind === "leg";
  const effectiveOrderType = isLeg ? orderType : "market";
  const needsLimit = effectiveOrderType !== "market";
  const limitOk = !needsLimit || (limitPrice != null && limitPrice > 0);
  // At the scaling cap: no remaining capacity, or the chosen size would push
  // total open past the cap. Blocks the BUY (server enforces this too).
  const atCap = remaining <= 0 || contracts > remaining;
  const atCapReason = `Scaling plan: ${openContracts}/${maxContracts} contracts open — close a position to scale up.`;
  const canFire =
    hasSelection && marketOpen && !pending && !locked && limitOk && !atCap;

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
        order_type: effectiveOrderType,
        limit_price: needsLimit ? limitPrice : null,
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
        {passed && <PassedBanner />}
        {locked && <LockBanner reason={lockReason} />}
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
      {passed && <PassedBanner />}
      {locked && <LockBanner reason={lockReason} />}
      {!locked && atCap && <LockBanner reason={atCapReason} />}
      <Summary selection={selection} contracts={contracts} />
      {isLeg && (
        <OrderTypeRow
          orderType={orderType}
          setOrderType={setOrderType}
          limitPrice={limitPrice}
          setLimitPrice={setLimitPrice}
        />
      )}
      <QuantityRow
        contracts={contracts}
        setContracts={setContracts}
        cap={remaining}
        scalingMax={maxContracts}
        openContracts={openContracts}
      />
      <DllRiskHint selection={selection} contracts={contracts} />
      <Actions
        selection={selection}
        contracts={contracts}
        disabled={!canFire}
        pending={pending}
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

/** Combine PASSED banner — informational (passing isn't a trading lock). */
function PassedBanner() {
  return (
    <div
      className="mx-3 mt-1 px-2 py-1 border border-bullish text-bullish text-tiny uppercase tracking-label-up"
      style={{ borderRadius: 0, fontSize: 11 }}
      role="status"
    >
      Combine PASSED — profit target, min days &amp; consistency met.
    </div>
  );
}

/** Combine soft-gate banner — shown when the account is day-locked or
 *  FAILED. UX only; the backend open path is not gated. */
function LockBanner({ reason }: { reason: string }) {
  return (
    <div
      className="mx-3 mt-1 px-2 py-1 border border-bearish text-bearish text-tiny uppercase tracking-label-up"
      style={{ borderRadius: 0, fontSize: 11 }}
      role="status"
    >
      {reason}
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
        style={{ fontSize: 11 }}
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

/**
 * Sizing-discipline hint — relates the ticket's worst case (full debit,
 * i.e. a BUY that expires worthless) to the remaining daily loss
 * budget. Display-only, mirrors the header pill's budget resolution
 * (Settings override → tier spec → backend); uses realized DLL usage
 * only — open-position drawdown isn't folded in here.
 *
 * Deliberately silent for the SELL direction: a short's max loss isn't
 * the premium, and pretending otherwise would be worse than nothing.
 */
function DllRiskHint({
  selection,
  contracts,
}: {
  selection: TicketSelection;
  contracts: number;
}) {
  const { data: account } = useAccountState();
  if (!account) return null;
  // Backend resolves + enforces the active combine's DLL (override or default).
  const dllBudget = account.dll_budget ?? 0;
  if (dllBudget <= 0) return null;
  const remaining = Math.max(0, dllBudget - (account.dll_used ?? 0));
  const cost = selection.price * 100 * contracts;
  if (!Number.isFinite(cost) || cost <= 0) return null;

  if (remaining <= 0) {
    return (
      <div
        className="px-3 pb-1 text-bearish tabular-nums"
        style={{ fontSize: 12 }}
        title="Realized losses today have hit your daily loss limit — new opens are blocked until the 5pm-PT settlement."
      >
        DLL exhausted — any further loss exceeds today&rsquo;s budget
      </div>
    );
  }

  const pct = (cost / remaining) * 100;
  const tone =
    pct > 100 ? "text-bearish" : pct >= 50 ? "text-warning" : "text-fg-tertiary-2";
  return (
    <div
      className={`px-3 pb-1 tabular-nums ${tone}`}
      style={{ fontSize: 12 }}
      title={
        "Worst case if bought: the full debit. Compared against what's left of today's " +
        "daily loss budget (realized losses only). Opens are blocked once realized losses hit the limit."
      }
    >
      if bought, max loss ${cost.toFixed(2)} ·{" "}
      {pct > 100
        ? `exceeds remaining DLL ($${remaining.toFixed(0)})`
        : `${Math.round(pct)}% of remaining DLL`}
    </div>
  );
}

/**
 * Order-type selector (Market | Limit | Stop) + a limit-price input that
 * appears for limit/stop. The price is the OPTION premium the order fills
 * against — a working order rests until the monitor sees the mark cross it.
 */
function OrderTypeRow({
  orderType,
  setOrderType,
  limitPrice,
  setLimitPrice,
}: {
  orderType: "market" | "limit" | "stop";
  setOrderType: (t: "market" | "limit" | "stop") => void;
  limitPrice: number | null;
  setLimitPrice: (p: number | null) => void;
}) {
  const types: Array<"market" | "limit" | "stop"> = ["market", "limit", "stop"];
  return (
    <div className="flex items-center gap-2 px-3 pb-1 tabular-nums shrink-0">
      <div className="flex" style={{ gap: 4 }}>
        {types.map((t) => {
          const active = orderType === t;
          return (
            <button
              key={t}
              type="button"
              onClick={() => setOrderType(t)}
              aria-pressed={active}
              className={[
                "uppercase tracking-label-up transition-colors duration-100 select-none rounded-btn px-2",
                active
                  ? "bg-tier-3 border border-amber text-amber"
                  : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
              ].join(" ")}
              style={{ height: 24, fontSize: 11 }}
            >
              {t}
            </button>
          );
        })}
      </div>
      {orderType !== "market" && (
        <label className="flex items-center gap-1 ml-auto" style={{ fontSize: 12 }}>
          <span className="uppercase tracking-label-up text-fg-tertiary-2">
            {orderType === "stop" ? "stop @" : "limit @"}
          </span>
          <input
            type="number"
            inputMode="decimal"
            min={0}
            step={0.01}
            value={limitPrice ?? ""}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              setLimitPrice(Number.isFinite(v) ? v : null);
            }}
            placeholder="0.00"
            aria-label="Limit price (option premium)"
            className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums text-right px-1.5"
            style={{ width: 64, height: 24, fontSize: 12 }}
          />
        </label>
      )}
    </div>
  );
}

function QuantityRow({
  contracts,
  setContracts,
  cap,
  scalingMax,
  openContracts,
}: {
  contracts: number;
  setContracts: (n: number) => void;
  /** Remaining capacity = scalingMax − openContracts (the effective per-order limit). */
  cap: number;
  /** Scaling-plan max position size (for the label). */
  scalingMax: number;
  /** Contracts already open/working (for the label). */
  openContracts: number;
}) {
  // Topstep preset ladder: − [VALUE] +  |  [1] [3] [5] [10] [15]
  const presets = [1, 3, 5, 10, 15];
  const atMax = contracts >= cap;
  return (
    <div className="flex flex-col gap-0.5 px-3 pb-1 shrink-0">
      <div className="flex items-center gap-3 tabular-nums">
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
            disabled={atMax}
            onClick={() => setContracts(Math.min(cap, contracts + 1))}
          >
            +
          </StepperButton>
        </div>
        <div className="flex" style={{ gap: 4 }}>
          {presets.map((n) => {
            const active = contracts === n;
            const blocked = n > cap;
            return (
              <button
                key={n}
                type="button"
                disabled={blocked}
                onClick={() => setContracts(n)}
                aria-pressed={active}
                title={
                  blocked
                    ? `Scaling plan: ${openContracts}/${scalingMax} open — ${cap} contract${cap === 1 ? "" : "s"} left`
                    : undefined
                }
                className={[
                  "tabular-nums transition-colors duration-100 font-medium",
                  "flex items-center justify-center select-none",
                  blocked
                    ? "bg-tier-1 border border-tier-2 text-fg-disabled cursor-not-allowed"
                    : active
                      ? "bg-tier-3 border border-amber text-amber"
                      : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
                ].join(" ")}
                style={{ width: 32, height: 32, borderRadius: "50%", fontSize: 12 }}
              >
                {n}
              </button>
            );
          })}
        </div>
      </div>
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 11 }}
        title="Scaling plan — max TOTAL open size grows with built equity; re-evaluates at the 5pm-PT settlement."
      >
        scaling · {openContracts}/{scalingMax} open ·{" "}
        {cap} {cap === 1 ? "contract" : "contracts"} left
      </span>
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
  pending,
  marketOpen,
  onBuy,
  onSell,
}: {
  selection: TicketSelection | null;
  contracts: number;
  disabled: boolean;
  pending: boolean;
  marketOpen: boolean;
  onBuy: () => void;
  onSell: () => void;
}) {
  // Topstep idiom: "BUY +N" / "SELL -N" main label, small action sub
  // line below. While a mutation is in flight both subs read
  // "submitting…" so the user knows the click registered.
  const cost = selection ? selection.price * 100 * contracts : 0;
  const sideLabel = selection
    ? selection.kind === "straddle"
      ? "straddle"
      : (selection.side ?? "call")
    : "—";
  const buySub = pending
    ? "submitting…"
    : selection
      ? `long ${sideLabel} · $${cost.toFixed(2)} debit`
      : marketOpen
        ? "pick a strike ↑"
        : "market closed";
  const sellSub = pending
    ? "submitting…"
    : selection
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
          fontSize: 12,
          opacity: disabled ? 1 : 0.78,
          marginTop: 2,
        }}
      >
        {sub}
      </span>
    </button>
  );
}
