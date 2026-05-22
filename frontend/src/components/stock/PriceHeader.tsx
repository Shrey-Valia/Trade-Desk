import { Skeleton } from "@/components/ui/Skeleton";
import {
  formatChangeDollar,
  formatPercent,
  formatPrice,
  formatRange,
  formatVolumeRatio,
} from "@/lib/formatters";
import { TOOLTIPS } from "@/lib/tooltips";
import type { TickerDetail } from "@/types/ticker";

interface Props {
  detail: TickerDetail;
}

export function PriceHeaderSkeleton() {
  return (
    <div className="px-4 border-b border-hairline bg-tier-0" style={{ height: 40 }}>
      <div className="flex items-center gap-4 h-full">
        <Skeleton width={40} height={11} />
        <Skeleton width={80} height={15} />
        <Skeleton width={120} height={11} />
        <Skeleton width={140} height={9} />
        <Skeleton width={140} height={9} />
        <Skeleton width={90} height={9} />
        <Skeleton width={50} height={11} />
      </div>
    </div>
  );
}

/**
 * Row A — single 40px hairline strip. Bloomberg archetype (commit 7).
 *
 * Ticker · price · change · ranges · vol ratio · ER badge, all inline,
 * no wrap, separated by negative space (no `·` bullets). ER badge uses
 * an amber left-rule instead of a filled background pill.
 */
export function PriceHeader({ detail }: Props) {
  const positive = detail.change_pct >= 0;
  const changeColorClass = positive ? "text-bullish" : "text-bearish";
  const showER = detail.days_to_earnings != null && detail.days_to_earnings <= 14;

  return (
    <div
      className="px-4 border-b border-hairline bg-tier-0 flex items-baseline gap-4"
      style={{ height: 40 }}
    >
      {/* Ticker — 15px medium per DESIGN.md ramp */}
      <span className="text-medium font-medium text-fg-primary">{detail.symbol}</span>

      {/* Price — 19px display, tabular */}
      <span className="text-display font-medium tabular-nums text-fg-primary">
        {formatPrice(detail.price)}
      </span>

      {/* Change ($ and %) — 13px body, tabular, colored. Both per Pass 1 resolution. */}
      <span className={`text-body tabular-nums ${changeColorClass}`}>
        {formatChangeDollar(detail.change_dollar)} ({formatPercent(detail.change_pct)})
      </span>

      {/* Day range */}
      <span className="flex items-baseline gap-1 text-xs2 tabular-nums" title={TOOLTIPS.day_range}>
        <span className="text-tiny uppercase tracking-label-up text-fg-tertiary">Day</span>
        <span className="text-fg-secondary">{formatRange(detail.day_low, detail.day_high)}</span>
      </span>

      {/* 52-week range */}
      <span className="flex items-baseline gap-1 text-xs2 tabular-nums" title={TOOLTIPS.fiftytwo_week_range}>
        <span className="text-tiny uppercase tracking-label-up text-fg-tertiary">52W</span>
        <span className="text-fg-secondary">{formatRange(detail.fifty_two_week_low, detail.fifty_two_week_high)}</span>
      </span>

      {/* Volume ratio — today / 20-day average inline */}
      <span
        className="flex items-baseline gap-1 text-xs2 tabular-nums"
        title={`${TOOLTIPS.volume}\n\nAverage volume: ${TOOLTIPS.avg_volume}`}
      >
        <span className="text-tiny uppercase tracking-label-up text-fg-tertiary">Vol</span>
        <span className="text-fg-secondary">
          {formatVolumeRatio(detail.volume, detail.avg_volume_20d)}
        </span>
      </span>

      {showER && (
        <span
          className="border-l-2 border-amber pl-2 text-tiny uppercase tracking-label-up text-amber"
          title={TOOLTIPS.er_badge}
        >
          ER {detail.days_to_earnings}d
        </span>
      )}
    </div>
  );
}
