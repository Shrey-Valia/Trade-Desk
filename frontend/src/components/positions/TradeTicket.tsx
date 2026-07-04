import { useEffect, useMemo, useRef, useState } from "react";

import {
  isIntentFresh,
  useHotkeyActions,
  useHotkeyConsumer,
} from "@/stores/hotkeyActions";
import { useAccountState } from "@/hooks/useAccountState";
import { useCombineStatus } from "@/hooks/useCombineStatus";
import { useOpenContractsCount } from "@/hooks/useOpenContractsCount";
import { useMarketStatus } from "@/hooks/useMarket";
import { useOpenZeroDteLeg } from "@/hooks/useOpenZeroDteLeg";
import { useOpenZeroDteStraddle } from "@/hooks/useOpenZeroDteStraddle";
import { useSelectedTicker } from "@/stores/selectedTicker";
import {
  premiumExitForDirection,
  useTradeTicket,
  type PremiumExitConfig,
  type TicketSelection,
  type TicketOrderType,
} from "@/stores/tradeTicket";
// ── WS5 (Trading depth): builder / sizer / Monte-Carlo tools ────────────────
// These mount in a collapsible TOOLS section below the Actions row (see the
// WS5 block in the render). Self-contained components; WS6 shares this file.
import { StrategyBuilder } from "@/components/positions/tools/StrategyBuilder";
import { PositionSizer } from "@/components/positions/tools/PositionSizer";
import { MonteCarloPanel } from "@/components/positions/tools/MonteCarloPanel";
// ── end WS5 ─────────────────────────────────────────────────────────────────

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
  const stopPrice = useTradeTicket((s) => s.stopPrice);
  const setStopPrice = useTradeTicket((s) => s.setStopPrice);
  const trailAmount = useTradeTicket((s) => s.trailAmount);
  const setTrailAmount = useTradeTicket((s) => s.setTrailAmount);
  const timeInForce = useTradeTicket((s) => s.timeInForce);
  const setTimeInForce = useTradeTicket((s) => s.setTimeInForce);
  const premiumExit = useTradeTicket((s) => s.premiumExit);
  const setPremiumExit = useTradeTicket((s) => s.setPremiumExit);
  const clear = useTradeTicket((s) => s.clear);

  const legMutation = useOpenZeroDteLeg();
  const straddleMutation = useOpenZeroDteStraddle();
  const { data: marketStatus } = useMarketStatus();
  const marketOpen = marketStatus?.status === "open";

  // Scaling-plan cap — max TOTAL open contracts at the current built equity
  // (server-enforced too). Shared sum-of-legs hook: the SAME math sizes the
  // chain's QuickOrder, so the two can't diverge.
  const { openContracts, maxContracts, remaining } = useOpenContractsCount();
  // A straddle quick-entry opens 2 legs, so it consumes 2× the per-leg size; a
  // single leg consumes 1×. Clamp the per-leg selection to what fits.
  const orderLegs = selection?.kind === "leg" ? 1 : 2;
  const maxPerLeg = Math.max(1, Math.floor(remaining / orderLegs));
  useEffect(() => {
    if (contracts > maxPerLeg) setContracts(maxPerLeg);
  }, [contracts, maxPerLeg, setContracts]);

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
  const needsStop = effectiveOrderType === "stop_limit";
  const limitOk = !needsLimit || (limitPrice != null && limitPrice > 0);
  // At the scaling cap: no remaining capacity, or the chosen size would push
  // total open past the cap. Blocks the BUY (server enforces this too).
  const atCap = remaining <= 0 || contracts * orderLegs > remaining;
  const atCapReason = `Scaling plan: ${openContracts}/${maxContracts} contracts open — close a position to scale up.`;
  // Stop-limit needs a valid stop (arm) price in addition to the limit price.
  const stopOk = !needsStop || (stopPrice != null && stopPrice > 0);
  const canFire =
    hasSelection && marketOpen && !pending && !locked && limitOk && stopOk && !atCap;

  // Synchronous double-click guard. The button's disabled prop tracks
  // mutation.isPending after react renders — but two synchronous clicks
  // within one frame both see isPending=false in the closure and both
  // dispatch a mutation. The ref flips IN the handler (before the
  // mutation queues) so the second click bails immediately, even
  // before react has rendered the disabled state.
  const submittingRef = useRef(false);

  // ── WS5: collapsible TOOLS tab (builder / sizer / Monte-Carlo). null = closed.
  const [activeTool, setActiveTool] = useState<ToolTab | null>(null);
  // The tools only need a SYMBOL, not a chain selection — bind them to the
  // charted symbol so an iron condor doesn't require first clicking an
  // unrelated single leg. A selection (if any) still wins: the tools follow
  // the contract the trader is actively working.
  const chartedSymbol = useSelectedTicker((s) => s.symbol);
  const toolsSymbol = selection?.symbol ?? chartedSymbol;
  // ── end WS5

  // WS6 power-UX: the B/S hotkeys "pre-arm" by focusing the matching action
  // button (not auto-firing — a stray keypress must never place an order). The
  // global hotkey hook publishes the intent on the action bus; we consume it
  // here and move focus so the user confirms with Enter/Space.
  const buyBtnRef = useRef<HTMLButtonElement>(null);
  const sellBtnRef = useRef<HTMLButtonElement>(null);
  const hotkeyIntent = useHotkeyActions((s) => s.intent);
  const hotkeyNonce = useHotkeyActions((s) => s.nonce);
  const hotkeyTs = useHotkeyActions((s) => s.ts);
  const consumeHotkey = useHotkeyActions((s) => s.consume);
  // Only an actionable ticket (a selection exists) counts as a consumer —
  // otherwise the B/S keys toast "pick a strike" instead of vanishing.
  useHotkeyConsumer(["armBuy", "armSell"], hasSelection);
  useEffect(() => {
    if (hotkeyIntent !== "armBuy" && hotkeyIntent !== "armSell") return;
    consumeHotkey();
    if (!isIntentFresh(hotkeyTs)) return; // stale replay from an old mount
    if (hotkeyIntent === "armBuy") buyBtnRef.current?.focus();
    else sellBtnRef.current?.focus();
    // closeActive is handled by the active-position panel, not the ticket.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hotkeyIntent, hotkeyNonce]);

  const fire = (action: "buy" | "sell") => {
    if (submittingRef.current || !canFire || !selection) return;
    submittingRef.current = true;
    const onSettled = () => {
      submittingRef.current = false;
    };
    // Premium-exit presets resolve per direction at fire time: a BUY is a
    // net-debit (long) open, a SELL a net-credit (short) one.
    const exits = premiumExitForDirection(premiumExit, action === "buy");
    if (selection.kind === "straddle") {
      straddleMutation.mutate(
        {
          symbol: selection.symbol,
          action,
          contracts,
          tp_premium_mult: exits.tp,
          sl_premium_mult: exits.sl,
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
        // TIF only matters for a working order; market fills ignore it.
        time_in_force: timeInForce,
        limit_price: needsLimit ? limitPrice : null,
        stop_price: needsStop ? stopPrice : null,
        trail_amount: trailAmount && trailAmount > 0 ? trailAmount : null,
        tp_premium_mult: exits.tp,
        sl_premium_mult: exits.sl,
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
        {/* WS5 tools stay reachable with NO chain selection — the builder /
            sizer / Monte-Carlo only need the charted symbol. Collapsed by
            default so the compact empty state keeps its footprint. */}
        {toolsSymbol && (
          <ToolsSection
            symbol={toolsSymbol}
            active={activeTool}
            onSelect={(t) => setActiveTool((prev) => (prev === t ? null : t))}
          />
        )}
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
      <Summary selection={selection} contracts={contracts} premiumExit={premiumExit} />
      {isLeg && (
        <OrderTypeRow
          orderType={orderType}
          setOrderType={setOrderType}
          limitPrice={limitPrice}
          setLimitPrice={setLimitPrice}
          stopPrice={stopPrice}
          setStopPrice={setStopPrice}
          timeInForce={timeInForce}
          setTimeInForce={setTimeInForce}
        />
      )}
      {isLeg && (
        <TrailStopRow trailAmount={trailAmount} setTrailAmount={setTrailAmount} />
      )}
      <PremiumExitRow config={premiumExit} onChange={setPremiumExit} />
      <QuantityRow
        contracts={contracts}
        setContracts={setContracts}
        cap={remaining}
        scalingMax={maxContracts}
        openContracts={openContracts}
      />
      <DllRiskHint selection={selection} contracts={contracts} />
      {/* ── WS6 RISK PREVIEW (BEGIN) ──────────────────────────────────────
          Owned by WS6. Self-contained block: reads only `selection` +
          `contracts` (both already in scope) and the shared breakeven/
          pricing math below. WS5 (multi-leg builder) edits this file too and
          merges FIRST — to integrate, keep this <RiskPreview/> call and its
          component + helpers as one unit; if WS5 generalizes `selection` to
          multi-leg, extend `riskPreviewFor()` rather than inlining here. */}
      <RiskPreview selection={selection} contracts={contracts} />
      {/* ── WS6 RISK PREVIEW (END) ───────────────────────────────────────── */}
      <Actions
        selection={selection}
        contracts={contracts}
        disabled={!canFire}
        pending={pending}
        marketOpen={marketOpen}
        onBuy={() => fire("buy")}
        onSell={() => fire("sell")}
        buyRef={buyBtnRef}
        sellRef={sellBtnRef}
      />
      {lastError && (
        <div className="px-3 pb-1 text-tiny text-bearish truncate" title={lastError}>
          {lastError}
        </div>
      )}
      {/* ── WS5: collapsible TOOLS — multi-leg builder / position sizer /
          Monte-Carlo. Additive; renders below the single/straddle ticket so
          the core BUY/SELL flow is unchanged. WS6 shares this file. ── */}
      <ToolsSection
        symbol={toolsSymbol ?? selection.symbol}
        active={activeTool}
        onSelect={(t) => setActiveTool((prev) => (prev === t ? null : t))}
      />
      {/* ── end WS5 ── */}
    </section>
  );
}

// ── WS5: TOOLS section (tab bar + active tool panel) ────────────────────────
type ToolTab = "builder" | "sizer" | "montecarlo";

function ToolsSection({
  symbol,
  active,
  onSelect,
}: {
  symbol: string;
  active: ToolTab | null;
  onSelect: (t: ToolTab) => void;
}) {
  const tabs: Array<{ key: ToolTab; label: string }> = [
    { key: "builder", label: "build" },
    { key: "sizer", label: "size" },
    { key: "montecarlo", label: "sim" },
  ];
  return (
    <div className="border-t border-hairline">
      <div className="flex items-center gap-1 px-3 py-1">
        <span
          className="uppercase tracking-label-up text-fg-tertiary-2 mr-1"
          style={{ fontSize: 10 }}
        >
          tools
        </span>
        {tabs.map((t) => {
          const on = active === t.key;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => onSelect(t.key)}
              aria-pressed={on}
              className={[
                "uppercase tracking-label-up rounded-btn px-2 transition-colors duration-100 select-none",
                on
                  ? "bg-tier-3 border border-amber text-amber"
                  : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
              ].join(" ")}
              style={{ height: 20, fontSize: 10 }}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      {active === "builder" && <StrategyBuilder symbol={symbol} />}
      {active === "sizer" && <PositionSizer />}
      {active === "montecarlo" && <MonteCarloPanel />}
    </div>
  );
}
// ── end WS5 ─────────────────────────────────────────────────────────────────

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
  premiumExit,
}: {
  selection: TicketSelection | null;
  contracts: number;
  premiumExit?: PremiumExitConfig;
}) {
  // Subtle live-price affordance: the chain refetch re-syncs the selected
  // contract's price (see RightChain), so flash the estimate briefly when it
  // moves — the trader sees the displayed risk is tracking the market.
  const price = selection?.price;
  const [flash, setFlash] = useState(false);
  const prevPrice = useRef<number | undefined>(price);
  useEffect(() => {
    const changed =
      price !== undefined &&
      prevPrice.current !== undefined &&
      price !== prevPrice.current;
    prevPrice.current = price;
    if (!changed) return;
    setFlash(true);
    const id = window.setTimeout(() => setFlash(false), 650);
    return () => window.clearTimeout(id);
  }, [price]);
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
      <span
        className={`text-tiny text-fg-secondary${flash ? " td-quick-flash" : ""}`}
        title="Tracks the live chain — refreshed with each chain update"
      >
        ${totalCost.toFixed(2)} debit
      </span>
      {beRange && (
        <>
          <span className="text-tiny text-fg-tertiary-2 uppercase">be</span>
          <span className="text-tiny text-position">{beRange}</span>
        </>
      )}
      {/* Premium-exit $ targets — entry premium × mult × 100 × qty, per
          direction. Only when the feature is armed; tracks the live price. */}
      {premiumExit?.enabled && (
        <PremiumExitTargets
          price={selection.price}
          contracts={contracts}
          config={premiumExit}
        />
      )}
    </div>
  );
}

/** Computed $ premium targets shown in the Summary. `null` mult = exit off. */
function PremiumExitTargets({
  price,
  contracts,
  config,
}: {
  price: number;
  contracts: number;
  config: PremiumExitConfig;
}) {
  const dollars = (mult: number) => (price * mult * 100 * contracts).toFixed(2);
  const group = (
    label: string,
    tp: number | null,
    sl: number | null,
    title: string,
  ) => {
    if (tp == null && sl == null) return null;
    return (
      <span className="text-tiny text-fg-tertiary-2 whitespace-nowrap" title={title}>
        {label}{" "}
        {tp != null && (
          <>
            tp <span className="text-position">${dollars(tp)}</span>
          </>
        )}
        {tp != null && sl != null && " · "}
        {sl != null && (
          <>
            sl <span className="text-bearish">${dollars(sl)}</span>
          </>
        )}
      </span>
    );
  };
  return (
    <>
      {group(
        "exit·long",
        config.longTpMult,
        config.longSlMult,
        "If BOUGHT: close when the position's premium value reaches the target (take-profit) or falls to the stop.",
      )}
      {group(
        "exit·short",
        config.shortTpMult,
        config.shortSlMult,
        "If SOLD: buy back at the target premium (a fraction of the credit = that share of max profit kept) or stop out at the stop premium.",
      )}
    </>
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
 * Order-type selector (Market | Limit | Stop | Stop-limit) + the option-premium
 * price input(s) that apply. A working order rests until the monitor sees the
 * mark cross the trigger:
 *   - limit / stop → one trigger (limit @ / stop @)
 *   - stop_limit   → arms @ stopPrice, then rests as a limit @ limitPrice
 */
function OrderTypeRow({
  orderType,
  setOrderType,
  limitPrice,
  setLimitPrice,
  stopPrice,
  setStopPrice,
  timeInForce,
  setTimeInForce,
}: {
  orderType: TicketOrderType;
  setOrderType: (t: TicketOrderType) => void;
  limitPrice: number | null;
  setLimitPrice: (p: number | null) => void;
  stopPrice: number | null;
  setStopPrice: (p: number | null) => void;
  timeInForce: "day" | "gtc";
  setTimeInForce: (t: "day" | "gtc") => void;
}) {
  const types: Array<{ key: TicketOrderType; label: string }> = [
    { key: "market", label: "market" },
    { key: "limit", label: "limit" },
    { key: "stop", label: "stop" },
    { key: "stop_limit", label: "stop lim" },
  ];
  const isStopLimit = orderType === "stop_limit";
  return (
    <div className="flex flex-col gap-1 px-3 pb-1 tabular-nums shrink-0">
      <div className="flex items-center gap-2">
        <div className="flex" style={{ gap: 4 }}>
          {types.map((t) => {
            const active = orderType === t.key;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setOrderType(t.key)}
                aria-pressed={active}
                className={[
                  "uppercase tracking-label-up transition-colors duration-100 select-none rounded-btn px-2",
                  active
                    ? "bg-tier-3 border border-amber text-amber"
                    : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
                ].join(" ")}
                style={{ height: 24, fontSize: 11 }}
              >
                {t.label}
              </button>
            );
          })}
        </div>
        {orderType !== "market" && !isStopLimit && (
          <PriceInput
            label={orderType === "stop" ? "stop @" : "limit @"}
            value={limitPrice}
            onChange={setLimitPrice}
            ariaLabel="Limit price (option premium)"
          />
        )}
      </div>
      {isStopLimit && (
        <div className="flex items-center gap-2 ml-auto">
          <PriceInput
            label="arms @"
            value={stopPrice}
            onChange={setStopPrice}
            ariaLabel="Stop arm price (option premium)"
          />
          <PriceInput
            label="limit @"
            value={limitPrice}
            onChange={setLimitPrice}
            ariaLabel="Resting limit price (option premium)"
          />
        </div>
      )}
      {orderType !== "market" && (
        <div className="flex items-center gap-1.5">
          <span
            className="uppercase tracking-label-up text-fg-tertiary-2"
            style={{ fontSize: 10 }}
          >
            TIF
          </span>
          {(["day", "gtc"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTimeInForce(t)}
              aria-pressed={timeInForce === t}
              title={
                t === "day"
                  ? "Day — cancelled at the next session if still unfilled"
                  : "GTC — rests until filled or cancelled"
              }
              className={[
                "uppercase tracking-label-up rounded-btn px-2 transition-colors duration-100 select-none",
                timeInForce === t
                  ? "bg-tier-3 border border-amber text-amber"
                  : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
              ].join(" ")}
              style={{ height: 22, fontSize: 10 }}
            >
              {t}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Optional trailing-stop EXIT — a checkbox that, when on, reveals a $/share
 * "trail" input. Attaches a trailing stop to the position at open: the monitor
 * trails the favorable option mark and stops the position out when the mark
 * retraces past (high-water − trail). Off (null) by default.
 */
function TrailStopRow({
  trailAmount,
  setTrailAmount,
}: {
  trailAmount: number | null;
  setTrailAmount: (a: number | null) => void;
}) {
  const on = trailAmount != null;
  return (
    <div className="flex items-center gap-2 px-3 pb-1 tabular-nums shrink-0" style={{ fontSize: 12 }}>
      <button
        type="button"
        onClick={() => setTrailAmount(on ? null : 0.1)}
        aria-pressed={on}
        className={[
          "uppercase tracking-label-up transition-colors duration-100 select-none rounded-btn px-2",
          on
            ? "bg-tier-3 border border-amber text-amber"
            : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
        ].join(" ")}
        style={{ height: 24, fontSize: 11 }}
        title="Attach a trailing stop: the position exits when the option mark retraces this far from its favorable high-water."
      >
        trail stop
      </button>
      {on && (
        <PriceInput
          label="trail $"
          value={trailAmount}
          onChange={(v) => setTrailAmount(v != null && v > 0 ? v : null)}
          ariaLabel="Trailing stop distance ($/share)"
        />
      )}
    </div>
  );
}

/**
 * Optional PREMIUM EXIT presets — "close at 2× / 50% max profit".
 * Collapsed (a single toggle) until armed. Two preset groups because the
 * semantics flip with direction:
 *   - long · buy (net-debit): TP/SL as multiples of the entry premium.
 *   - short · sell (net-credit): Tastytrade-style — TP as the fraction of
 *     the credit to buy back at (50% = keep half of max profit), SL at a
 *     multiple of the credit (2× = stop when the mark doubles).
 * Clicking the active chip turns that exit off (null). Last-used config
 * persists in the ticket store.
 */
function PremiumExitRow({
  config,
  onChange,
}: {
  config: PremiumExitConfig;
  onChange: (patch: Partial<PremiumExitConfig>) => void;
}) {
  const on = config.enabled;
  return (
    <div
      className="flex flex-col gap-1 px-3 pb-1 tabular-nums shrink-0"
      style={{ fontSize: 12 }}
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onChange({ enabled: !on })}
          aria-pressed={on}
          aria-expanded={on}
          className={[
            "uppercase tracking-label-up transition-colors duration-100 select-none rounded-btn px-2",
            on
              ? "bg-tier-3 border border-amber text-amber"
              : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
          ].join(" ")}
          style={{ height: 24, fontSize: 11 }}
          title="Attach premium-based exits at open: take-profit / stop-loss as multiples of the entry premium (e.g. sell at 2× the debit, or buy a short back at 50% of the credit). The direction you fire picks which row applies."
        >
          premium exit
        </button>
        {!on && (
          <span className="text-fg-tertiary-2" style={{ fontSize: 11 }}>
            off
          </span>
        )}
      </div>
      {on && (
        <div className="flex flex-col gap-1 pl-0.5">
          <MultPresetLine
            label="long · buy"
            tpValue={config.longTpMult}
            tpPresets={[
              { mult: 1.5, label: "1.5×" },
              { mult: 2, label: "2×" },
              { mult: 3, label: "3×" },
            ]}
            tpTitle={(m) =>
              `Take profit: sell when the premium reaches ${m}× entry.`
            }
            slValue={config.longSlMult}
            slPresets={[
              { mult: 0.5, label: "0.5×" },
              { mult: 0.25, label: "0.25×" },
            ]}
            slTitle={(m) => `Stop loss: cut when the premium falls to ${m}× entry.`}
            onTp={(v) => onChange({ longTpMult: v })}
            onSl={(v) => onChange({ longSlMult: v })}
          />
          <MultPresetLine
            label="short · sell"
            tpValue={config.shortTpMult}
            tpPresets={[
              { mult: 0.5, label: "50%" },
              { mult: 0.25, label: "25%" },
            ]}
            tpTitle={(m) =>
              `Take profit at ${Math.round((1 - m) * 100)}% of max profit: buy the short back at ${Math.round(m * 100)}% of the credit received.`
            }
            slValue={config.shortSlMult}
            slPresets={[{ mult: 2, label: "2×" }]}
            slTitle={(m) =>
              `Stop loss: buy back when the mark reaches ${m}× the credit received.`
            }
            onTp={(v) => onChange({ shortTpMult: v })}
            onSl={(v) => onChange({ shortSlMult: v })}
          />
        </div>
      )}
    </div>
  );
}

/** One direction's TP + SL preset chips + custom multiple inputs. */
function MultPresetLine({
  label,
  tpValue,
  tpPresets,
  tpTitle,
  slValue,
  slPresets,
  slTitle,
  onTp,
  onSl,
}: {
  label: string;
  tpValue: number | null;
  tpPresets: Array<{ mult: number; label: string }>;
  tpTitle: (m: number) => string;
  slValue: number | null;
  slPresets: Array<{ mult: number; label: string }>;
  slTitle: (m: number) => string;
  onTp: (v: number | null) => void;
  onSl: (v: number | null) => void;
}) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 10, width: 72 }}
      >
        {label}
      </span>
      <MultGroup
        name="tp"
        value={tpValue}
        presets={tpPresets}
        title={tpTitle}
        onChange={onTp}
      />
      <MultGroup
        name="sl"
        value={slValue}
        presets={slPresets}
        title={slTitle}
        onChange={onSl}
      />
    </div>
  );
}

function MultGroup({
  name,
  value,
  presets,
  title,
  onChange,
}: {
  name: string;
  value: number | null;
  presets: Array<{ mult: number; label: string }>;
  title: (m: number) => string;
  onChange: (v: number | null) => void;
}) {
  const isCustom =
    value != null && !presets.some((p) => Math.abs(p.mult - value) < 1e-9);
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 10 }}
      >
        {name}
      </span>
      {presets.map((p) => {
        const active = value != null && Math.abs(p.mult - value) < 1e-9;
        return (
          <button
            key={p.mult}
            type="button"
            onClick={() => onChange(active ? null : p.mult)}
            aria-pressed={active}
            title={`${title(p.mult)} Click again to turn this exit off.`}
            className={[
              "tabular-nums tracking-label-up rounded-btn px-1.5 transition-colors duration-100 select-none",
              active
                ? "bg-tier-3 border border-amber text-amber"
                : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
            ].join(" ")}
            style={{ height: 20, fontSize: 10 }}
          >
            {p.label}
          </button>
        );
      })}
      <input
        type="number"
        inputMode="decimal"
        min={0.05}
        step={0.05}
        value={isCustom ? value : ""}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          onChange(Number.isFinite(v) && v > 0 ? v : null);
        }}
        placeholder="×"
        aria-label={`Custom ${name} premium multiple`}
        title="Custom multiple of the entry premium (blank = off)."
        className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums text-right px-1"
        style={{ width: 44, height: 20, fontSize: 10 }}
      />
    </span>
  );
}

