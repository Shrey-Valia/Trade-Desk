import type { SignalReason } from "@/types/signal";

/**
 * Two-column breakdown — agreeing on the left (bullish-green left rule),
 * conflicting on the right (bearish-red left rule). Conflicting column
 * is NEVER empty by omission; when the rule engine genuinely found no
 * conflicts we render an explicit "No conflicting signals" row so the
 * reader knows the absence is real, not hidden.
 */
export function SignalBreakdown({
  agreeing,
  conflicting,
}: {
  agreeing: SignalReason[];
  conflicting: SignalReason[];
}) {
  return (
    <section className="grid grid-cols-2 border-b border-hairline">
      <Column
        title="Signals agreeing"
        items={agreeing}
        emptyMessage="No agreeing signals fired."
        ruleColor="border-bullish"
        rightBorder
      />
      <Column
        title="Signals conflicting"
        items={conflicting}
        emptyMessage="No conflicting signals — clean setup."
        ruleColor="border-bearish"
      />
    </section>
  );
}

function Column({
  title,
  items,
  emptyMessage,
  ruleColor,
  rightBorder,
}: {
  title: string;
  items: SignalReason[];
  emptyMessage: string;
  ruleColor: string;
  rightBorder?: boolean;
}) {
  return (
    <div className={rightBorder ? "border-r border-hairline" : ""}>
      <div className="px-3 py-1.5 border-b border-hairline bg-tier-0">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          {title}
        </span>
        <span className="ml-2 text-tiny text-fg-tertiary tabular-nums">
          ({items.length})
        </span>
      </div>
      <ul className="divide-y divide-hairline">
        {items.length === 0 ? (
          <li className="px-3 py-2 text-tiny text-fg-tertiary">{emptyMessage}</li>
        ) : (
          items.map((r) => (
            <li
              key={`${title}:${r.label}`}
              className={`px-3 py-1.5 border-l-2 ${ruleColor}`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs2 text-fg-primary">{r.label}</span>
                <span className="text-tiny text-fg-tertiary tabular-nums">
                  w={r.weight}
                </span>
              </div>
              <div className="text-tiny text-fg-secondary mt-0.5">{r.detail}</div>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
