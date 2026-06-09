import type { ButtonHTMLAttributes } from "react";

export interface TierPillProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className"> {
  /** Combine tier label, e.g. "50K". Default "50K". */
  tier?: string;
  /** Balance is below the trailing MLL — turns the pill bearish. */
  breached?: boolean;
  className?: string;
}

/**
 * TierPill — the combine-tier indicator / switcher; the leftmost element
 * in the terminal header. Renders "{tier} Combine ▾", 40px tall, tier-2
 * fill with a tier-3 border (bearish border + text when `breached`),
 * 4px radius, uppercase label.
 *
 * Static trigger — render your own dropdown menu on click. Matches the
 * inline TierPill currently in TradeDeskHeader.
 */
export function TierPill({
  tier = "50K",
  breached = false,
  type = "button",
  className = "",
  ...rest
}: TierPillProps) {
  return (
    <button
      type={type}
      className={[
        "inline-flex items-center gap-2 h-10 px-3 rounded-btn",
        "uppercase tracking-label-up tabular-nums font-medium",
        "transition-colors duration-100",
        breached
          ? "bg-tier-2 border border-bearish text-bearish"
          : "bg-tier-2 border border-tier-3 text-fg-primary hover:bg-tier-3",
        className,
      ].join(" ")}
      style={{ fontSize: 12 }}
      aria-haspopup="listbox"
      {...rest}
    >
      <span>{tier} Combine</span>
      <span className="text-fg-tertiary-2" style={{ fontSize: 10 }}>
        ▾
      </span>
    </button>
  );
}
