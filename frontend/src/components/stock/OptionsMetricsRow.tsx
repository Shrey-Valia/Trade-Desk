import { useTickerMetrics } from "@/hooks/useTickerMetrics";
import { formatPrice } from "@/lib/formatters";
import { TOOLTIPS } from "@/lib/tooltips";
import { MetricCell } from "@/components/ui/MetricCell";
import { SkeletonCard } from "@/components/ui/SkeletonCard";

interface Props {
  symbol: string;
}

/**
 * Row C — 5 inline MetricCells separated by 1px vertical hairlines, no card
 * chrome. Commit 10 of the Bloomberg revamp.
 */
export function OptionsMetricsRow({ symbol }: Props) {
  const { data, isLoading, isError, error } = useTickerMetrics(symbol);

  if (isLoading) {
    return (
      <div className="border-b border-hairline grid grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className={i < 4 ? "border-r border-hairline" : ""}>
            <SkeletonCard />
          </div>
        ))}
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="px-4 py-2 border-b border-hairline text-tiny text-bearish">
        {(error as Error)?.message ?? "Failed to load metrics"}
      </div>
    );
  }

  // If every metric is null, render one consolidated message instead of 5
  // dashed cells that read as 5 simultaneous failures.
  const allMissing = [data.iv_rank, data.vrp, data.skew_25d, data.pc_ratio, data.max_pain].every(
    (v) => v == null,
  );
  if (allMissing) {
    return (
      <div className="px-4 py-3 border-b border-hairline text-tiny text-fg-secondary text-center">
        Insufficient options data for metrics
      </div>
    );
  }

  const ivRankValue = data.iv_rank == null ? "—" : data.iv_rank.toFixed(0);
  const vrpValue = data.vrp == null ? "—" : signed1(data.vrp);
  const skewValue = data.skew_25d == null ? "—" : signed3(data.skew_25d);
  const pcValue = data.pc_ratio == null ? "—" : data.pc_ratio.toFixed(2);
  const maxPainValue = data.max_pain == null ? "—" : formatPrice(data.max_pain);

  // VRP color: positive = bullish green (rich premium, edge for sellers);
  // negative = bearish red. Phase 8a semantic preserved.
  const vrpColor: "primary" | "bullish" | "bearish" =
    data.vrp == null || data.vrp === 0
      ? "primary"
      : data.vrp > 0
      ? "bullish"
      : "bearish";

  return (
    <div className="border-b border-hairline grid grid-cols-5">
      <div className="border-r border-hairline">
        <MetricCell
          label="IV Rank"
          value={ivRankValue}
          subContext={data.iv_rank_status ?? undefined}
          tooltip={TOOLTIPS.iv_rank}
        />
      </div>
      <div className="border-r border-hairline">
        <MetricCell label="VRP" value={vrpValue} valueColor={vrpColor} tooltip={TOOLTIPS.vrp} />
      </div>
      <div className="border-r border-hairline">
        <MetricCell label="25Δ Skew" value={skewValue} tooltip={TOOLTIPS.skew_25d} />
      </div>
      <div className="border-r border-hairline">
        <MetricCell label="P/C Ratio" value={pcValue} tooltip={TOOLTIPS.pc_ratio} />
      </div>
      <MetricCell label="Max Pain" value={maxPainValue} tooltip={TOOLTIPS.max_pain} />
    </div>
  );
}

function signed1(n: number): string {
  const s = n >= 0 ? "+" : "";
  return `${s}${n.toFixed(1)}`;
}

function signed3(n: number): string {
  const s = n >= 0 ? "+" : "";
  return `${s}${n.toFixed(3)}`;
}
