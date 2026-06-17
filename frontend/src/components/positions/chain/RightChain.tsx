import { useEffect, useRef } from "react";

import { useChainTable } from "@/hooks/useChainTable";
import { useMarketStatus } from "@/hooks/useMarket";
import { useTradeTicket } from "@/stores/tradeTicket";
import type { ChainStrikeRow } from "@/types/zerodte";

/**
 * Upper-right column option chain — dense Bloomberg-style layout
 * intended to fit in a ~452px wide column. ~16 strikes visible
 * without scrolling (8 above ATM, 8 below).
 *
 * Layout: CALL price (right) | STRIKE (center) | PUT price (left).
 * ATM row: amber left-border + bg-tier-1 fill + amber values.
 *
 * Click semantics (Phase 5 — select-only, no immediate fire):
 *   - Call cell  → select call-leg at that strike in the ticket
 *   - Put cell   → select put-leg at that strike in the ticket
 *   - Strike cell on ATM row → select straddle at that strike
 *   - Strike cell off ATM → select call-leg at that strike
 *
 * The actual BUY or SELL fires from the trade ticket below the chain,
 * not from these clicks. Direction is which of the ticket's two
 * buttons the user presses.
 *
 * Read-only states (dim cells, no-op clicks):
 *   - market closed
 *   - chain query returned "No 0DTE for {symbol} today"
 */
interface Props {
  symbol: string | null;
}

// Topstep DOM-style ladder — taller rows (20px), wider center strike
// column anchored with a subtle bg-tier-1 tint, hairline every 5 rows.
const ROW_HEIGHT = 20;
const CALL_W = 168;
const STRIKE_W = 88;
const PUT_W = 168;
const GRID = `${CALL_W}px ${STRIKE_W}px ${PUT_W}px`;

