import type { HTMLAttributes } from "react";

export type PriceSource = "quote" | "bs";

export interface ChainRowProps extends HTMLAttributes<HTMLDivElement> {
  /** Strike price. */
  strike: number;
  /** Call price. */
  call: number;
  /** Put price. */
  put: number;
  /** ATM row — amber left-border, lifted fill, amber strike. */
  isAtm?: boolean;
  /** Pricing source per side; "bs" (model) dims the cell + tags `·m`. */
  callSource?: PriceSource;
  putSource?: PriceSource;
  onCall?: () => void;
  onPut?: () => void;
  onStrike?: () => void;
  disabled?: boolean;
  className?: string;
}

// Compact widths so calls/puts hug the centered strike, reading like a
// desk ticket rather than a full-width table. Call/put equal → strike
// sits dead-center.
const CALL_W = 84;
const STRIKE_W = 64;
const PUT_W = 84;
const CHAIN_GRID = `${CALL_W}px ${STRIKE_W}px ${PUT_W}px`;
const ROW_HEIGHT = 18;

/**
 * ChainRow — one strike row of the option chain: CALL │ STRIKE │ PUT.
 * Three centered columns (84 / 64 / 84) so calls/puts hug the strike.
 * 18px tall, 11px tabular. ATM row = amber left-border + lifted fill +
 * amber strike. Clicking a price fires onCall/onPut; the strike fires
 * onStrike (a straddle when ATM). Prices sourced from "bs" (the
 * Black-Scholes model, no live quote) render dimmed + tagged `·m`.
 *
 * Flat-prop API per the design system. Matches the inline ChainRow
 * currently in chain/ChainTable.tsx (which passes a row object); a later
 * call-site step maps row → these props.
 */
export function ChainRow({
  strike,
  call,
  put,
  isAtm = false,
  callSource = "quote",
  putSource = "quote",
  onCall,
  onPut,
  onStrike,
  disabled = false,
  className = "",
  ...rest
}: ChainRowProps) {
  const rowCls = isAtm
    ? "bg-tier-1 border-l-2 border-amber"
    : "border-l-2 border-transparent hover:bg-tier-1";

  return (
    <div
      data-strike={strike}
      data-atm={isAtm || undefined}
      className={[
        "grid items-center text-tiny tabular-nums border-b border-hairline",
        rowCls,
        className,
      ].join(" ")}
      style={{ gridTemplateColumns: CHAIN_GRID, height: ROW_HEIGHT }}
      {...rest}
    >
      <PriceCell
        price={call}
        source={callSource}
        align="right"
        disabled={disabled || call <= 0}
        onClick={onCall}
      />
      <button
        type="button"
        onClick={onStrike}
        disabled={disabled}
        className={[
          "text-center px-1 h-full border-l border-r border-hairline",
          isAtm ? "text-amber font-medium" : "text-fg-primary",
          "hover:bg-tier-2 disabled:opacity-50 disabled:cursor-not-allowed",
        ].join(" ")}
      >
        {strike}
      </button>
      <PriceCell
        price={put}
        source={putSource}
        align="left"
        disabled={disabled || put <= 0}
        onClick={onPut}
      />
    </div>
  );
}

function PriceCell({
  price,
  source,
  align,
  disabled,
  onClick,
}: {
  price: number;
  source: PriceSource;
  align: "left" | "right";
  disabled: boolean;
  onClick?: () => void;
}) {
  const dim = source === "bs";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={[
        "h-full px-2 tabular-nums hover:bg-tier-2",
        "disabled:opacity-30 disabled:cursor-not-allowed",
        align === "right" ? "text-right" : "text-left",
        dim ? "text-fg-secondary" : "text-fg-primary",
      ].join(" ")}
    >
      {price.toFixed(2)}
      {source === "bs" && (
        <span className="text-fg-tertiary ml-0.5" style={{ fontSize: 8 }}>
          ·m
        </span>
      )}
    </button>
  );
}
