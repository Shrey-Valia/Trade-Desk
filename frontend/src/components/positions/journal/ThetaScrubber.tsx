import { Coachmark } from "@/components/positions/Coachmark";

interface DaysProps {
  mode?: "days";
  currentDte: number;
  scrubberDte: number;
  onChange: (dte: number) => void;
  onReset: () => void;
  disabled?: boolean;
}

interface HoursProps {
  mode: "hours";
  /** Total session hours from entry to close (denominator of the bar). */
  totalHours: number;
  /** Live elapsed hours (server-reported when not scrubbing); used as
   *  the slider value when `scrubberHours` is null. */
  liveElapsedHours: number;
  /** Scrubbed elapsed hours, null = live mode (slider tracks live). */
  scrubberHours: number | null;
  onChangeHours: (hours: number | null) => void;
  disabled?: boolean;
}

type Props = DaysProps | HoursProps;

/**
 * Theta-decay scrubber — the demo move.
 *
 * Two modes:
 *   * "days"  (default) — integer days for multi-day positions. Left =
 *     now, right = expiry; thumb sweeps the visible-T-decay overlap.
 *   * "hours" — fractional hours for 0DTE positions. Left = entry, right
 *     = market close (4pm ET). Drives elapsed_hours into the analytics
 *     endpoint; backend re-prices BS at sub-day T.
 *
 * As the user drags right (either mode):
 *   1. The today payoff curve converges to the expiration curve.
 *   2. The breakeven lines on the price chart walk OUTWARD toward
 *      strike±cost (the expiration breakevens).
 */
export function ThetaScrubber(props: Props) {
  if (props.mode === "hours") return <HoursScrubber {...props} />;
  return <DaysScrubber {...(props as DaysProps)} />;
}

function DaysScrubber({
  currentDte,
  scrubberDte,
  onChange,
  onReset,
  disabled,
}: DaysProps) {
  const elapsed = Math.max(0, currentDte - scrubberDte);
  const isAtNow = scrubberDte === currentDte;
  return (
    <div className="relative flex items-center gap-3 px-3 py-1.5 border-t border-hairline bg-tier-0 shrink-0">
      <Coachmark
        hint="scrubber"
        label="Theta scrubber"
        body="Drag right to fast-forward time — watch the breakeven move on the chart as theta decays."
        side="top"
        enabled={!disabled && currentDte > 0}
      />
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

function HoursScrubber({
  totalHours,
  liveElapsedHours,
  scrubberHours,
  onChangeHours,
  disabled,
}: HoursProps) {
  const value = scrubberHours ?? liveElapsedHours;
  const isLive = scrubberHours === null;
  const decayPct = totalHours > 0 ? Math.min(1, value / totalHours) : 0;
  return (
    <div className="relative flex items-center gap-3 px-3 py-1.5 border-t border-hairline bg-tier-0 shrink-0">
      <span className="text-tiny uppercase tracking-label-up text-fg-secondary shrink-0">
        Theta scrubber · 0DTE
      </span>
      <div className="flex items-center gap-2 flex-1 min-w-0">
        <span className="text-tiny text-fg-tertiary uppercase tracking-label-up w-12 text-right">
          Entry
        </span>
        <input
          type="range"
          min={0}
          max={Math.max(0.01, totalHours)}
          step={0.05}
          value={value}
          onChange={(e) => onChangeHours(Number(e.target.value))}
          disabled={disabled}
          className="theta-scrubber flex-1 min-w-0"
          aria-label="Hours elapsed since entry"
          aria-valuemin={0}
          aria-valuemax={totalHours}
          aria-valuenow={value}
        />
        <span className="text-tiny text-fg-tertiary uppercase tracking-label-up w-16">
          Close
        </span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <DecayBar pct={decayPct} />
        <span className="text-tiny text-fg-secondary tabular-nums">
          +{value.toFixed(1)}h
        </span>
        <button
          type="button"
          onClick={() => onChangeHours(null)}
          disabled={disabled || isLive}
          className="text-tiny uppercase tracking-label-up text-fg-tertiary hover:text-amber disabled:opacity-40"
        >
          live
        </button>
      </div>
    </div>
  );
}

function DecayBar({ pct }: { pct: number }) {
  const fill = Math.max(0, Math.min(1, pct));
  return (
    <div className="flex items-center gap-1">
      <span
        className="text-tiny uppercase tracking-label-up text-fg-tertiary"
        style={{ fontSize: 9 }}
      >
        Decay
      </span>
      <div
        className="h-1.5 bg-tier-2 border border-hairline"
        style={{ width: 60 }}
        aria-label={`Session decay ${(fill * 100).toFixed(0)}%`}
      >
        <div
          className="h-full"
          style={{ width: `${fill * 100}%`, background: "#D4537E" }}
        />
      </div>
      <span
        className="text-tiny text-fg-tertiary tabular-nums"
        style={{ fontSize: 9 }}
      >
        {(fill * 100).toFixed(0)}%
      </span>
    </div>
  );
}