export function RightChain({ symbol }: Props) {
  // Pull 5 strikes above + 5 below ATM ⇒ ~11 rows visible without
  // scrolling. The previous redesign asked for 16; the simplification
  // pass dropped that to reduce the right column's visual weight.
  const { data, isLoading, isError, error } = useChainTable(symbol, 5);
  const setSelection = useTradeTicket((s) => s.setSelection);
  const currentSelection = useTradeTicket((s) => s.selection);
  const { data: marketStatus } = useMarketStatus();
  const marketOpen = marketStatus?.status === "open";

  const bodyRef = useRef<HTMLDivElement>(null);
  const atmStrike = data?.atm_strike ?? null;

  // Auto-scroll ATM row to center on symbol change.
  useEffect(() => {
    if (!bodyRef.current || atmStrike == null) return;
    const row = bodyRef.current.querySelector<HTMLElement>(
      `[data-strike="${atmStrike}"]`,
    );
    if (row) row.scrollIntoView({ block: "center", behavior: "auto" });
  }, [atmStrike, symbol]);

  const chainErrMsg = isError ? (error as Error)?.message ?? "" : "";
  const noZeroDteToday = chainErrMsg.startsWith("No 0DTE for");
  // Cells are clickable to PREVIEW a contract (payoff/greeks in the detail
  // panel) whenever a chain exists — even with the market closed. Trading
  // (BUY/SELL) stays gated in the ticket; selecting is view-only.

  const onClickCall = (row: ChainStrikeRow) => {
    if (!data || noZeroDteToday) return;
    setSelection({
      kind: "leg",
      side: "call",
      symbol: data.underlying,
      strike: row.strike,
      price: row.call_price,
      expiry: data.expiry,
    });
  };
  const onClickPut = (row: ChainStrikeRow) => {
    if (!data || noZeroDteToday) return;
    setSelection({
      kind: "leg",
      side: "put",
      symbol: data.underlying,
      strike: row.strike,
      price: row.put_price,
      expiry: data.expiry,
    });
  };
  const onClickStrike = (row: ChainStrikeRow) => {
    if (!data || noZeroDteToday) return;
    if (row.is_atm) {
      setSelection({
        kind: "straddle",
        symbol: data.underlying,
        strike: row.strike,
        // Straddle "price" = call + put premium (debit if long).
        price: row.call_price + row.put_price,
        expiry: data.expiry,
      });
      return;
    }
    setSelection({
      kind: "leg",
      side: "call",
      symbol: data.underlying,
      strike: row.strike,
      price: row.call_price,
      expiry: data.expiry,
    });
  };

  return (
    <section className="flex flex-col bg-tier-0">
      <Header
        symbol={data?.underlying ?? symbol ?? "—"}
        expiry={data?.expiry ?? null}
        spot={data?.spot ?? null}
        atm={data?.atm_strike ?? null}
        iv={data?.iv_used ?? null}
      />
      <ColumnHeader />
      {!marketOpen && data && (
        <div
          className="px-3 py-1 border-b border-hairline bg-tier-1 text-warning text-center shrink-0"
          style={{ fontSize: 10 }}
          role="status"
        >
          Market closed — indicative pricing; tap a contract to preview, trading resumes next session
        </div>
      )}
      <div
        ref={bodyRef}
        className="overflow-y-auto"
        style={{ scrollbarGutter: "stable", maxHeight: 360 }}
      >
        {!symbol && <EmptyMessage>Pick a ticker in the header.</EmptyMessage>}
        {symbol && isLoading && !data && (
          <EmptyMessage>Loading {symbol} chain…</EmptyMessage>
        )}
        {noZeroDteToday && (
          <EmptyMessage tone="warning">{chainErrMsg}</EmptyMessage>
        )}
        {isError && !noZeroDteToday && (
          <EmptyMessage tone="bearish">{chainErrMsg}</EmptyMessage>
        )}
        {data && data.rows.length > 0 && (
          <div className="flex flex-col items-center">
            {data.rows.map((row, idx) => {
              const selStrike =
                currentSelection?.symbol === data.underlying
                  ? currentSelection.strike
                  : null;
              const selKind = currentSelection?.kind ?? null;
              const selSide = currentSelection?.side ?? null;
              const selectedCall =
                selStrike === row.strike &&
                (selKind === "straddle" ||
                  (selKind === "leg" && selSide === "call"));
              const selectedPut =
                selStrike === row.strike &&
                (selKind === "straddle" ||
                  (selKind === "leg" && selSide === "put"));
              return (
                <Row
                  key={row.strike}
                  row={row}
                  disabled={noZeroDteToday}
                  selectedCall={selectedCall}
                  selectedPut={selectedPut}
                  showBottomRule={(idx + 1) % 5 === 0}
                  onClickCall={() => onClickCall(row)}
                  onClickPut={() => onClickPut(row)}
                  onClickStrike={() => onClickStrike(row)}
                />
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

function Header({
  symbol,
  expiry,
  spot,
  atm,
  iv,
}: {
  symbol: string;
  expiry: string | null;
  spot: number | null;
  atm: number | null;
  iv: number | null;
}) {
  return (
    <div className="border-b border-hairline bg-tier-1 shrink-0">
      <div className="flex items-baseline gap-2 px-3 pt-1.5 tabular-nums">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Option chain
        </span>
        <span className="text-tiny text-fg-primary">{symbol}</span>
        <span className="text-tiny text-fg-tertiary-2">
          0DTE · exp {expiry ?? "today"}
        </span>
        <span
          className="ml-auto text-fg-tertiary-2"
          style={{ fontSize: 10 }}
        >
          indicative pricing
        </span>
      </div>
      <div className="flex items-baseline gap-3 px-3 pb-1 tabular-nums">
        <SubItem label="spot" value={spot != null ? `$${spot.toFixed(2)}` : "—"} />
        <SubItem label="ATM" value={atm != null ? `$${atm}` : "—"} />
        <SubItem
          label="IV"
          value={iv != null ? `${(iv * 100).toFixed(1)}%` : "—"}
        />
      </div>
    </div>
  );
}

function SubItem({ label, value }: { label: string; value: string }) {
  return (
    <span className="text-tiny tabular-nums">
      <span className="text-fg-tertiary-2 uppercase mr-1" style={{ fontSize: 9 }}>
        {label}
      </span>
      <span className="text-fg-secondary">{value}</span>
    </span>
  );
}

function ColumnHeader() {
  return (
    <div className="flex justify-center border-b border-hairline-strong bg-tier-1 shrink-0">
      <div
        className="grid items-center text-tiny uppercase tracking-label-up text-fg-tertiary-2"
        style={{
          gridTemplateColumns: GRID,
          fontSize: 9,
          letterSpacing: "0.08em",
          height: ROW_HEIGHT,
        }}
      >
        <span className="text-right pr-3">Call</span>
        <span className="text-center">Strike</span>
        <span className="text-left pl-3">Put</span>
      </div>
    </div>
  );
}

function Row({
  row,
  disabled,
  selectedCall,
  selectedPut,
  showBottomRule,
  onClickCall,
  onClickPut,
  onClickStrike,
}: {
  row: ChainStrikeRow;
  disabled: boolean;
  selectedCall: boolean;
  selectedPut: boolean;
  /** Hairline divider below this row — only every 5th, for ladder grouping. */
  showBottomRule: boolean;
  onClickCall: () => void;
  onClickPut: () => void;
  onClickStrike: () => void;
}) {
  // ATM row: 4px amber left rule + bg-tier-2 across, amber values
  // (visible even in disabled state).
  // Selected row (any cell): persistent bg-tier-3 + 2px amber outline.
  // Default row: 4px transparent left rule + bg-tier-3 fill on hover.
  const anySelected = selectedCall || selectedPut;
  const baseClass = anySelected
    ? "bg-tier-3 border-l-[4px] border-amber relative ring-1 ring-amber"
    : row.is_atm
      ? "bg-tier-2 border-l-[4px] border-amber"
      : "border-l-[4px] border-transparent hover:bg-tier-3";
  const bottomBorder = showBottomRule ? "border-b border-hairline" : "";
  return (
    <div
      data-strike={row.strike}
      className={`grid items-center tabular-nums ${baseClass} ${bottomBorder}`}
      style={{
        gridTemplateColumns: GRID,
        height: ROW_HEIGHT,
      }}
    >
      <Cell
        align="right"
        price={row.call_price}
        source={row.call_source}
        delta={row.call_delta}
        theta={row.call_theta}
        disabled={disabled || row.call_price <= 0}
        side="call"
        strike={row.strike}
        isAtm={row.is_atm}
        selected={selectedCall}
        onClick={onClickCall}
      />
      <button
        type="button"
        onClick={onClickStrike}
        disabled={disabled}
        className={[
          "text-center px-1 h-full tabular-nums",
          // Subtle bg tint on the strike column to anchor the ladder
          // center. ATM/selected rows already have their own fills;
          // the column tint only shows on the default rows.
          anySelected || row.is_atm ? "" : "bg-tier-1",
          row.is_atm ? "text-amber font-medium" : "text-fg-primary",
          disabled
            ? row.is_atm
              ? "text-amber cursor-not-allowed"
              : "text-fg-disabled cursor-not-allowed"
            : "hover:text-amber",
        ].join(" ")}
        style={{ fontSize: 13, fontWeight: row.is_atm ? 500 : 400 }}
        title={
          disabled
            ? "Market closed or no 0DTE today"
            : row.is_atm
              ? `Select straddle at ${row.strike}`
              : `Select call at ${row.strike}`
        }
      >
        {row.strike}
      </button>
      <Cell
        align="left"
        price={row.put_price}
        source={row.put_source}
        delta={row.put_delta}
        theta={row.put_theta}
        disabled={disabled || row.put_price <= 0}
        side="put"
        strike={row.strike}
        isAtm={row.is_atm}
        selected={selectedPut}
        onClick={onClickPut}
      />
    </div>
  );
}

function Cell({
  align,
  price,
  source,
  delta,
  theta,
  disabled,
  side,
  strike,
  isAtm,
  selected,
  onClick,
}: {
  align: "left" | "right";
  price: number;
  source: "quote" | "bs";
  delta: number;
  theta: number;
  disabled: boolean;
  side: "call" | "put";
  strike: number;
  isAtm: boolean;
  selected: boolean;
  onClick: () => void;
}) {
  const dim = source === "bs";
  // ATM row keeps its amber values even in disabled state (the row
  // identity should remain visible while market is closed).
  const baseColor = disabled
    ? isAtm
      ? "text-amber cursor-not-allowed"
      : "text-fg-disabled cursor-not-allowed"
    : selected
      ? "text-amber"
      : isAtm
        ? "text-amber"
        : dim
          ? "text-fg-tertiary-2"
          : "text-fg-primary";
  // Price hugs the strike (call → right edge, put → left edge); the
  // dimmer Δ/Θ greeks sit outboard so they read as secondary info
  // without displacing the price's anchor on the strike. Greeks are
  // display-only — same per-share values the backend already returns.
  const priceEl = (
    <span className="whitespace-nowrap">
      {price.toFixed(2)}
      {source === "bs" && (
        <span
          className="text-fg-tertiary ml-0.5"
          style={{ fontSize: 8 }}
          aria-hidden
        >
          ·m
        </span>
      )}
    </span>
  );
  const greeksEl = (
    <span
      className={`whitespace-nowrap ${disabled ? "text-fg-disabled" : "text-fg-tertiary-2"}`}
      style={{ fontSize: 9, fontWeight: 400 }}
    >
      Δ{delta.toFixed(2)} Θ{theta.toFixed(2)}
    </span>
  );
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={[
        "h-full px-2 tabular-nums font-medium flex items-baseline gap-1.5",
        align === "right" ? "justify-end" : "justify-start",
        baseColor,
        disabled ? "" : "hover:text-amber",
      ].join(" ")}
      style={{ fontSize: 12, fontWeight: 500 }}
      title={
        disabled
          ? "Market closed or no 0DTE today"
          : `Select ${side} at ${strike} · ${
              source === "bs" ? "BS-model price (no live quote)" : "indicative quote"
            } · Δ ${delta.toFixed(2)} · Θ ${theta.toFixed(2)}/day`
      }
    >
      {align === "right" ? (
        <>
          {greeksEl}
          {priceEl}
        </>
      ) : (
        <>
          {priceEl}
          {greeksEl}
        </>
      )}
    </button>
  );
}

function EmptyMessage({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone?: "warning" | "bearish";
}) {
  const cls =
    tone === "bearish"
      ? "text-bearish"
      : tone === "warning"
        ? "text-warning"
        : "text-fg-tertiary";
  return (
    <div className={`flex-1 flex items-center justify-center text-tiny ${cls} px-4 py-6 text-center`}>
      {children}
    </div>
  );
}
