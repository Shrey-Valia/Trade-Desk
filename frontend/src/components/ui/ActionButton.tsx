import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ActionIntent = "buy" | "sell";

export interface ActionButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className"> {
  /** "buy" (green action fill) or "sell" (red action fill). Default "buy". */
  intent?: ActionIntent;
  /** Main label, e.g. "BUY +1". */
  label: ReactNode;
  /** Sub-line, e.g. "long call · $8.00 debit". */
  sub?: ReactNode;
  className?: string;
}

/**
 * ActionButton — the large BUY / SELL ticket button. 56px tall, solid
 * ACTION-affordance fill (`action-buy` / `action-sell`, deliberately NOT
 * the bullish/bearish P&L colors), white text, 4px radius, two-line
 * label with hover + press states. Disabled sinks to tier-1.
 *
 * Matches the inline ActionButton currently in TradeTicket (and the
 * CLOSE button chrome in BottomStrip).
 *
 * Note: label uses font-semibold (600) to match the live inline buttons.
 * The DS doctrine nominally caps weight at 500 — flagged for a later
 * design reconciliation, kept at 600 here so the call-site swap is
 * pixel-identical.
 */
export function ActionButton({
  intent = "buy",
  label,
  sub,
  disabled = false,
  type = "button",
  className = "",
  ...rest
}: ActionButtonProps) {
  const fill = disabled
    ? "bg-tier-1"
    : intent === "buy"
      ? "bg-action-buy hover:bg-action-buy-hover active:bg-action-buy-active"
      : "bg-action-sell hover:bg-action-sell-hover active:bg-action-sell-active";

  return (
    <button
      type={type}
      disabled={disabled}
      data-intent={intent}
      className={[
        "h-14 w-full rounded-btn px-2 leading-tight",
        "flex flex-col items-center justify-center",
        "transition-colors duration-100",
        fill,
        disabled ? "text-fg-disabled cursor-not-allowed" : "text-white",
        className,
      ].join(" ")}
      {...rest}
    >
      <span className="font-semibold tracking-wide" style={{ fontSize: 14 }}>
        {label}
      </span>
      {sub && (
        <span
          className="tabular-nums"
          style={{ fontSize: 12, marginTop: 2, opacity: disabled ? 1 : 0.78 }}
        >
          {sub}
        </span>
      )}
    </button>
  );
}
