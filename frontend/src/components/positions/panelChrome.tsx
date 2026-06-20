import type { ReactNode } from "react";

/**
 * Shared chrome for the bottom-strip FEED panel.
 *
 * Exact replica of BottomStrip's ColHeader (1px hairline, bg-tier-1, the
 * 9–10px uppercase tracked label). The right slot carries the refreshed
 * relative-time label and, optionally, a `headerControl` rendered just to
 * its left.
 */
export function PanelHeader({
  left,
  right,
  headerControl,
}: {
  left: string;
  right: string;
  headerControl?: ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2 px-3 py-1 border-b border-hairline bg-tier-1 shrink-0">
      <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
        {left}
      </span>
      <span className="flex items-baseline gap-2 shrink-0">
        {right && (
          <span
            className="uppercase tracking-label-up text-fg-tertiary-2"
            style={{ fontSize: 11 }}
          >
            {right}
          </span>
        )}
        {headerControl}
      </span>
    </div>
  );
}

/** Compact relative time: "just now", "12m ago", "3h ago", "2d ago". */
export function relativeTime(iso: string): string {
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
