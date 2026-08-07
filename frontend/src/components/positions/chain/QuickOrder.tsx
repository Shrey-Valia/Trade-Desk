import { useEffect, useId, useRef, useState } from "react";

import { useOpenZeroDteLeg } from "@/hooks/useOpenZeroDteLeg";
import type { TicketOrderType } from "@/stores/tradeTicket";

/**
 * DOM-lite one-click ticket. A tiny popover anchored to a call/put chain
 * cell (opened by right-click / long-press) that fires
 * {@link useOpenZeroDteLeg} DIRECTLY — bypassing the select→TradeTicket flow
 * for fast, ladder-style order entry.
 *
 * Minimal surface: qty stepper + order-type chips + BUY/SELL. A limit/stop/
 * stop-limit reveals a single trigger input (option-premium), seeded from the
 * cell's indicative price. Market fires immediately. On a successful fire the
 * parent flashes the row amber (via `onFired`) and the popover closes.
 *
 * Closes on: Escape, outside-click, or a successful fire. Focus traps to the
 * panel on open and restores to the anchor on close for keyboard users.
 */
export interface QuickOrderTarget {
  symbol: string;
  side: "call" | "put";
  strike: number;
  /** Indicative per-share premium for this cell (seed for limit/stop). */
  price: number;
  expiry: string;
  /** Viewport anchor — the cell's bounding rect (for positioning). */
  anchor: { x: number; y: number };
}

interface Props {
  target: QuickOrderTarget;
  /** Live indicative premium for this cell, refreshed by the parent on each
   *  chain refetch. Falls back to `target.price` (the open-time snapshot) when
   *  null. Keeps the seed from going stale while the popover sits open. */
  livePrice: number | null;
  /** Remaining contracts allowed by the scaling cap (clamps qty + presets). */
  maxContracts: number;
  onClose: () => void;
  /** Fired after a successful open so the parent can flash the row. */
  onFired: () => void;
}

const PANEL_W = 196;
const ORDER_TYPES: Array<{ key: TicketOrderType; label: string }> = [
  { key: "market", label: "mkt" },
  { key: "limit", label: "lmt" },
  { key: "stop", label: "stop" },
];

