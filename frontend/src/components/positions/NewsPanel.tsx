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
export function NewsPanel({ symbol }: { symbol: string | null }) {
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
      <Header left={`News${symbol ? ` · ${symbol}` : ""}`} right={refreshedLabel} />
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

const CARD_WIDTH = 220;

function NewsCard({ item }: { item: NewsItem }) {
  return (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      className="shrink-0 h-full flex flex-col gap-1.5 px-3 py-2 border-r border-hairline hover:bg-tier-2 transition-colors duration-100 tabular-nums"
      style={{ width: CARD_WIDTH }}
      title={item.headline}
    >
      <Badge tone="cyan">{truncateSource(item.source) || "news"}</Badge>
      <span
        className="text-body text-fg-primary"
        style={{
          display: "-webkit-box",
          WebkitBoxOrient: "vertical",
          WebkitLineClamp: 3,
          overflow: "hidden",
        }}
      >
        {item.headline}
      </span>
      {item.summary && (
        <span className="text-tiny text-fg-tertiary-2 truncate">
          {item.summary}
        </span>
      )}
      <span className="text-tiny text-fg-tertiary mt-auto" style={{ fontSize: 11 }}>
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

/** Exact replica of BottomStrip's ColHeader chrome so the NEWS panel
 *  header matches the other four panels (1px hairline, bg-tier-1, the
 *  9–10px uppercase tracked label). Kept local to avoid exporting/
 *  refactoring BottomStrip internals. */
function Header({ left, right }: { left: string; right: string }) {
  return (
    <div className="flex items-baseline justify-between px-3 py-1 border-b border-hairline bg-tier-1 shrink-0">
      <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
        {left}
      </span>
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 9 }}
      >
        {right}
      </span>
    </div>
  );
}

function truncateSource(source: string): string {
  const s = source.trim();
  return s.length > 18 ? `${s.slice(0, 17)}…` : s;
}

/** Compact relative time: "just now", "12m ago", "3h ago", "2d ago". */
function relativeTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "";
  const diffSec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (diffSec < 60) return "just now";
  const min = Math.floor(diffSec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}
