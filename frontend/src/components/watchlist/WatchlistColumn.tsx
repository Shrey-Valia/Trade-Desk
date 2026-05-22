import { formatDistanceToNow } from "date-fns";
import { useMarketStatus } from "@/hooks/useMarket";
import { useSelectedTicker } from "@/stores/selectedTicker";
import { useWatchlist } from "@/hooks/useWatchlist";
import type { WatchlistCategoryKey } from "@/types/watchlist";
import { WatchlistCategory, CATEGORY_LABELS } from "./WatchlistCategory";

const CATEGORY_ORDER: WatchlistCategoryKey[] = [
  "hot_now",
  "earnings",
  "unusual_options",
  "sentiment_up",
  "sentiment_down",
];

// Per-category ghost-item counts roughly matching what populates in
// practice — silhouette resembles the final layout so no shift on load.
const SKELETON_ITEM_COUNTS: Record<WatchlistCategoryKey, number> = {
  hot_now: 4,
  earnings: 2,
  unusual_options: 3,
  sentiment_up: 0,
  sentiment_down: 0,
};

/**
 * Left rail — Bloomberg archetype (commit 6).
 *
 * 240px hairline rail, no emoji category icons, no wall clock (the top
 * bar carries one — Pass 3 review resolved the duplication). Header
 * shows just "WATCHLIST" + freshness indicator ("Updated 5s ago").
 */
export function WatchlistColumn() {
  const { data, isLoading, isError, error } = useWatchlist();
  const { data: marketStatus } = useMarketStatus();
  const symbol = useSelectedTicker((s) => s.symbol);
  const setSymbol = useSelectedTicker((s) => s.setSymbol);
  const freshness = data?.updated_at
    ? formatDistanceToNow(new Date(data.updated_at), { addSuffix: true })
    : null;
  const closedBanner =
    marketStatus && marketStatus.status === "closed" && data?.updated_at
      ? `Markets closed — last snapshot ${new Date(data.updated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
      : null;

  return (
    <aside
      className="border-r border-hairline bg-tier-0 overflow-y-auto"
      style={{ width: 240, minWidth: 240 }}
    >
      <div className="px-3 py-2 border-b border-hairline">
        <div className="flex items-baseline justify-between">
          <span className="text-xs2 uppercase tracking-label-up text-fg-secondary">
            Watchlist
          </span>
          {freshness && (
            <span className="text-tiny text-fg-tertiary">{freshness}</span>
          )}
        </div>
      </div>

      {closedBanner && (
        <div className="px-3 py-1.5 text-tiny text-fg-tertiary bg-tier-1 border-b border-hairline">
          {closedBanner}
        </div>
      )}

      {isLoading && <WatchlistColumnSkeleton />}
      {isError && (
        <div className="px-3 py-3 text-tiny text-bearish">
          {(error as Error)?.message ?? "Failed to load"}
        </div>
      )}

      {data && (
        <div className="py-1">
          {CATEGORY_ORDER.map((key) => (
            <WatchlistCategory
              key={key}
              category={key}
              items={data[key]}
              note={data.notes?.[key]}
              selectedSymbol={symbol ?? undefined}
              onSelect={setSymbol}
            />
          ))}
        </div>
      )}
    </aside>
  );
}

/**
 * Ghost copy of the 5-category rail — hairline header rows + 2-4 ghost
 * item rows per category. Static blocks per DESIGN.md skeleton rules.
 */
function WatchlistColumnSkeleton() {
  return (
    <div className="py-1">
      {CATEGORY_ORDER.map((key) => {
        const label = CATEGORY_LABELS[key];
        const itemCount = SKELETON_ITEM_COUNTS[key];
        return (
          <div key={key} className="mb-3">
            <div className="flex items-center gap-1 px-3 pt-1.5 pb-1">
              <span aria-hidden className="text-tiny text-fg-tertiary">
                ▸
              </span>
              <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
                {label}
              </span>
            </div>
            {itemCount === 0 ? (
              <div className="px-3 py-1.5">
                <div className="h-2 w-3/4 bg-tier-2" />
              </div>
            ) : (
              Array.from({ length: itemCount }).map((_, i) => (
                <div key={i} className="px-3 py-1.5 border-l-2 border-l-transparent">
                  <div className="flex items-baseline justify-between gap-1.5">
                    <div className="h-3 w-12 bg-tier-2" />
                    <div className="h-2 w-10 bg-tier-2" />
                  </div>
                  <div className="h-2 w-full bg-tier-2 mt-1" />
                </div>
              ))
            )}
          </div>
        );
      })}
    </div>
  );
}