function PriceInput({
  label,
  value,
  onChange,
  ariaLabel,
}: {
  label: string;
  value: number | null;
  onChange: (p: number | null) => void;
  ariaLabel: string;
}) {
  return (
    <label className="flex items-center gap-1" style={{ fontSize: 12 }}>
      <span className="uppercase tracking-label-up text-fg-tertiary-2">{label}</span>
      <input
        type="number"
        inputMode="decimal"
        min={0}
        step={0.01}
        value={value ?? ""}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          onChange(Number.isFinite(v) ? v : null);
        }}
        placeholder="0.00"
        aria-label={ariaLabel}
        className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums text-right px-1.5"
        style={{ width: 64, height: 24, fontSize: 12 }}
      />
    </label>
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
  buyRef,
  sellRef,
}: {
  selection: TicketSelection | null;
  contracts: number;
  disabled: boolean;
  pending: boolean;
  marketOpen: boolean;
  onBuy: () => void;
  onSell: () => void;
  buyRef?: React.Ref<HTMLButtonElement>;
  sellRef?: React.Ref<HTMLButtonElement>;
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
        buttonRef={buyRef}
      />
      <ActionButton
        intent="sell"
        label={`SELL -${contracts}`}
        sub={sellSub}
        disabled={disabled}
        onClick={onSell}
        buttonRef={sellRef}
      />
    </div>
  );
}

