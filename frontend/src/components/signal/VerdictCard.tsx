import type { SignalVerdict, VerdictType } from "@/types/signal";

/**
 * Top card: headline verdict + verdict-type chip + conviction bar.
 *
 * verdict-type chip color uses the existing semantic palette:
 *   sell_premium      → bullish green (collecting credit reads "favorable")
 *   buy_premium       → cyan          (structural / neutral-but-important)
 *   directional_long  → amber         (selection/focus on a direction)
 *   directional_short → amber         (same — direction owns "focus" semantic)
 *   avoid             → bearish red
 *   neutral           → fg-secondary
 */
const TYPE_LABEL: Record<VerdictType, string> = {
  sell_premium: "Sell premium",
  buy_premium: "Buy premium",
  directional_long: "Directional long",
  directional_short: "Directional short",
  avoid: "Avoid",
  neutral: "Neutral",
};

const TYPE_COLOR: Record<VerdictType, string> = {
  sell_premium: "text-bullish border-bullish",
  buy_premium: "text-cyan border-cyan",
  directional_long: "text-bullish border-bullish",
  directional_short: "text-bearish border-bearish",
  avoid: "text-bearish border-bearish",
  neutral: "text-fg-secondary border-hairline",
};

export function VerdictCard({ verdict }: { verdict: SignalVerdict }) {
  const chipClass = TYPE_COLOR[verdict.verdict_type];
  return (
    <section className="px-4 py-3 border-b border-hairline bg-tier-0 flex items-center gap-6">
      <div className="flex flex-col gap-1 min-w-0">
        <span className="text-tiny uppercase tracking-label-up text-fg-tertiary">
          {verdict.symbol} · Signal
        </span>
        <h2 className="text-display font-medium text-fg-primary truncate">
          {verdict.verdict}
        </h2>
      </div>
      <span
        className={`shrink-0 border-l-2 pl-2 text-xs2 uppercase tracking-label-up ${chipClass}`}
      >
        {TYPE_LABEL[verdict.verdict_type]}
      </span>
      <ConvictionBar value={verdict.conviction} label={verdict.conviction_label} />
    </section>
  );
}

function ConvictionBar({
  value,
  label,
}: {
  value: number;
  label: SignalVerdict["conviction_label"];
}) {
  const labelColor =
    label === "high"
      ? "text-bullish"
      : label === "moderate"
      ? "text-fg-primary"
      : "text-bearish";
  const fillColor =
    label === "high"
      ? "bg-bullish"
      : label === "moderate"
      ? "bg-fg-secondary"
      : "bg-bearish";
  return (
    <div className="flex flex-col gap-1 ml-auto items-end shrink-0">
      <div className="flex items-baseline gap-2">
        <span className="text-tiny uppercase tracking-label-up text-fg-tertiary">
          Conviction
        </span>
        <span className={`text-medium font-medium tabular-nums ${labelColor}`}>
          {value}
        </span>
        <span className={`text-tiny uppercase tracking-label-up ${labelColor}`}>
          {label}
        </span>
      </div>
      <div
        className="h-1 bg-tier-2 border border-hairline"
        style={{ width: 180 }}
        aria-label={`Conviction ${value} of 100`}
      >
        <div className={`h-full ${fillColor}`} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}
