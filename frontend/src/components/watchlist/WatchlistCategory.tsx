import type { WatchlistCategoryKey, WatchlistItem } from "@/types/watchlist";
import { WatchlistItem as ItemRow } from "./WatchlistItem";

interface Props {
  category: WatchlistCategoryKey;
  items: WatchlistItem[];
  note?: string;
  selectedSymbol?: string;
  onSelect?: (symbol: string) => void;
}

/**
 * Category labels — Bloomberg archetype (commit 6). Emoji category icons
 * killed; sentiment categories use ▲/▼ glyph suffix as the only
 * distinguishing mark.
 */
export const CATEGORY_LABELS: Record<WatchlistCategoryKey, string> = {
  hot_now: "HOT NOW",
  earnings: "EARNINGS ≤5d",
  unusual_options: "UNUSUAL OPTIONS",
  sentiment_up: "SENTIMENT ▲",
  sentiment_down: "SENTIMENT ▼",
};

// Category-specific empty-state copy. Explains WHY the section is empty
// rather than a generic "No names yet" that reads as "something's broken."
const EMPTY_MESSAGES: Record<WatchlistCategoryKey, string> = {
  hot_now: "Quiet market — no significant moves yet",
  earnings: "No earnings in your watchlist this week",
  unusual_options: "No abnormal options flow detected",
  sentiment_up: "No names yet",
  sentiment_down: "No names yet",
};

export function WatchlistCategory({ category, items, note, selectedSymbol, onSelect }: Props) {
  const label = CATEGORY_LABELS[category];
  const count = items.length;
  // `note` (from backend) takes priority — used for "Sentiment unavailable
  // on free tier" today. Falls back to the per-category default copy.
  const emptyText = note ?? EMPTY_MESSAGES[category];

  return (
    <div className="mb-3">
      <div className="flex items-baseline justify-between px-3 pt-1.5 pb-1">
        <div className="flex items-center gap-1">
          <span aria-hidden className="text-tiny text-fg-tertiary">
            ▾
          </span>
          <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
            {label}
          </span>
        </div>
        {count > 0 && (
          <span className="text-tiny text-fg-tertiary tabular-nums">({count})</span>
        )}
      </div>
      {items.length === 0 ? (
        <div className="px-3 py-1.5 text-tiny text-fg-tertiary">{emptyText}</div>
      ) : (
        items.map((item) => (
          <ItemRow
            key={`${category}:${item.symbol}`}
            item={item}
            selected={selectedSymbol === item.symbol}
            onSelect={onSelect}
          />
        ))
      )}
    </div>
  );
}
