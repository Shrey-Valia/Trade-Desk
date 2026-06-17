import type { ReactNode } from "react";

import { PanelHeader, relativeTime } from "@/components/positions/panelChrome";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { useTickerNews } from "@/hooks/useTickerNews";
import type { NewsItem } from "@/types/news";

/**
 * NEWS — 5th bottom-row panel. Ticker-scoped headlines in a single
 * horizontally-scrolling row of fixed-width cards (readable within the
 * short bottom-row height, vs. a cramped truncated vertical list).
 *
 * Renders as a native sibling of the other Col* panels: same ColHeader
 * chrome, same Empty treatment. Reads the active symbol (passed from
 * BottomStrip) so it re-fetches when the user changes ticker.
 *
 * Three required states, all visually distinct:
 *   - loading : skeleton cards in the scroll row (no spinner)
 *   - empty   : quiet tertiary line "No recent news for SYM"
 *   - error   : quiet "News unavailable" + ghost retry (the 503/429 case)
 */
export function NewsPanel({
  symbol,
  headerControl,
}: {
  symbol: string | null;
  headerControl?: ReactNode;
}) {
  const query = useTickerNews(symbol);
  const items = query.data?.items ?? [];
  const showError = query.isError && items.length === 0;
  const showLoading = query.isLoading && items.length === 0;
  const showEmpty = !showLoading && !showError && items.length === 0;

  const refreshedLabel =
    items.length > 0 && query.dataUpdatedAt
      ? relativeTime(new Date(query.dataUpdatedAt).toISOString())
      : "";

  return (
    <>
      <PanelHeader
        left={`News${symbol ? ` · ${symbol}` : ""}`}
        right={refreshedLabel}
        headerControl={headerControl}
      />
      {showLoading ? (
        <LoadingCards />
      ) : showError ? (
        <ErrorState onRetry={() => query.refetch()} />
      ) : showEmpty ? (
        <EmptyState symbol={symbol} />
      ) : (
        <div
          className="news-scroll flex-1 min-h-0 flex overflow-x-auto overflow-y-hidden"
          style={{ scrollbarGutter: "stable" }}
        >
          {items.map((it) => (
            <NewsCard key={it.id} item={it} />
          ))}
        </div>
      )}
    </>
  );
}

const CARD_WIDTH = 196;

function NewsCard({ item }: { item: NewsItem }) {
  return (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      className="shrink-0 h-full flex flex-col gap-1 px-3 py-1.5 border-r border-hairline hover:bg-tier-2 transition-colors duration-100 tabular-nums"
      style={{ width: CARD_WIDTH }}
      title={item.headline}
    >
      <Badge tone="cyan">{truncateSource(item.source) || "news"}</Badge>
      {/* 2-line clamp + no summary: news reads as a quick-scan feature, not
          a content wall. Full headline is in the title tooltip. */}
      <span
        className="text-tiny text-fg-secondary"
        style={{
          display: "-webkit-box",
          WebkitBoxOrient: "vertical",
          WebkitLineClamp: 2,
          overflow: "hidden",
        }}
      >
        {item.headline}
      </span>
      <span className="text-tiny text-fg-tertiary mt-auto" style={{ fontSize: 10 }}>
        {relativeTime(item.created_at)}
      </span>
    </a>
  );
}

function LoadingCards() {
  return (
    <div className="flex-1 min-h-0 flex overflow-hidden" aria-hidden>
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="shrink-0 h-full flex flex-col gap-2 px-3 py-2 border-r border-hairline"
          style={{ width: CARD_WIDTH }}
        >
          <Skeleton width={56} height={12} />
          <Skeleton width="90%" height={11} />
          <Skeleton width="80%" height={11} />
          <Skeleton width="60%" height={11} />
          <div className="mt-auto">
            <Skeleton width={48} height={9} />
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState({ symbol }: { symbol: string | null }) {
  return (
    <div className="flex-1 flex items-center justify-center text-tiny text-fg-tertiary-2 px-4 text-center">
      No recent news for {symbol ?? "—"}.
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-1.5 px-4 text-center">
      <span className="text-tiny text-fg-tertiary">News unavailable</span>
      <button
        type="button"
        onClick={onRetry}
        className="text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-amber transition-colors duration-100"
        style={{ fontSize: 9 }}
      >
        retry
      </button>
    </div>
  );
}

function truncateSource(source: string): string {
  const s = source.trim();
  return s.length > 18 ? `${s.slice(0, 17)}…` : s;
}
