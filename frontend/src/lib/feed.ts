import type { CombineEvent } from "@/types/combine";
import type { FeedEvent, FeedTone } from "@/types/feed";
import type { Trade } from "@/types/journal";
import { STRATEGY_LABELS } from "@/types/journal";
import type {
  WatchlistCategoryKey,
  WatchlistItem,
  WatchlistResponse,
} from "@/types/watchlist";

/** Fixed category order — mirrors WatchlistColumn's CATEGORY_ORDER so the
 *  feed clusters signals the same way the watchlist rail does. */
export const FEED_CATEGORY_ORDER: WatchlistCategoryKey[] = [
  "hot_now",
  "earnings",
  "unusual_options",
  "sentiment_up",
  "sentiment_down",
];

/** Condensed badge tag per signal category (fits the ~90px col5). */
export const SIGNAL_BADGE: Record<WatchlistCategoryKey, string> = {
  hot_now: "HOT",
  earnings: "ER",
  unusual_options: "FLOW",
  sentiment_up: "SENT▲",
  sentiment_down: "SENT▼",
};

/** Full label for tooltip / wide-box readability. */
const CATEGORY_LABEL: Record<WatchlistCategoryKey, string> = {
  hot_now: "Hot now",
  earnings: "Earnings soon",
  unusual_options: "Unusual options",
  sentiment_up: "Sentiment up",
  sentiment_down: "Sentiment down",
};

function signalTone(category: WatchlistCategoryKey, changePct: number): FeedTone {
  if (category === "sentiment_up") return "bullish";
  if (category === "sentiment_down") return "bearish";
  return changePct >= 0 ? "bullish" : "bearish";
}

function closeTone(realizedPnl: number): FeedTone {
  if (realizedPnl > 0) return "bullish";
  if (realizedPnl < 0) return "bearish";
  return "neutral";
}

function eventTone(type: string): FeedTone {
  if (type === "funded" || type === "payout") return "bullish";
  if (type === "failed") return "bearish";
  return "neutral"; // settled, reset
}

function strategyLabel(strategy: string): string {
  return STRATEGY_LABELS[strategy] ?? strategy;
}

/**
 * Merge the global watchlist signals and the user's trade open/close
 * events into one descending-by-time tape. Pure (no React, no Date.now
 * dependence beyond the inputs' own timestamps) so it's trivially
 * testable.
 *
 * Signals share the watchlist's single `updated_at` (there is no
 * per-item timestamp), so they tie on `ts`; the tie-break is fixed
 * category order then symbol, which keeps ordering deterministic and
 * clusters signals together just below any newer trade events. Each
 * signal carries a stable `signal:<category>:<symbol>` key so the same
 * row doesn't flicker as the 30s poll re-stamps `updated_at`.
 */
export function buildFeedEvents(
  watchlist: WatchlistResponse | undefined,
  trades: Trade[],
  lifecycle: CombineEvent[] = [],
  cap = 50,
): FeedEvent[] {
  const events: FeedEvent[] = [];

  for (const e of lifecycle) {
    const ts = Date.parse(e.created_at);
    events.push({
      kind: "lifecycle",
      key: `event:${e.id}`,
      ts: Number.isFinite(ts) ? ts : 0,
      symbol: e.combine_name ?? "Account",
      tone: eventTone(e.type),
      eventType: e.type,
      label: e.type,
      detail: e.message,
    });
  }

  if (watchlist) {
    const signalTs = Date.parse(watchlist.updated_at);
    const ts = Number.isFinite(signalTs) ? signalTs : 0;
    for (const category of FEED_CATEGORY_ORDER) {
      const items = watchlist[category] as WatchlistItem[];
      for (const item of items) {
        events.push({
          kind: "signal",
          key: `signal:${category}:${item.symbol}`,
          ts,
          symbol: item.symbol,
          tone: signalTone(category, item.change_pct),
          category,
          label: CATEGORY_LABEL[category],
          detail: item.subtitle,
        });
      }
    }
  }

  for (const t of trades) {
    const openTs = Date.parse(t.entry_date);
    events.push({
      kind: "trade_open",
      key: `open:${t.id}`,
      ts: Number.isFinite(openTs) ? openTs : 0,
      symbol: t.symbol,
      tone: "neutral",
      strategy: t.strategy,
      label: "Opened",
      detail: strategyLabel(t.strategy),
    });
    if (t.status === "closed" && t.exit_date) {
      const closeTs = Date.parse(t.exit_date);
      const pnl = t.realized_pnl ?? 0;
      events.push({
        kind: "trade_close",
        key: `close:${t.id}`,
        ts: Number.isFinite(closeTs) ? closeTs : 0,
        symbol: t.symbol,
        tone: closeTone(pnl),
        strategy: t.strategy,
        realizedPnl: pnl,
        label: "Closed",
        detail: strategyLabel(t.strategy),
      });
    }
  }

  // Secondary rank on ts ties: trades (real timestamps) before signals,
  // then signal category order, then symbol — fully deterministic.
  const rank = (e: FeedEvent): number =>
    e.kind === "signal" ? FEED_CATEGORY_ORDER.indexOf(e.category) : -1;

  events.sort(
    (a, b) =>
      b.ts - a.ts || rank(a) - rank(b) || a.symbol.localeCompare(b.symbol),
  );

  return events.slice(0, cap);
}
