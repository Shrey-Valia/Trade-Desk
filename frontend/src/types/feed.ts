import type { WatchlistCategoryKey } from "@/types/watchlist";

/** Visual tone for a feed row — drives bullish/bearish/neutral coloring,
 *  the same convention TodayRow and WatchlistItem use. */
export type FeedTone = "bullish" | "bearish" | "neutral";

/**
 * A single entry in the Live Feed tape. A client-derived discriminated
 * union (NOT a wire type — these are synthesized from the watchlist +
 * journal queries, so no zod schema). `ts` is epoch ms for sorting,
 * `key` is a stable React/dedupe key, `label` is the primary text and
 * `detail` the secondary line.
 */
export type FeedEvent =
  | {
      kind: "signal";
      key: string;
      ts: number;
      symbol: string;
      tone: FeedTone;
      category: WatchlistCategoryKey;
      label: string;
      detail: string;
    }
  | {
      kind: "trade_open";
      key: string;
      ts: number;
      symbol: string;
      tone: FeedTone;
      strategy: string;
      label: string;
      detail: string;
    }
  | {
      kind: "trade_close";
      key: string;
      ts: number;
      symbol: string;
      tone: FeedTone;
      strategy: string;
      realizedPnl: number;
      label: string;
      detail: string;
    };