/* ── WS6 RISK PREVIEW component + helpers (BEGIN) ──────────────────────────
 *
 * Pre-trade risk summary for the configured order. Reuses the existing
 * `computeBreakevens()` (above) and the same `price × 100 × contracts` debit
 * math the Summary/Actions already use — no new pricing source. Reads only
 * `selection` + `contracts`, so it stays decoupled from the rest of the ticket
 * (and from WS5's multi-leg work, which merges first — see the delimited call
 * site above).
 *
 * Definitions shown:
 *   - MAX LOSS : a long (the BUY direction) caps loss at the full debit. A
 *     short's loss is unbounded, so for shorts we say so rather than print a
 *     misleading number — mirroring DllRiskHint's deliberate-silence stance.
 *   - BREAKEVEN: the underlying price(s) at expiry (magenta band on the chart).
 *   - R-MULTIPLE: with risk R = the debit, the underlying targets that return
 *     +1R / +2R on the position (premium doubles / triples for a long). Gives
 *     the trader a reward-in-underlying-terms reference before they fire.
 */
interface RiskPreviewData {
  /** LONG (buy) max loss = the full debit — always bounded. */
  maxLoss: number;
  breakevens: string | null;
  /** Underlying price at +1R / +2R profit (premium 2× / 3×), long single-leg. */
  target1R: number | null;
  target2R: number | null;
  /** LONG (buy) max profit — null = UNBOUNDED (long call / long straddle). */
  longMaxProfit: number | null;
  /** SHORT (sell) max loss — null = UNBOUNDED (naked short call / short straddle). */
  shortMaxLoss: number | null;
  /** Premium RECEIVED if sold — the short's max profit (keep it if worthless). */
  shortCredit: number;
}

