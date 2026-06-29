import { useEffect, useMemo, useRef, useState } from "react";

import { useHotkeyActions } from "@/stores/hotkeyActions";
import { useAccountState } from "@/hooks/useAccountState";
import { useTrades } from "@/hooks/useTrades";
import { useCombineStatus } from "@/hooks/useCombineStatus";
import { useMarketStatus } from "@/hooks/useMarket";
import { useOpenZeroDteLeg } from "@/hooks/useOpenZeroDteLeg";
import { useOpenZeroDteStraddle } from "@/hooks/useOpenZeroDteStraddle";
import {
  useTradeTicket,
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
  const needsStop = effectiveOrderType === "stop_limit";
  const limitOk = !needsLimit || (limitPrice != null && limitPrice > 0);
  // At the scaling cap: no remaining capacity, or the chosen size would push
  // total open past the cap. Blocks the BUY (server enforces this too).
  const atCap = remaining <= 0 || contracts > remaining;
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
  // ── end WS5

  // WS6 power-UX: the B/S hotkeys "pre-arm" by focusing the matching action
  // button (not auto-firing — a stray keypress must never place an order). The
  // global hotkey hook publishes the intent on the action bus; we consume it
  // here and move focus so the user confirms with Enter/Space.
  const buyBtnRef = useRef<HTMLButtonElement>(null);
  const sellBtnRef = useRef<HTMLButtonElement>(null);
  const hotkeyIntent = useHotkeyActions((s) => s.intent);
  const hotkeyNonce = useHotkeyActions((s) => s.nonce);
  const consumeHotkey = useHotkeyActions((s) => s.consume);
  useEffect(() => {
    if (hotkeyIntent === "armBuy") {
      buyBtnRef.current?.focus();
      consumeHotkey();
    } else if (hotkeyIntent === "armSell") {
      sellBtnRef.current?.focus();
      consumeHotkey();
    }
    // closeActive is handled by the active-position panel, not the ticket.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hotkeyIntent, hotkeyNonce]);

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
        time_in_force: needsLimit ? timeInForce : "gtc",
        limit_price: needsLimit ? limitPrice : null,
        stop_price: needsStop ? stopPrice : null,
        trail_amount: trailAmount && trailAmount > 0 ? trailAmount : null,
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
          stopPrice={stopPrice}
          setStopPrice={setStopPrice}
          timeInForce={timeInForce}
          setTimeInForce={setTimeInForce}
        />
      )}
      {isLeg && (
        <TrailStopRow trailAmount={trailAmount} setTrailAmount={setTrailAmount} />
      )}
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
        symbol={selection.symbol}
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
  maxLoss: number;
  breakevens: string | null;
  /** Underlying price at +1R / +2R profit (premium 2× / 3×), long only. */
  target1R: number | null;
  target2R: number | null;
}

export function riskPreviewFor(
  selection: TicketSelection,
  contracts: number,
): RiskPreviewData {
  const debit = selection.price * 100 * contracts;
  const breakevens = computeBreakevens(selection);

  // R-multiple in underlying terms: the long pays `price` premium; at +1R the
  // option is worth 2×price (one R of profit), at +2R it's 3×price. For a
  // single call/put that maps to an underlying move of `nR × price` past the
  // breakeven in the option's favorable direction. Straddles move either way,
  // so we don't print a single directional target.
  let target1R: number | null = null;
  let target2R: number | null = null;
  if (selection.kind === "leg") {
    const be =
      selection.side === "call"
        ? selection.strike + selection.price
        : selection.strike - selection.price;
    const step = selection.price; // one R of underlying move past BE
    if (selection.side === "call") {
      target1R = be + step;
      target2R = be + 2 * step;
    } else {
      target1R = be - step;
      target2R = be - 2 * step;
    }
  }

  return { maxLoss: debit, breakevens, target1R, target2R };
}

function RiskPreview({
  selection,
  contracts,
}: {
  selection: TicketSelection;
  contracts: number;
}) {
  const { maxLoss, breakevens, target1R, target2R } = riskPreviewFor(
    selection,
    contracts,
  );
  if (!Number.isFinite(maxLoss) || maxLoss <= 0) return null;

  return (
    <div
      className="mx-3 mb-1 px-2 py-1.5 bg-tier-1 border border-hairline rounded-btn tabular-nums"
      style={{ fontSize: 12 }}
      aria-label="Risk preview for this order"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 10 }}>
          risk preview
        </span>
        <span
          className="uppercase tracking-label-up text-fg-tertiary-2"
          style={{ fontSize: 10 }}
          title="If bought (long), loss is capped at the full debit. A short's loss is not premium-bounded."
        >
          if long
        </span>
      </div>
      <div className="flex items-baseline gap-x-4 gap-y-0.5 flex-wrap mt-0.5">
        <Stat label="max loss" value={`$${maxLoss.toFixed(2)}`} tone="text-bearish" />
        {breakevens && <Stat label="breakeven" value={breakevens} tone="text-position" />}
        {target1R != null && (
          <Stat
            label="+1R / +2R"
            value={`$${target1R.toFixed(2)} · $${(target2R ?? target1R).toFixed(2)}`}
            tone="text-fg-secondary"
            title="Underlying price where the option returns +1R / +2R (R = the debit risked)."
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
