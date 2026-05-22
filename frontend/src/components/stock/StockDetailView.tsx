import { useTickerDetail } from "@/hooks/useTickerDetail";
import {
  useSelectedTicker,
  useSelectedTickerHasHydrated,
} from "@/stores/selectedTicker";
import { BlackScholesPanel } from "@/components/modeling/BlackScholesPanel";
import { MonteCarloPanel } from "@/components/modeling/MonteCarloPanel";
import { AnnotatedChart } from "./AnnotatedChart";
import { ModelSignalsRow } from "./ModelSignalsRow";
import { OptionsMetricsRow } from "./OptionsMetricsRow";
import { PriceHeader, PriceHeaderSkeleton } from "./PriceHeader";

/**
 * Detail layout — flex-column that fills the viewport without scrolling.
 *
 * Proportions (per user spec): chart dominates (~45% viewport), rows
 * compact (~12% combined), MC+BS share the bottom (~35%). PriceHeader
 * auto-sizes (40px hairline strip). Chart + MC+BS use flex-grow so the
 * column expands to fill — no empty whitespace below BS.
 *
 * `flex-[3]` vs `flex-[2]` is roughly a 60/40 split of remaining flex
 * space after PriceHeader + rows take their natural height, which lands
 * near the 45/35 viewport ratio at typical dashboard heights.
 */
export function StockDetailView() {
  const hasHydrated = useSelectedTickerHasHydrated();
  const symbol = useSelectedTicker((s) => s.symbol);
  const { data, isLoading, isError, error } = useTickerDetail(
    hasHydrated ? symbol : null,
  );

  if (!hasHydrated) {
    return <div className="flex-1" />;
  }

  if (!symbol) {
    return (
      <div className="flex-1 flex items-center justify-center text-fg-tertiary text-xs2">
        Select a name from the watchlist
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex-1 p-4 text-bearish text-xs2">
        {(error as Error)?.message ?? `Failed to load ${symbol}`}
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {isLoading || !data ? <PriceHeaderSkeleton /> : <PriceHeader detail={data} />}
      <div className="flex-[3] min-h-0 flex flex-col">
        <AnnotatedChart symbol={symbol} />
      </div>
      <div className="shrink-0">
        <OptionsMetricsRow symbol={symbol} />
        <ModelSignalsRow symbol={symbol} />
      </div>
      <div className="flex-[2] min-h-0 grid grid-cols-2 border-t border-hairline">
        <div className="border-r border-hairline min-h-0 flex flex-col">
          <MonteCarloPanel symbol={symbol} />
        </div>
        <div className="min-h-0 flex flex-col">
          <BlackScholesPanel symbol={symbol} />
        </div>
      </div>
    </div>
  );
}