export function riskPreviewFor(
  selection: TicketSelection,
  contracts: number,
): RiskPreviewData {
  // Same magnitude whether you BUY (debit) or SELL (credit).
  const notional = selection.price * 100 * contracts;
  const breakevens = computeBreakevens(selection);

  // R-multiple in underlying terms: the long pays `price` premium; at +1R the
  // option is worth 2×price (one R of profit), at +2R it's 3×price. For a
  // single call/put that maps to an underlying move of `nR × price` past the
  // breakeven in the option's favorable direction. Straddles move either way,
  // so we don't print a single directional target.
  let target1R: number | null = null;
  let target2R: number | null = null;

  // Bounds differ by side. A call's upside (long) and a naked short call's
  // downside are both UNBOUNDED. A put is capped because the underlying can't
  // go below 0: a long put's max gain and a short put's max loss are both the
  // assignment-to-zero value (strike − premium) × 100 × contracts. A straddle
  // carries a call leg, so both its long upside and short loss are unbounded.
  let longMaxProfit: number | null;
  let shortMaxLoss: number | null;

  if (selection.kind === "leg") {
    const be =
      selection.side === "call"
        ? selection.strike + selection.price
        : selection.strike - selection.price;
    const step = selection.price; // one R of underlying move past BE
    if (selection.side === "call") {
      target1R = be + step;
      target2R = be + 2 * step;
      longMaxProfit = null; // long call → unbounded upside
      shortMaxLoss = null; // short call → unbounded loss
    } else {
      target1R = be - step;
      target2R = be - 2 * step;
      const toZero = (selection.strike - selection.price) * 100 * contracts;
      longMaxProfit = toZero; // long put → max gain if underlying → 0
      shortMaxLoss = toZero; // short put → max loss if assigned (underlying → 0)
    }
  } else {
    longMaxProfit = null; // long straddle → unbounded (the call leg)
    shortMaxLoss = null; // short straddle → unbounded (the call leg)
  }

  return {
    maxLoss: notional,
    breakevens,
    target1R,
    target2R,
    longMaxProfit,
    shortMaxLoss,
    shortCredit: notional,
  };
}