export function QuickOrder({
  target,
  livePrice,
  maxContracts,
  onClose,
  onFired,
}: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const open = useOpenZeroDteLeg();

  // The freshest indicative premium — live quote when the parent has one, else
  // the open-time snapshot. Drives the auto-seed AND the display-only entry
  // price we send (server re-prices market fills anyway, but be honest).
  const currentPrice = livePrice ?? target.price;

  const cap = Math.max(1, maxContracts);
  const [contracts, setContracts] = useState(1);
  const [orderType, setOrderType] = useState<TicketOrderType>("market");
  const [trigger, setTrigger] = useState<number | null>(currentPrice);
  // Once the user types a trigger, stop auto-tracking the live price so we
  // never clobber their chosen limit; until then the seed follows the market.
  const [triggerDirty, setTriggerDirty] = useState(false);
  const submittingRef = useRef(false);

  // Re-seed the (unedited) trigger to the live premium as the chain refetches,
  // so a limit/stop placed without touching the field defaults to the CURRENT
  // price, not the premium from whenever the popover happened to open.
  useEffect(() => {
    if (!triggerDirty && currentPrice > 0) setTrigger(currentPrice);
  }, [currentPrice, triggerDirty]);

  const needsTrigger = orderType !== "market";
  const triggerOk = !needsTrigger || (trigger != null && trigger > 0);
  // Surface how far a user-set trigger has drifted from the live premium.
  const triggerDrift =
    needsTrigger && triggerDirty && trigger != null && currentPrice > 0
      ? trigger - currentPrice
      : null;

  // Clamp qty to the live scaling cap (mirrors the TradeTicket clamp so a
  // quick order can never exceed the remaining size the server would accept).
  useEffect(() => {
    setContracts((c) => Math.min(cap, Math.max(1, c)));
  }, [cap]);

  // Close on Escape + outside-click; restore focus to the previously focused
  // element (the anchored cell) on unmount.
  useEffect(() => {
    const prevFocus = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    const onDown = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("keydown", onKey, true);
    // Defer the outside-click listener a tick so the opening right-click /
    // long-press that mounted us doesn't immediately close us.
    const id = window.setTimeout(
      () => document.addEventListener("mousedown", onDown, true),
      0,
    );
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("mousedown", onDown, true);
      window.clearTimeout(id);
      prevFocus?.focus?.();
    };
  }, [onClose]);

  const fire = (action: "buy" | "sell") => {
    if (submittingRef.current || !triggerOk) return;
    submittingRef.current = true;
    open.mutate(
      {
        symbol: target.symbol,
        side: target.side,
        action,
        strike: target.strike,
        entry_price: currentPrice,
        contracts,
        order_type: orderType,
        limit_price: needsTrigger ? trigger : null,
        stop_price: null,
        trail_amount: null,
        // Match the main ticket's default (tradeTicket store) so the same
        // product doesn't rest a working order for a different lifetime
        // depending on which surface placed it — the wire default is "gtc".
        time_in_force: "day",
      },
      {
        onSuccess: () => {
          onFired();
          onClose();
        },
        onSettled: () => {
          submittingRef.current = false;
        },
      },
    );
  };

  // Position the panel near the anchor, clamped into the viewport. Anchored
  // above-left of the cursor so it doesn't cover the row the user is acting on.
  const left = Math.max(
    8,
    Math.min(target.anchor.x, window.innerWidth - PANEL_W - 8),
  );
  const top = Math.max(8, target.anchor.y);

  const sideLabel = target.side.toUpperCase();
  const pending = open.isPending;

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      tabIndex={-1}
      className="fixed z-50 bg-tier-1 border border-amber rounded-btn shadow-lg outline-none tabular-nums"
      style={{ left, top, width: PANEL_W, fontSize: 12 }}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div
        id={titleId}
        className="flex items-baseline justify-between px-2 py-1 border-b border-hairline"
      >
        <span className="uppercase tracking-label-up text-amber font-medium">
          Quick · {target.strike} {sideLabel}
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close quick order"
          className="text-fg-tertiary hover:text-fg-primary leading-none"
          style={{ fontSize: 14 }}
        >
          ×
        </button>
      </div>

      <div className="flex flex-col gap-1.5 px-2 py-1.5">
        {/* Order-type chips */}
        <div className="flex" style={{ gap: 4 }}>
          {ORDER_TYPES.map((t) => {
            const active = orderType === t.key;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => {
                  setOrderType(t.key);
                  if (t.key !== "market" && trigger == null) {
                    setTrigger(currentPrice);
                    setTriggerDirty(false);
                  }
                }}
                aria-pressed={active}
                className={[
                  "uppercase tracking-label-up rounded-btn px-1.5 transition-colors duration-100 select-none",
                  active
                    ? "bg-tier-3 border border-amber text-amber"
                    : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
                ].join(" ")}
                style={{ height: 22, fontSize: 11 }}
              >
                {t.label}
              </button>
            );
          })}
        </div>

        {needsTrigger && (
          <label className="flex items-center gap-1">
            <span className="uppercase tracking-label-up text-fg-tertiary-2">
              {orderType === "stop" ? "stop @" : "limit @"}
            </span>
            <input
              type="number"
              inputMode="decimal"
              min={0}
              step={0.01}
              value={trigger ?? ""}
              onChange={(e) => {
                setTriggerDirty(true);
                const v = parseFloat(e.target.value);
                setTrigger(Number.isFinite(v) ? v : null);
              }}
              placeholder="0.00"
              aria-label="Trigger price (option premium)"
              className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums text-right px-1.5"
              style={{ width: 64, height: 22, fontSize: 12 }}
            />
            <span
              className="text-fg-tertiary-2 tabular-nums"
              style={{ fontSize: 11 }}
              title="Live indicative premium — the seed tracks this until you type your own."
            >
              live {currentPrice.toFixed(2)}
              {triggerDrift != null && Math.abs(triggerDrift) >= 0.01 && (
                <span className="text-warning ml-1">
                  ({triggerDrift > 0 ? "+" : "−"}
                  {Math.abs(triggerDrift).toFixed(2)})
                </span>
              )}
            </span>
          </label>
        )}

        {/* Qty stepper */}
        <div className="flex items-center" style={{ gap: 4 }}>
          <QtyButton
            aria-label="Decrease quantity"
            disabled={contracts <= 1}
            onClick={() => setContracts((c) => Math.max(1, c - 1))}
          >
            −
          </QtyButton>
          <div
            aria-live="polite"
            className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums flex items-center justify-center"
            style={{ width: 44, height: 24, fontSize: 14, fontWeight: 500 }}
          >
            {contracts}
          </div>
          <QtyButton
            aria-label="Increase quantity"
            disabled={contracts >= cap}
            onClick={() => setContracts((c) => Math.min(cap, c + 1))}
          >
            +
          </QtyButton>
          <span
            className="uppercase tracking-label-up text-fg-tertiary-2 ml-auto"
            style={{ fontSize: 11 }}
            title="Remaining contracts allowed by the scaling cap"
          >
            {cap} left
          </span>
        </div>

        {/* BUY / SELL */}
        <div className="grid grid-cols-2 gap-1.5" style={{ height: 30 }}>
          <button
            type="button"
            disabled={pending || !triggerOk}
            onClick={() => fire("buy")}
            className={[
              "rounded-btn font-semibold tracking-wide flex items-center justify-center transition-colors duration-100",
              pending || !triggerOk
                ? "bg-tier-1 text-fg-disabled cursor-not-allowed"
                : "bg-action-buy hover:bg-action-buy-hover active:bg-action-buy-active text-white",
            ].join(" ")}
            style={{ fontSize: 12 }}
          >
            {pending ? "…" : `BUY +${contracts}`}
          </button>
          <button
            type="button"
            disabled={pending || !triggerOk}
            onClick={() => fire("sell")}
            className={[
              "rounded-btn font-semibold tracking-wide flex items-center justify-center transition-colors duration-100",
              pending || !triggerOk
                ? "bg-tier-1 text-fg-disabled cursor-not-allowed"
                : "bg-action-sell hover:bg-action-sell-hover active:bg-action-sell-active text-white",
            ].join(" ")}
            style={{ fontSize: 12 }}
          >
            {pending ? "…" : `SELL -${contracts}`}
          </button>
        </div>
        {open.isError && (
          <div
            className="text-bearish truncate"
            style={{ fontSize: 11 }}
            title={(open.error as Error)?.message}
          >
            {(open.error as Error)?.message || "Could not place order"}
          </div>
        )}
      </div>
    </div>
  );
}

function QtyButton({
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
        "rounded-btn flex items-center justify-center select-none transition-colors duration-100",
        disabled
          ? "bg-tier-1 text-fg-disabled cursor-not-allowed border border-tier-2"
          : "bg-tier-2 border border-tier-3 text-fg-primary hover:bg-tier-3",
      ].join(" ")}
      style={{ width: 24, height: 24, fontSize: 14, lineHeight: 1 }}
    >
      {children}
    </button>
  );
}
