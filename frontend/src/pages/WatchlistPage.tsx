import { PageHeader } from "@/components/layout/PageHeader";
import { WatchlistColumn } from "@/components/watchlist/WatchlistColumn";

/**
 * Watchlist destination — Step 1 of the navigation revamp.
 *
 * The watchlist component still lives in the right rail of the chart
 * view; this page is a focused-scan view that reuses the same
 * component without the chart competing for attention. Restyle is
 * a later step in the revamp.
 */
export function WatchlistPage() {
  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader title="Watchlist" subtitle="Scan view" />
      <main className="flex-1 min-h-0 flex border-t border-hairline">
        <WatchlistColumn />
        <div className="flex-1 min-w-0 flex items-center justify-center text-tiny text-fg-tertiary">
          <span className="max-w-md text-center leading-relaxed px-4">
            Click any symbol to load it on the chart view.
            <br />
            <span className="text-fg-tertiary/70">
              (Restyled full-screen watchlist is a later step in the revamp.)
            </span>
          </span>
        </div>
      </main>
    </div>
  );
}
