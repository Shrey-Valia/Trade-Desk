import { useMarketIndices, useMarketStatus } from "@/hooks/useMarket";
import { formatPercent } from "@/lib/formatters";
import type { IndexQuote, MarketStatus } from "@/types/market";

/**
 * Persistent top bar — Bloomberg archetype (commit 4).
 *
 * 28px hairline strip, no wordmark. Status dot + label inline on the left,
 * three index cells inline on the right, all separated by negative space
 * (no `|` separators). Indices format: `SPY 537.71 +0.42%` — symbol at
 * 11px FG SECONDARY, price at 13px tabular FG PRIMARY, signed pct at
 * 11px tabular in bullish/bearish.
 */
export function DashboardHeader() {
  const { data: status } = useMarketStatus();
  const { data: indices } = useMarketIndices();

  const isLoading = !status && !indices;
  if (isLoading) {
    return <DashboardHeaderSkeleton />;
  }

  return (
    <header
      className="flex items-center justify-between border-b border-hairline bg-tier-0 px-4"
      style={{ height: 28 }}
    >
      <StatusInline status={status} />
      <div className="flex items-center gap-3">
        <IndexCell q={indices?.spy ?? null} />
        <IndexCell q={indices?.qqq ?? null} />
        <IndexCell q={indices?.vix ?? null} />
      </div>
    </header>
  );
}

/**
 * Single line: colored dot + uppercase status label. Dot color carries
 * the semantic; the word reinforces it. No pill background — chrome-free
 * per DESIGN.md.
 */
function StatusInline({ status }: { status: MarketStatus | undefined }) {
  if (!status) {
    return <span className="text-tiny text-fg-tertiary">—</span>;
  }
  // open → bullish, closed → fg-secondary, pre/after → cyan.
  // Cyan = "structural but neutral" matches the pre/post-market read
  // (data exists, but not the same regime as RTH). Amber is reserved
  // for focus / today / warning / selection per DESIGN.md.
  const dotColorClass =
    status.status === "open"
      ? "text-bullish"
      : status.status === "closed"
      ? "text-fg-secondary"
      : "text-cyan";

  return (
    <span
      className="flex items-center gap-1.5"
      aria-live="polite"
    >
      <span aria-hidden className={`text-tiny ${dotColorClass}`}>
        ●
      </span>
      <span className="text-tiny uppercase tracking-label-up text-fg-primary">
        {status.label}
      </span>
    </span>
  );
}

function IndexCell({ q }: { q: IndexQuote | null }) {
  if (!q) {
    return <span className="text-tiny text-fg-tertiary tabular-nums">—</span>;
  }
  const positive = q.change_pct >= 0;
  const changeColorClass = positive ? "text-bullish" : "text-bearish";
  const ariaDirection = positive ? "up" : "down";
  return (
    <span
      className="flex items-baseline gap-1 tabular-nums"
      aria-label={`${q.symbol} ${q.price.toFixed(2)}, ${ariaDirection} ${Math.abs(q.change_pct).toFixed(2)} percent`}
    >
      <span className="text-tiny text-fg-secondary">{q.symbol}</span>
      <span className="text-xs2 text-fg-primary">{q.price.toFixed(2)}</span>
      <span className={`text-tiny ${changeColorClass}`}>{formatPercent(q.change_pct)}</span>
    </span>
  );
}

/**
 * Skeleton mirrors final layout — hairline blocks at the same widths
 * as the loaded content. Static blocks (no shimmer) per DESIGN.md.
 */
function DashboardHeaderSkeleton() {
  return (
    <header
      className="flex items-center justify-between border-b border-hairline bg-tier-0 px-4"
      style={{ height: 28 }}
    >
      <div className="flex items-center gap-1.5">
        <div className="h-2 w-2 bg-tier-2" />
        <div className="h-2 w-14 bg-tier-2" />
      </div>
      <div className="flex items-center gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-2 w-20 bg-tier-2" />
        ))}
      </div>
    </header>
  );
}