function RiskPreview({
  selection,
  contracts,
}: {
  selection: TicketSelection;
  contracts: number;
}) {
  const {
    maxLoss,
    breakevens,
    target1R,
    target2R,
    longMaxProfit,
    shortMaxLoss,
    shortCredit,
  } = riskPreviewFor(selection, contracts);
  if (!Number.isFinite(maxLoss) || maxLoss <= 0) return null;

  // null bound = unbounded; show it in words, never a fake number.
  const money = (v: number) => `$${v.toFixed(2)}`;
  const bound = (v: number | null) => (v == null ? "unbounded" : money(v));
  const lbl = "uppercase tracking-label-up text-fg-tertiary-2";

  return (
    <div
      className="mx-3 mb-1 px-2 py-1.5 bg-tier-1 border border-hairline rounded-btn tabular-nums"
      style={{ fontSize: 12 }}
      aria-label="Risk preview for this order"
    >
      <span className={lbl} style={{ fontSize: 10 }}>
        risk preview
      </span>
      {/* Both directions, max loss + max profit. Loss bearish, profit position;
          an UNBOUNDED loss (naked short call / short straddle) is flagged warning. */}
      <div
        className="mt-1 grid items-baseline gap-x-3 gap-y-0.5"
        style={{ gridTemplateColumns: "auto 1fr 1fr" }}
      >
        <span />
        <span className={lbl} style={{ fontSize: 10 }}>max loss</span>
        <span className={lbl} style={{ fontSize: 10 }}>max profit</span>

        <span className={lbl} style={{ fontSize: 10 }}>long · buy</span>
        <span className="text-bearish">{money(maxLoss)}</span>
        <span className="text-position">{bound(longMaxProfit)}</span>

        <span className={lbl} style={{ fontSize: 10 }}>short · sell</span>
        <span
          className={shortMaxLoss == null ? "text-warning" : "text-bearish"}
          title={
            shortMaxLoss == null
              ? "A naked short call / short straddle has no upside cap on the underlying — loss is unbounded."
              : "Short put assigned with the underlying at 0: (strike − premium) × 100 × contracts."
          }
        >
          {bound(shortMaxLoss)}
        </span>
        <span className="text-position">
          {money(shortCredit)}
          <span className="text-fg-tertiary-2"> credit</span>
        </span>
      </div>
      <div className="mt-1 pt-1 border-t border-hairline flex items-baseline gap-x-4 flex-wrap">
        {breakevens && <Stat label="breakeven" value={breakevens} tone="text-position" />}
        {target1R != null && (
          <Stat
            label="+1R / +2R"
            value={`$${target1R.toFixed(2)} · $${(target2R ?? target1R).toFixed(2)}`}
            tone="text-fg-secondary"
            title="Underlying price where a LONG returns +1R / +2R (R = the debit risked)."
          />
        )}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
  title,
}: {
  label: string;
  value: string;
  tone: string;
  title?: string;
}) {
  return (
    <span className="inline-flex items-baseline gap-1" title={title}>
      <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 10 }}>
        {label}
      </span>
      <span className={tone}>{value}</span>
    </span>
  );
}
/* ── WS6 RISK PREVIEW component + helpers (END) ────────────────────────────── */

function ActionButton({
  intent,
  label,
  sub,
  disabled,
  onClick,
  buttonRef,
}: {
  intent: "buy" | "sell";
  label: string;
  sub: string;
  disabled: boolean;
  onClick: () => void;
  buttonRef?: React.Ref<HTMLButtonElement>;
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
      ref={buttonRef}
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
