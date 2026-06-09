import type { HTMLAttributes } from "react";

export interface PresetChipsProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "onSelect"> {
  /** Quantity presets. Default [1, 3, 5, 10, 15]. */
  presets?: number[];
  /** Currently-selected value (highlights the matching chip). */
  value: number;
  /** Called with the chosen preset. */
  onSelect: (n: number) => void;
  className?: string;
}

/**
 * PresetChips — round one-tap contract-quantity presets (1 / 3 / 5 / 10
 * / 15). Circular 32px chips. Selected = amber border + amber text on
 * the lifted (tier-3) fill; idle = tier-2 fill, secondary text, lifts on
 * hover. Use beside a <Stepper> in the trade ticket. Matches the inline
 * preset ladder currently in TradeTicket.
 */
export function PresetChips({
  presets = [1, 3, 5, 10, 15],
  value,
  onSelect,
  className = "",
  ...rest
}: PresetChipsProps) {
  return (
    <div className={["flex", className].join(" ")} style={{ gap: 4 }} {...rest}>
      {presets.map((n) => {
        const active = value === n;
        return (
          <button
            key={n}
            type="button"
            aria-pressed={active}
            onClick={() => onSelect(n)}
            className={[
              "tabular-nums font-medium select-none",
              "flex items-center justify-center",
              "transition-colors duration-100",
              active
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
  );
}
