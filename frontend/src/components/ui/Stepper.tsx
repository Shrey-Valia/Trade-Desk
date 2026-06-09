import type { HTMLAttributes, ReactNode } from "react";

export interface StepperProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "onChange"> {
  /** Current value. */
  value: number;
  /** Called with the next value. */
  onChange: (next: number) => void;
  /** Min (default 1). */
  min?: number;
  /** Max (default 999). */
  max?: number;
  className?: string;
}

/**
 * Stepper — the −/value/+ quantity control from the trade ticket.
 * Square 32px ± buttons (tier-2 fill, tier-3 border, lift to tier-3 on
 * hover; disabled sinks to tier-1) flanking a 60px value box. Uses the
 * true minus glyph "−". Controlled via value/onChange. Matches the
 * inline stepper currently in TradeTicket.
 */
export function Stepper({
  value,
  onChange,
  min = 1,
  max = 999,
  className = "",
  ...rest
}: StepperProps) {
  return (
    <div
      className={["flex items-center", className].join(" ")}
      style={{ gap: 4 }}
      {...rest}
    >
      <StepBtn
        ariaLabel="Decrease quantity"
        disabled={value <= min}
        onClick={() => onChange(Math.max(min, value - 1))}
      >
        −
      </StepBtn>
      <div
        aria-live="polite"
        className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums flex items-center justify-center"
        style={{ width: 60, height: 32, fontSize: 16, fontWeight: 500 }}
      >
        {value}
      </div>
      <StepBtn
        ariaLabel="Increase quantity"
        disabled={value >= max}
        onClick={() => onChange(Math.min(max, value + 1))}
      >
        +
      </StepBtn>
    </div>
  );
}

function StepBtn({
  children,
  disabled,
  onClick,
  ariaLabel,
}: {
  children: ReactNode;
  disabled?: boolean;
  onClick: () => void;
  ariaLabel: string;
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
          ? "bg-tier-1 border border-tier-2 text-fg-disabled cursor-not-allowed"
          : "bg-tier-2 border border-tier-3 text-fg-primary hover:bg-tier-3",
      ].join(" ")}
      style={{ width: 32, height: 32, fontSize: 16, lineHeight: 1 }}
    >
      {children}
    </button>
  );
}
