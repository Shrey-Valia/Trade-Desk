interface Props {
  currentDte: number;
  scrubberDte: number;
  onChange: (dte: number) => void;
  onReset: () => void;
  disabled?: boolean;
}

/**
 * Theta-decay scrubber — the demo move.
 *
 * Visual axis: left = NOW (T+0d), right = EXPIRY (T+current_dte). The
 * thumb starts on the left and dragging RIGHT advances time toward
 * expiration — matches the convention of time flowing left-to-right.
 *
 * Internally the position model tracks `scrubber_dte` (days REMAINING
 * to expiry); the slider input tracks `elapsed` (days advanced from
 * now). We swap between them at the input boundary so the rest of the
 * stack keeps the natural "days remaining" framing.
 *
 * As the user drags right:
 *   1. The today payoff curve converges to the expiration curve
 *      (visually IS theta decay)
 *   2. The breakeven line on the price chart widens toward the
 *      expiration BEs
 */
export function ThetaScrubber({
  currentDte,
  scrubberDte,
  onChange,
  onReset,
  disabled,
}: Props) {
  const elapsed = Math.max(0, currentDte - scrubberDte);
  const isAtNow = scrubberDte === currentDte;
  return (
    <div className="flex items-center gap-3 px-3 py-1.5 border-t border-hairline bg-tier-0 shrink-0">
      <span className="text-tiny uppercase tracking-label-up text-fg-secondary shrink-0">
        Theta scrubber
      </span>
      <div className="flex items-center gap-2 flex-1 min-w-0">
        <span className="text-tiny text-fg-tertiary uppercase tracking-label-up w-12 text-right">
          Now
        </span>
        <input
          type="range"
          min={0}
          max={Math.max(1, currentDte)}
          step={1}
          value={elapsed}
          onChange={(e) => onChange(currentDte - Number(e.target.value))}
          disabled={disabled}
          className="theta-scrubber flex-1 min-w-0"
          aria-label="Days advanced toward expiry"
          aria-valuemin={0}
          aria-valuemax={currentDte}
          aria-valuenow={elapsed}
        />
        <span className="text-tiny text-fg-tertiary uppercase tracking-label-up w-16">
          Expiry
        </span>
      </div>
      <div className="flex items-center gap-3 shrink-0 tabular-nums">
        <span className="text-tiny text-fg-secondary">
          T+{elapsed}d <span className="text-fg-tertiary">·</span> DTE {scrubberDte}
        </span>
        <button
          type="button"
          onClick={onReset}
          disabled={disabled || isAtNow}
          className="text-tiny uppercase tracking-label-up text-fg-tertiary hover:text-amber disabled:opacity-40"
        >
          reset
        </button>
      </div>
    </div>
  );
}
