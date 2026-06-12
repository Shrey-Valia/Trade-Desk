import { PageHeader } from "@/components/layout/PageHeader";
import { WatchlistColumn } from "@/components/watchlist/WatchlistColumn";
import { WatchlistPreview } from "@/components/watchlist/WatchlistPreview";

/**
 * Watchlist destination — scan view.
 *
 * Left: the same WatchlistColumn the chart view uses (row click writes
 * the shared selectedTicker store). Right: WatchlistPreview renders
 * the clicked symbol — price, sparkline, ranges, options vitals — with
 * a jump-to-chart action, so a scan pass doesn't require bouncing to
 * the terminal and back per symbol.
 */
export function WatchlistPage() {
  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader title="Watchlist" subtitle="Scan view" />
      <main className="flex-1 min-h-0 flex border-t border-hairline">
        <WatchlistColumn />
        <WatchlistPreview />
      </main>
    </div>
  );
}
