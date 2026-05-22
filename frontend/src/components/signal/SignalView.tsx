import { useSignal } from "@/hooks/useSignal";
import {
  useSelectedTicker,
  useSelectedTickerHasHydrated,
} from "@/stores/selectedTicker";

import { MockFlowBanner } from "./MockFlowBanner";
import { SignalBreakdown } from "./SignalBreakdown";
import { ThesisPanel } from "./ThesisPanel";
import { VerdictCard } from "./VerdictCard";

/**
 * Signal-tab root. Reads selectedTicker the same way StockDetailView
 * does — so the watchlist row that's already selected drives this
 * surface, no separate selector.
 */
export function SignalView() {
  const hasHydrated = useSelectedTickerHasHydrated();
  const symbol = useSelectedTicker((s) => s.symbol);
  const { data, isLoading, isError, error } = useSignal(hasHydrated ? symbol : null);

  if (!hasHydrated) {
    return <div className="flex-1" />;
  }

  if (!symbol) {
    return (
      <div className="flex-1 flex items-center justify-center text-fg-tertiary text-xs2">
        Select a ticker to generate a signal.
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <div className="flex-1 flex items-center justify-center text-fg-tertiary text-xs2">
        Computing signal for {symbol}…
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex-1 p-4 text-bearish text-xs2">
        {(error as Error)?.message ?? `Failed to load signal for ${symbol}`}
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
      <VerdictCard verdict={data} />
      {data.mock_flow_used && (
        <div className="px-4 py-2 border-b border-hairline">
          <MockFlowBanner sweepCount={data.mock_sweeps.length} />
        </div>
      )}
      <SignalBreakdown
        agreeing={data.signals_agreeing}
        conflicting={data.signals_conflicting}
      />
      <ThesisPanel verdict={data} />
    </div>
  );
}
