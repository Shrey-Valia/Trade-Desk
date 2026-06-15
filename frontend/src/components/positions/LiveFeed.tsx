import type { ReactNode } from "react";

import { PanelHeader, relativeTime } from "@/components/positions/panelChrome";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { useLiveFeed } from "@/hooks/useLiveFeed";
import { formatChangeDollar } from "@/lib/formatters";
import { SIGNAL_BADGE } from "@/lib/feed";
import type { FeedEvent, FeedTone } from "@/types/feed";

/**
 * LIVE FEED — the bottom-strip tape that swaps in for NEWS. A unified,
 * newest-first list merging global watchlist signals with the user's own
 * trade opens/closes (see lib/feed.buildFeedEvents).
 *
 * Renders the same fragment shape as NewsPanel (PanelHeader + body) so it
 * drops into both bottom-strip boxes. Unlike NewsPanel's horizontal cards
 * the body scrolls VERTICALLY, and each row is a two-line layout that
 * stays legible in the narrow ~90px col5 as well as the wide box.
 */
export function LiveFeed({ headerControl }: { headerControl?: ReactNode }) {
  const { events, isLoading, isError, updatedAt, refetch } = useLiveFeed();

  const refreshedLabel =
    events.length > 0 && updatedAt
      ? relativeTime(new Date(updatedAt).toISOString())
      : "";
  const showError = isError && events.length === 0;
  const showLoading = isLoading && events.length === 0;
  const showEmpty = !showLoading && !showError && events.length === 0;

  return (
    <>
      <PanelHeader left="Feed" right={refreshedLabel} headerControl={headerControl} />
      {showLoading ? (
        <LoadingRows />
      ) : showError ? (
        <ErrorState onRetry={refetch} />
      ) : showEmpty ? (
        <EmptyState />
      ) : (
        <div className="flex-1 min-h-0 overflow-y-auto" style={{ scrollbarGutter: "stable" }}>
          {events.map((ev) => (
            <FeedRow key={ev.key} ev={ev} />
          ))}
        </div>
      )}
    </>
  );
}

const TONE_TEXT: Record<FeedTone, string> = {
  bullish: "text-bullish",
  bearish: "text-bearish",
  neutral: "text-fg-secondary",
};

function FeedRow({ ev }: { ev: FeedEvent }) {
  const toneText = TONE_TEXT[ev.tone];
  return (
    <div
      className="flex flex-col gap-0.5 px-3 py-1 border-b border-hairline tabular-nums"
      title={`${ev.label} · ${ev.symbol} · ${ev.detail}`}
    >
      <div className="flex items-center gap-2">
        <span className="text-fg-tertiary shrink-0" style={{ fontSize: 9 }}>
          {relativeTime(new Date(ev.ts).toISOString())}
        </span>
        <FeedBadge ev={ev} />
      </div>
      <div className="flex items-baseline gap-1.5 min-w-0">
        <span className="text-tiny text-fg-primary shrink-0">{ev.symbol}</span>
        <span className={`text-tiny truncate ${toneText}`}>{ev.detail}</span>
        {ev.kind === "trade_close" && (
          <span className={`text-tiny ml-auto shrink-0 ${toneText}`}>
            {formatChangeDollar(ev.realizedPnl)}
          </span>
        )}
      </div>
    </div>
  );
}

function FeedBadge({ ev }: { ev: FeedEvent }) {
  if (ev.kind === "signal") {
    return <Badge tone="cyan">{SIGNAL_BADGE[ev.category]}</Badge>;
  }
  if (ev.kind === "trade_open") {
    return <Badge tone="amber">OPEN</Badge>;
  }
  const tone: BadgeTone =
    ev.tone === "bullish" ? "bullish" : ev.tone === "bearish" ? "bearish" : "muted";
  return <Badge tone={tone}>CLOSE</Badge>;
}

function LoadingRows() {
  return (
    <div className="flex-1 min-h-0 overflow-hidden" aria-hidden>
      {[0, 1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className="flex flex-col gap-1 px-3 py-1.5 border-b border-hairline"
        >
          <Skeleton width={64} height={9} />
          <Skeleton width="80%" height={11} />
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex-1 flex items-center justify-center text-tiny text-fg-tertiary-2 px-4 text-center">
      No recent activity.
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-1.5 px-4 text-center">
      <span className="text-tiny text-fg-tertiary">Feed unavailable</span>
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
